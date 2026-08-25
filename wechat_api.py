import os
import time

import httpx
from dotenv import load_dotenv


load_dotenv()

ACCESS_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
TEMPORARY_MEDIA_URL = "https://api.weixin.qq.com/cgi-bin/media/get"
WECHAT_API_TIMEOUT_SECONDS = 2.0
MAX_VOICE_BYTES = 10 * 1024 * 1024

_access_token: str | None = None
_access_token_expires_at = 0.0


class WeChatAPIError(RuntimeError):
    """微信公众号接口调用失败。"""


async def get_access_token() -> str:
    global _access_token, _access_token_expires_at

    if _access_token and time.monotonic() < _access_token_expires_at:
        return _access_token

    load_dotenv()
    app_id = os.getenv("WECHAT_APP_ID")
    app_secret = os.getenv("WECHAT_APP_SECRET")
    if not app_id or not app_secret:
        raise WeChatAPIError("missing WeChat AppID or AppSecret")

    transport = httpx.AsyncHTTPTransport(retries=0)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(WECHAT_API_TIMEOUT_SECONDS),
            transport=transport,
        ) as client:
            response = await client.get(
                ACCESS_TOKEN_URL,
                params={
                    "grant_type": "client_credential",
                    "appid": app_id,
                    "secret": app_secret,
                },
            )
            response.raise_for_status()
            data = response.json()
    except Exception as exc:
        raise WeChatAPIError("access token request failed") from exc

    access_token = data.get("access_token") if isinstance(data, dict) else None
    if not access_token:
        raise WeChatAPIError("access token response was invalid")

    try:
        expires_in = int(data.get("expires_in", 7200))
    except (TypeError, ValueError):
        expires_in = 7200
    refresh_after = max(min(expires_in - 300, expires_in), 1)
    _access_token = access_token
    _access_token_expires_at = time.monotonic() + refresh_after
    return access_token


async def download_voice_media(media_id: str) -> bytes:
    if not media_id:
        raise WeChatAPIError("missing media ID")

    access_token = await get_access_token()
    transport = httpx.AsyncHTTPTransport(retries=0)
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(WECHAT_API_TIMEOUT_SECONDS),
            transport=transport,
        ) as client:
            async with client.stream(
                "GET",
                TEMPORARY_MEDIA_URL,
                params={"access_token": access_token, "media_id": media_id},
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                content_type = content_type.split(";", 1)[0].strip().lower()
                if content_type == "application/json":
                    await response.aread()
                    raise WeChatAPIError("media download response was an error")

                content_length = response.headers.get("content-length")
                if content_length:
                    try:
                        if int(content_length) > MAX_VOICE_BYTES:
                            raise WeChatAPIError("voice file is too large")
                    except ValueError:
                        pass

                audio_data = bytearray()
                async for chunk in response.aiter_bytes():
                    audio_data.extend(chunk)
                    if len(audio_data) > MAX_VOICE_BYTES:
                        raise WeChatAPIError("voice file is too large")
    except WeChatAPIError:
        raise
    except Exception as exc:
        raise WeChatAPIError("media download failed") from exc

    if not audio_data or bytes(audio_data).lstrip().startswith(b"{"):
        raise WeChatAPIError("media download response was invalid")

    return bytes(audio_data)
