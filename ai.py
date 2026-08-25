import os

from dotenv import load_dotenv
from openai import OpenAI


MODEL_NAME = "gpt-5-nano"


class AIError(RuntimeError):
    """OpenAI 配置或 API 调用失败。"""


def ask_ai(message: str) -> str:
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        raise AIError("缺少 OPENAI_API_KEY，请先在 .env 中配置。")

    client = OpenAI(api_key=api_key)

    try:
        response = client.responses.create(
            model=MODEL_NAME,
            input=message,
        )
    except Exception as exc:
        safe_message = str(exc).replace(api_key, "[REDACTED]")
        raise AIError(f"OpenAI API 调用失败：{safe_message}") from exc
    finally:
        client.close()

    if not response.output_text:
        raise AIError("OpenAI API 调用成功，但没有返回文本内容。")

    return response.output_text
