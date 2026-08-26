import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from access_control import is_within_rate_limit
from ai import analyze_image, ask_ai
from memory import clear_history, get_history, save_turn
from miniapp_auth import (
    MiniappConfigurationError,
    MiniappExchangeError,
    MiniappSessionStoreError,
    create_session,
    exchange_code_for_openid,
    get_current_miniapp_user,
)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/miniapp/v1", tags=["miniapp"])

MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_HISTORY_PLACEHOLDER = "[用户发送了一张图片]"
ALLOWED_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)
INVALID_IMAGE_DETAIL = "图片格式或大小不符合要求。"


def _has_valid_image_signature(image_bytes: bytes, mime_type: str) -> bool:
    if mime_type == "image/jpeg":
        return image_bytes.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return (
            len(image_bytes) >= 12
            and image_bytes.startswith(b"RIFF")
            and image_bytes[8:12] == b"WEBP"
        )
    return False


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    code: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: Literal["Bearer"] = "Bearer"
    expires_in: int


class MeResponse(BaseModel):
    authenticated: Literal[True] = True


class ChatRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    message: StrictStr = Field(min_length=1, max_length=2000)


class ChatResponse(BaseModel):
    reply: str


class HistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class HistoryResponse(BaseModel):
    messages: list[HistoryMessage]


class MemoryClearResponse(BaseModel):
    cleared: Literal[True] = True


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest) -> LoginResponse:
    try:
        user_id = await exchange_code_for_openid(payload.code)
    except MiniappConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Miniapp login is temporarily unavailable",
        ) from exc
    except MiniappExchangeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="WeChat login failed",
        ) from exc

    try:
        access_token, expires_in = create_session(user_id)
    except MiniappSessionStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from exc

    return LoginResponse(
        access_token=access_token,
        expires_in=expires_in,
    )


@router.get("/me", response_model=MeResponse)
def me(
    _user_id: str = Depends(get_current_miniapp_user),
) -> MeResponse:
    return MeResponse()


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_miniapp_user),
) -> ChatResponse:
    if not is_within_rate_limit(user_id, channel="miniapp"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="消息发送太频繁，请稍后再试。",
        )

    history = get_history(user_id, channel="miniapp")
    try:
        reply = ask_ai(payload.message, history)
    except Exception as exc:
        logger.warning("Miniapp AI reply failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI暂时无法回复，请稍后再试。",
        ) from exc

    save_turn(
        user_id,
        payload.message,
        reply,
        channel="miniapp",
    )
    return ChatResponse(reply=reply)


@router.get("/history", response_model=HistoryResponse)
def history(
    user_id: str = Depends(get_current_miniapp_user),
) -> HistoryResponse:
    messages = get_history(user_id, channel="miniapp")
    return HistoryResponse(messages=messages)


@router.post("/image", response_model=ChatResponse)
def image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_miniapp_user),
) -> ChatResponse:
    mime_type = (file.content_type or "").strip().lower()
    if mime_type not in ALLOWED_IMAGE_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=INVALID_IMAGE_DETAIL,
        )

    try:
        image_bytes = file.file.read(MAX_IMAGE_BYTES + 1)
    except Exception as exc:
        logger.warning("Miniapp image upload read failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=INVALID_IMAGE_DETAIL,
        ) from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    if not image_bytes or not _has_valid_image_signature(image_bytes, mime_type):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=INVALID_IMAGE_DETAIL,
        )
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=INVALID_IMAGE_DETAIL,
        )

    if not is_within_rate_limit(user_id, channel="miniapp"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="消息发送太频繁，请稍后再试。",
        )

    try:
        reply = analyze_image(image_bytes, mime_type)
    except Exception as exc:
        logger.warning("Miniapp image analysis failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI暂时无法分析这张图片，请稍后再试。",
        ) from exc

    save_turn(
        user_id,
        IMAGE_HISTORY_PLACEHOLDER,
        reply,
        channel="miniapp",
    )
    return ChatResponse(reply=reply)


@router.delete("/memory", response_model=MemoryClearResponse)
def delete_memory(
    user_id: str = Depends(get_current_miniapp_user),
) -> MemoryClearResponse:
    clear_history(user_id, channel="miniapp")
    return MemoryClearResponse()
