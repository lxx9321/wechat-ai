import logging
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

import web_auth
from access_control import is_within_rate_limit
from ai import analyze_image, ask_ai
from image_validation import ImageTooLarge, InvalidImageUpload, read_and_validate_image
from memory import clear_history, get_history, save_turn
from web_auth import WebSessionStoreError, get_current_web_user


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/web/v1", tags=["web"])

IMAGE_HISTORY_PLACEHOLDER = "[用户发送了一张图片]"
INVALID_IMAGE_DETAIL = "图片格式或大小不符合要求。"


class AuthenticatedResponse(BaseModel):
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


@router.post("/session", response_model=AuthenticatedResponse)
def create_web_session(response: Response) -> AuthenticatedResponse:
    try:
        session_token, expires_in = web_auth.create_session()
    except WebSessionStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from exc

    response.set_cookie(
        key=web_auth.WEB_COOKIE_NAME,
        value=session_token,
        max_age=expires_in,
        path="/",
        secure=web_auth.WEB_COOKIE_SECURE,
        httponly=True,
        samesite="lax",
    )
    return AuthenticatedResponse()


@router.get("/me", response_model=AuthenticatedResponse)
def me(_user_id: str = Depends(get_current_web_user)) -> AuthenticatedResponse:
    return AuthenticatedResponse()


@router.get("/history", response_model=HistoryResponse)
def history(user_id: str = Depends(get_current_web_user)) -> HistoryResponse:
    messages = get_history(user_id, channel="web")
    return HistoryResponse(messages=messages)


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    user_id: str = Depends(get_current_web_user),
) -> ChatResponse:
    if not is_within_rate_limit(user_id, channel="web"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="消息发送太频繁，请稍后再试。",
        )

    history_messages = get_history(user_id, channel="web")
    try:
        reply = ask_ai(payload.message, history_messages)
    except Exception as exc:
        logger.warning("Web AI reply failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI暂时无法回复，请稍后再试。",
        ) from exc

    save_turn(
        user_id,
        payload.message,
        reply,
        channel="web",
    )
    return ChatResponse(reply=reply)


@router.post("/image", response_model=ChatResponse)
def image(
    file: UploadFile = File(...),
    user_id: str = Depends(get_current_web_user),
) -> ChatResponse:
    try:
        image_bytes, mime_type = read_and_validate_image(
            file.file,
            file.content_type or "",
        )
    except ImageTooLarge as exc:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=INVALID_IMAGE_DETAIL,
        ) from exc
    except InvalidImageUpload as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=INVALID_IMAGE_DETAIL,
        ) from exc
    finally:
        try:
            file.file.close()
        except Exception:
            pass

    if not is_within_rate_limit(user_id, channel="web"):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="消息发送太频繁，请稍后再试。",
        )

    try:
        reply = analyze_image(image_bytes, mime_type)
    except Exception as exc:
        logger.warning("Web image analysis failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="AI暂时无法分析这张图片，请稍后再试。",
        ) from exc

    save_turn(
        user_id,
        IMAGE_HISTORY_PLACEHOLDER,
        reply,
        channel="web",
    )
    return ChatResponse(reply=reply)


@router.delete("/memory", response_model=MemoryClearResponse)
def delete_memory(
    user_id: str = Depends(get_current_web_user),
) -> MemoryClearResponse:
    clear_history(user_id, channel="web")
    return MemoryClearResponse()
