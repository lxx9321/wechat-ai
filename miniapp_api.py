import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from access_control import is_within_rate_limit
from ai import ask_ai
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


@router.delete("/memory", response_model=MemoryClearResponse)
def delete_memory(
    user_id: str = Depends(get_current_miniapp_user),
) -> MemoryClearResponse:
    clear_history(user_id, channel="miniapp")
    return MemoryClearResponse()
