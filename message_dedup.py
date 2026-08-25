import hashlib
import hmac
import json
import logging
import os

import redis
from dotenv import load_dotenv


load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_REDIS_URL = "redis://127.0.0.1:6379/0"
MESSAGE_DEDUP_TTL_SECONDS = 600

REDIS_URL = os.getenv("REDIS_URL", DEFAULT_REDIS_URL)

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


def _message_key(message_id: str) -> str:
    return f"wechat:message:{message_id}"


def _user_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest()


def get_cached_reply(message_id: str, user_id: str) -> bytes | None:
    if not message_id:
        return None

    try:
        cached = _get_client().get(_message_key(message_id))
        if cached is None:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8")

        payload = json.loads(cached)
        if not isinstance(payload, dict):
            raise ValueError("invalid cached reply")

        cached_user_hash = payload.get("user_hash")
        response_xml = payload.get("response_xml")
        if not isinstance(cached_user_hash, str) or not isinstance(
            response_xml, str
        ):
            raise ValueError("invalid cached reply")
        if not hmac.compare_digest(cached_user_hash, _user_hash(user_id)):
            return None

        return response_xml.encode("utf-8")
    except Exception as exc:
        logger.warning(
            "Redis message dedup read failed: %s", type(exc).__name__
        )
        return None


def cache_reply(
    message_id: str,
    user_id: str,
    response_body: bytes,
) -> None:
    if not message_id:
        return

    try:
        payload = json.dumps(
            {
                "user_hash": _user_hash(user_id),
                "response_xml": response_body.decode("utf-8"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        _get_client().set(
            _message_key(message_id),
            payload,
            ex=MESSAGE_DEDUP_TTL_SECONDS,
        )
    except Exception as exc:
        logger.warning(
            "Redis message dedup write failed: %s", type(exc).__name__
        )
