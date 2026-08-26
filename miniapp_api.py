from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from miniapp_auth import (
    MiniappConfigurationError,
    MiniappExchangeError,
    MiniappSessionStoreError,
    create_session,
    exchange_code_for_openid,
    get_current_miniapp_user,
)


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
