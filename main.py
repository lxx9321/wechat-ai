import hashlib
import hmac
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse


load_dotenv()

app = FastAPI()
WECHAT_TOKEN = os.environ["WECHAT_TOKEN"]


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
    values = [WECHAT_TOKEN, timestamp, nonce]
    values.sort()
    digest = hashlib.sha1("".join(values).encode("utf-8")).hexdigest()

    if not hmac.compare_digest(digest, signature):
        return PlainTextResponse("invalid signature", status_code=403)

    return PlainTextResponse(echostr)
