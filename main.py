import hashlib
import hmac
import logging
import os
import time
from xml.etree import ElementTree

import httpx
from access_control import is_user_allowed, is_within_rate_limit
from ai import analyze_image, ask_ai, transcribe_audio
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from memory import clear_history, get_history, save_turn
from wechat_api import download_voice_media


load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()
WECHAT_TOKEN = os.environ["WECHAT_TOKEN"]
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 2.0
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class ImageDownloadError(RuntimeError):
    """微信图片下载或校验失败。"""


async def download_wechat_image(pic_url: str) -> tuple[bytes, str]:
    if not pic_url:
        raise ImageDownloadError("missing image URL")

    timeout = httpx.Timeout(IMAGE_DOWNLOAD_TIMEOUT_SECONDS)
    transport = httpx.AsyncHTTPTransport(retries=0)
    async with httpx.AsyncClient(
        timeout=timeout,
        transport=transport,
        follow_redirects=True,
    ) as client:
        async with client.stream("GET", pic_url) as response:
            response.raise_for_status()
            mime_type = response.headers.get("content-type", "").split(";", 1)[0]
            mime_type = mime_type.strip().lower()
            if not mime_type.startswith("image/"):
                raise ImageDownloadError("invalid image content type")

            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > MAX_IMAGE_BYTES:
                        raise ImageDownloadError("image is too large")
                except ValueError:
                    pass

            image_data = bytearray()
            async for chunk in response.aiter_bytes():
                image_data.extend(chunk)
                if len(image_data) > MAX_IMAGE_BYTES:
                    raise ImageDownloadError("image is too large")

    if not image_data:
        raise ImageDownloadError("empty image")

    return bytes(image_data), mime_type


def verify_signature(signature: str, timestamp: str, nonce: str) -> bool:
    values = [WECHAT_TOKEN, timestamp, nonce]
    values.sort()
    digest = hashlib.sha1("".join(values).encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, signature)


@app.get("/")
def read_root():
    return {"status": "ok"}


@app.get("/wechat", response_class=PlainTextResponse)
def verify_wechat(
    signature: str,
    timestamp: str,
    nonce: str,
    echostr: str,
):
    if not verify_signature(signature, timestamp, nonce):
        return PlainTextResponse("invalid signature", status_code=403)

    return PlainTextResponse(echostr)


@app.post("/wechat")
async def handle_wechat_message(
    request: Request,
    signature: str,
    timestamp: str,
    nonce: str,
):
    if not verify_signature(signature, timestamp, nonce):
        return PlainTextResponse("invalid signature", status_code=403)

    request_body = await request.body()

    try:
        root = ElementTree.fromstring(request_body)
    except ElementTree.ParseError:
        return PlainTextResponse("invalid xml", status_code=400)

    fields = {
        name: root.findtext(name, default="")
        for name in (
            "ToUserName",
            "FromUserName",
            "CreateTime",
            "MsgType",
            "Content",
            "PicUrl",
            "MediaId",
            "Format",
            "Recognition",
            "MsgId",
        )
    }

    message_type = fields["MsgType"]
    user_id = fields["FromUserName"] or ""
    if (
        message_type in {"text", "image", "voice"}
        and not is_user_allowed(user_id)
    ):
        reply_content = "当前账号暂未开放AI功能。"
    elif message_type == "text":
        user_message = (fields["Content"] or "").strip()
        if user_message == "清空记忆":
            clear_history(user_id)
            reply_content = "聊天记忆已清空。"
        elif not user_message:
            reply_content = "请输入内容后再发送。"
        elif not is_within_rate_limit(user_id):
            reply_content = "消息发送太频繁，请稍后再试。"
        else:
            history = get_history(user_id)
            try:
                reply_content = ask_ai(user_message, history)
            except Exception as exc:
                logger.warning("AI reply failed: %s", type(exc).__name__)
                reply_content = "AI 暂时无法回复，请稍后再试。"
            else:
                save_turn(user_id, user_message, reply_content)
    elif message_type == "image":
        try:
            image_bytes, mime_type = await download_wechat_image(fields["PicUrl"])
        except Exception as exc:
            logger.warning("Image download failed: %s", type(exc).__name__)
            reply_content = "图片获取失败，请稍后再试。"
        else:
            if not is_within_rate_limit(user_id):
                reply_content = "消息发送太频繁，请稍后再试。"
            else:
                try:
                    reply_content = analyze_image(image_bytes, mime_type)
                except Exception as exc:
                    logger.warning("Image analysis failed: %s", type(exc).__name__)
                    reply_content = "AI 暂时无法分析这张图片，请稍后再试。"
                else:
                    save_turn(user_id, "[用户发送了一张图片]", reply_content)
    elif message_type == "voice":
        voice_text = (fields["Recognition"] or "").strip()
        if not voice_text:
            try:
                audio_bytes = await download_voice_media(fields["MediaId"])
            except Exception as exc:
                logger.warning("Voice download failed: %s", type(exc).__name__)
                reply_content = "语音获取失败，请稍后再试。"
            else:
                audio_format = (fields["Format"] or "").strip().lower()
                safe_formats = {
                    "flac",
                    "m4a",
                    "mp3",
                    "mp4",
                    "mpeg",
                    "mpga",
                    "ogg",
                    "wav",
                    "webm",
                    "amr",
                    "speex",
                }
                if audio_format not in safe_formats:
                    audio_format = "bin"
                if not is_within_rate_limit(user_id):
                    reply_content = "消息发送太频繁，请稍后再试。"
                else:
                    try:
                        voice_text = transcribe_audio(
                            audio_bytes, f"voice.{audio_format}"
                        )
                    except Exception as exc:
                        logger.warning(
                            "Voice transcription failed: %s", type(exc).__name__
                        )
                        reply_content = "暂时无法识别这段语音，请稍后再试。"

        if voice_text:
            if not is_within_rate_limit(user_id):
                reply_content = "消息发送太频繁，请稍后再试。"
            else:
                history = get_history(user_id)
                try:
                    reply_content = ask_ai(voice_text, history)
                except Exception as exc:
                    logger.warning("AI reply failed: %s", type(exc).__name__)
                    reply_content = "AI 暂时无法回复，请稍后再试。"
                else:
                    save_turn(user_id, voice_text, reply_content)
    else:
        return PlainTextResponse("success")

    reply = ElementTree.Element("xml")
    reply_fields = {
        "ToUserName": fields["FromUserName"],
        "FromUserName": fields["ToUserName"],
        "CreateTime": str(int(time.time())),
        "MsgType": "text",
        "Content": reply_content,
    }

    for name, value in reply_fields.items():
        ElementTree.SubElement(reply, name).text = value

    response_body = ElementTree.tostring(reply, encoding="utf-8")
    return Response(content=response_body, media_type="application/xml")
