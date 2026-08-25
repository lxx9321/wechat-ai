import logging
import os

import redis
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_RATE_LIMIT_10_SECONDS = 3
DEFAULT_RATE_LIMIT_60_SECONDS = 10


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
RATE_LIMIT_10_SECONDS = _positive_int_from_env(
    "RATE_LIMIT_10_SECONDS", DEFAULT_RATE_LIMIT_10_SECONDS
)
RATE_LIMIT_60_SECONDS = _positive_int_from_env(
    "RATE_LIMIT_60_SECONDS", DEFAULT_RATE_LIMIT_60_SECONDS
)

_redis_client: redis.Redis | None = None

_RATE_LIMIT_SCRIPT = """
local count_10s = redis.call('INCR', KEYS[1])
if count_10s == 1 then
    redis.call('EXPIRE', KEYS[1], 10)
end

local count_60s = redis.call('INCR', KEYS[2])
if count_60s == 1 then
    redis.call('EXPIRE', KEYS[2], 60)
end

return {count_10s, count_60s}
"""


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


def _rate_keys(user_id: str) -> tuple[str, str]:
    return (
        f"wechat:rate:{user_id}:10s",
        f"wechat:rate:{user_id}:60s",
    )


def is_user_allowed(user_id: str) -> bool:
    whitelist_enabled = (
        os.getenv("WECHAT_WHITELIST_ENABLED", "false").strip().lower()
        == "true"
    )
    if not whitelist_enabled:
        return True

    allowed_users = {
        item.strip()
        for item in os.getenv("WECHAT_ALLOWED_USERS", "").split(",")
        if item.strip()
    }
    return bool(user_id) and user_id in allowed_users


def is_within_rate_limit(user_id: str) -> bool:
    key_10s, key_60s = _rate_keys(user_id)
    try:
        counts = _get_client().eval(
            _RATE_LIMIT_SCRIPT,
            2,
            key_10s,
            key_60s,
        )
        count_10s, count_60s = (int(counts[0]), int(counts[1]))
        return (
            count_10s <= RATE_LIMIT_10_SECONDS
            and count_60s <= RATE_LIMIT_60_SECONDS
        )
    except Exception as exc:
        logger.warning(
            "Redis rate limit check failed: %s; allowing request",
            type(exc).__name__,
        )
        return True
