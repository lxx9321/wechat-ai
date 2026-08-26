import hashlib
import json
import os
import secrets

import redis
from dotenv import load_dotenv
from fastapi import HTTPException, Request, status


load_dotenv()

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_SESSION_TTL_SECONDS = 2592000
DEFAULT_COOKIE_NAME = "web_session"
SESSION_TOKEN_BYTES = 32
USER_ID_BYTES = 24


class WebAuthError(RuntimeError):
    """Web 匿名会话处理失败。"""


class WebSessionStoreError(WebAuthError):
    """Redis Web 会话读写失败。"""


class InvalidWebSession(WebAuthError):
    """Web 会话不存在、过期或内容无效。"""


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        return default


def _bool_from_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


REDIS_URL = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
WEB_SESSION_TTL_SECONDS = _positive_int_from_env(
    "WEB_SESSION_TTL_SECONDS",
    DEFAULT_SESSION_TTL_SECONDS,
)
WEB_COOKIE_NAME = os.getenv("WEB_COOKIE_NAME", DEFAULT_COOKIE_NAME).strip()
if not WEB_COOKIE_NAME:
    WEB_COOKIE_NAME = DEFAULT_COOKIE_NAME
WEB_COOKIE_SECURE = _bool_from_env("WEB_COOKIE_SECURE", False)

_redis_client: redis.Redis | None = None


def _get_client() -> redis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis.from_url(
            REDIS_URL,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
    return _redis_client


def _token_hash(session_token: str) -> str:
    return hashlib.sha256(session_token.encode("utf-8")).hexdigest()


def _session_key(session_token: str) -> str:
    return f"web:session:{_token_hash(session_token)}"


def create_session() -> tuple[str, int]:
    session_token = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
    user_id = secrets.token_urlsafe(USER_ID_BYTES)
    session_value = json.dumps(
        {"user_id": user_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )

    try:
        _get_client().set(
            _session_key(session_token),
            session_value,
            ex=WEB_SESSION_TTL_SECONDS,
        )
    except Exception as exc:
        raise WebSessionStoreError("session creation failed") from exc

    return session_token, WEB_SESSION_TTL_SECONDS


def get_user_for_token(session_token: str) -> str:
    normalized_token = session_token.strip()
    if not normalized_token:
        raise InvalidWebSession("empty session token")

    try:
        session_value = _get_client().get(_session_key(normalized_token))
    except Exception as exc:
        raise WebSessionStoreError("session lookup failed") from exc

    if session_value is None:
        raise InvalidWebSession("session not found")

    try:
        if isinstance(session_value, bytes):
            session_value = session_value.decode("utf-8")
        payload = json.loads(session_value)
        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("invalid user_id")
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidWebSession("invalid session content") from exc

    return user_id.strip()


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
    )


def get_current_web_user(request: Request) -> str:
    session_token = request.cookies.get(WEB_COOKIE_NAME)
    if session_token is None:
        raise _unauthorized()

    try:
        return get_user_for_token(session_token)
    except InvalidWebSession as exc:
        raise _unauthorized() from exc
    except WebSessionStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from exc
