import base64
import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()
MODEL_NAME = os.getenv("OPENAI_MODEL", "gpt-5-nano")


class AIError(RuntimeError):
    """OpenAI 配置或 API 调用失败。"""


def ask_ai(message: str, history: list[dict] | None = None) -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise AIError("缺少 OPENAI_API_KEY，请先在 .env 中配置。")

    client = OpenAI(api_key=api_key, timeout=5.0, max_retries=0)
    request_input = message
    if history:
        request_input = [*history, {"role": "user", "content": message}]

    try:
        response = client.responses.create(
            model=MODEL_NAME,
            input=request_input,
            reasoning={"effort": "minimal"},
        )
    except Exception as exc:
        safe_message = str(exc).replace(api_key, "[REDACTED]")
        raise AIError(f"OpenAI API 调用失败：{safe_message}") from exc
    finally:
        client.close()

    if not response.output_text:
        raise AIError("OpenAI API 调用成功，但没有返回文本内容。")

    return response.output_text


def analyze_image(image_bytes: bytes, mime_type: str) -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise AIError("缺少 OPENAI_API_KEY，请先在 .env 中配置。")

    image_base64 = base64.b64encode(image_bytes).decode("ascii")
    image_data_url = f"data:{mime_type};base64,{image_base64}"
    client = OpenAI(api_key=api_key, timeout=5.0, max_retries=0)

    try:
        response = client.responses.create(
            model=MODEL_NAME,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "请分析这张图片，用简洁的中文说明图片中的主要内容。"
                                "如果图片中有明显文字，也请概括重要文字信息。"
                            ),
                        },
                        {
                            "type": "input_image",
                            "image_url": image_data_url,
                        },
                    ],
                }
            ],
            reasoning={"effort": "minimal"},
        )
    except Exception as exc:
        safe_message = str(exc).replace(api_key, "[REDACTED]")
        raise AIError(f"OpenAI 图片分析失败：{safe_message}") from exc
    finally:
        client.close()

    if not response.output_text:
        raise AIError("OpenAI 图片分析成功，但没有返回文本内容。")

    return response.output_text
