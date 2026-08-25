import json
import logging
import os

import redis
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
DEFAULT_MAX_HISTORY_ROUNDS = 6
DEFAULT_HISTORY_TTL_SECONDS = 604800


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
MAX_HISTORY_ROUNDS = _positive_int_from_env(
    "MAX_HISTORY_ROUNDS", DEFAULT_MAX_HISTORY_ROUNDS
)
HISTORY_TTL_SECONDS = _positive_int_from_env(
    "HISTORY_TTL_SECONDS", DEFAULT_HISTORY_TTL_SECONDS
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


def _history_key(user_id: str) -> str:
    return f"wechat:history:{user_id}"


def _log_failure(action: str, exc: Exception) -> None:
    logger.warning("Redis history %s failed: %s", action, type(exc).__name__)


def get_history(user_id: str) -> list[dict]:
    try:
        items = _get_client().lrange(_history_key(user_id), 0, -1)
        history = []
        for item in items:
            if isinstance(item, bytes):
                item = item.decode("utf-8")
            message = json.loads(item)
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"user", "assistant"}
                or not isinstance(message.get("content"), str)
            ):
                raise ValueError("invalid history item")
            history.append(
                {"role": message["role"], "content": message["content"]}
            )
        return history
    except Exception as exc:
        _log_failure("read", exc)
        return []


def save_turn(user_id: str, user_message: str, assistant_message: str) -> None:
    try:
        key = _history_key(user_id)
        max_messages = MAX_HISTORY_ROUNDS * 2
        user_item = json.dumps(
            {"role": "user", "content": user_message},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        assistant_item = json.dumps(
            {"role": "assistant", "content": assistant_message},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        pipeline = _get_client().pipeline(transaction=True)
        pipeline.rpush(key, user_item, assistant_item)
        pipeline.ltrim(key, -max_messages, -1)
        pipeline.expire(key, HISTORY_TTL_SECONDS)
        pipeline.execute()
    except Exception as exc:
        _log_failure("write", exc)


def clear_history(user_id: str) -> None:
    try:
        _get_client().delete(_history_key(user_id))
    except Exception as exc:
        _log_failure("clear", exc)
