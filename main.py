import hashlib
import hmac
import logging
import os
import time
from xml.etree import ElementTree

from ai import ask_ai
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse, Response
from memory import clear_history, get_history, save_turn


load_dotenv()

logger = logging.getLogger(__name__)
app = FastAPI()
WECHAT_TOKEN = os.environ["WECHAT_TOKEN"]


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
            "MsgId",
        )
    }

    if fields["MsgType"] != "text":
        return PlainTextResponse("success")

    user_message = (fields["Content"] or "").strip()
    user_id = fields["FromUserName"] or ""
    if user_message == "清空记忆":
        clear_history(user_id)
        reply_content = "聊天记忆已清空。"
    elif not user_message:
        reply_content = "请输入内容后再发送。"
    else:
        history = get_history(user_id)
        try:
            reply_content = ask_ai(user_message, history)
        except Exception as exc:
            logger.warning("AI reply failed: %s", type(exc).__name__)
            reply_content = "AI 暂时无法回复，请稍后再试。"
        else:
            save_turn(user_id, user_message, reply_content)

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
