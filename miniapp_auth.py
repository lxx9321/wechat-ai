import hashlib
import json
import logging
import os
import secrets

import httpx
import redis
from dotenv import load_dotenv
from fastapi import Header, HTTPException, status


load_dotenv()

logger = logging.getLogger(__name__)

JSCODE2SESSION_URL = "https://api.weixin.qq.com/sns/jscode2session"
WECHAT_API_TIMEOUT_SECONDS = 2.0
DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_SESSION_TTL_SECONDS = 604800
TOKEN_BYTES = 32


class _Jscode2SessionLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if (
            record.name == "httpx"
            and isinstance(args, tuple)
            and len(args) >= 2
            and str(args[1]).startswith(JSCODE2SESSION_URL)
        ):
            redacted_args = list(args)
            redacted_args[1] = f"{JSCODE2SESSION_URL}?[REDACTED]"
            record.args = tuple(redacted_args)
        return True


logging.getLogger("httpx").addFilter(_Jscode2SessionLogFilter())


class MiniappAuthError(RuntimeError):
    """小程序登录或服务端会话处理失败。"""


class MiniappConfigurationError(MiniappAuthError):
    """小程序登录配置缺失或无效。"""


class MiniappExchangeError(MiniappAuthError):
    """微信登录凭证校验失败。"""


class MiniappSessionStoreError(MiniappAuthError):
    """Redis 服务端会话读写失败。"""


class InvalidMiniappSession(MiniappAuthError):
    """服务端会话不存在、过期或内容无效。"""


def _positive_int_from_env(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        if value <= 0:
            raise ValueError
        return value
    except ValueError:
        logger.warning("Invalid %s; using default", name)
        return default


REDIS_URL = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)
MINIAPP_APP_ID = os.getenv("MINIAPP_APP_ID", "").strip()
MINIAPP_APP_SECRET = os.getenv("MINIAPP_APP_SECRET", "").strip()
MINIAPP_SESSION_TTL_SECONDS = _positive_int_from_env(
    "MINIAPP_SESSION_TTL_SECONDS", DEFAULT_SESSION_TTL_SECONDS
)

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


def _token_hash(access_token: str) -> str:
    return hashlib.sha256(access_token.encode("utf-8")).hexdigest()


def _session_key(access_token: str) -> str:
    return f"miniapp:session:{_token_hash(access_token)}"


async def exchange_code_for_openid(code: str) -> str:
    normalized_code = code.strip()
    if not normalized_code:
        raise MiniappExchangeError("empty login code")
    if not MINIAPP_APP_ID or not MINIAPP_APP_SECRET:
        raise MiniappConfigurationError("miniapp credentials are missing")

    transport = httpx.AsyncHTTPTransport(retries=0)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(WECHAT_API_TIMEOUT_SECONDS),
            transport=transport,
        ) as client:
            response = await client.get(
                JSCODE2SESSION_URL,
                params={
                    "appid": MINIAPP_APP_ID,
                    "secret": MINIAPP_APP_SECRET,
                    "js_code": normalized_code,
                    "grant_type": "authorization_code",
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise MiniappExchangeError("jscode2session request failed") from exc

    if not isinstance(data, dict):
        raise MiniappExchangeError("jscode2session response was invalid")
    if data.get("errcode") not in (None, 0):
        raise MiniappExchangeError("jscode2session returned an error")

    openid = data.get("openid")
    if not isinstance(openid, str) or not openid.strip():
        raise MiniappExchangeError("jscode2session response had no openid")
    return openid.strip()


def create_session(user_id: str) -> tuple[str, int]:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        raise ValueError("user_id must not be empty")

    access_token = secrets.token_urlsafe(TOKEN_BYTES)
    session_value = json.dumps(
        {"user_id": normalized_user_id},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    try:
        _get_client().set(
            _session_key(access_token),
            session_value,
            ex=MINIAPP_SESSION_TTL_SECONDS,
        )
    except Exception as exc:
        raise MiniappSessionStoreError("session creation failed") from exc
    return access_token, MINIAPP_SESSION_TTL_SECONDS


def get_user_for_token(access_token: str) -> str:
    normalized_token = access_token.strip()
    if not normalized_token:
        raise InvalidMiniappSession("empty access token")

    try:
        session_value = _get_client().get(_session_key(normalized_token))
    except Exception as exc:
        raise MiniappSessionStoreError("session lookup failed") from exc

    if session_value is None:
        raise InvalidMiniappSession("session not found")

    try:
        if isinstance(session_value, bytes):
            session_value = session_value.decode("utf-8")
        payload = json.loads(session_value)
        user_id = payload.get("user_id") if isinstance(payload, dict) else None
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError("invalid user_id")
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidMiniappSession("invalid session content") from exc

    return user_id.strip()


def invalidate_session(access_token: str) -> None:
    normalized_token = access_token.strip()
    if not normalized_token:
        raise InvalidMiniappSession("empty access token")
    try:
        _get_client().delete(_session_key(normalized_token))
    except Exception as exc:
        raise MiniappSessionStoreError("session invalidation failed") from exc


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_current_miniapp_user(
    authorization: str | None = Header(default=None),
) -> str:
    if authorization is None:
        raise _unauthorized()

    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1]:
        raise _unauthorized()

    try:
        return get_user_for_token(parts[1])
    except InvalidMiniappSession as exc:
        raise _unauthorized() from exc
    except MiniappSessionStoreError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from exc
