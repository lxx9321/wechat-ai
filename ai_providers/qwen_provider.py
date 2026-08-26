import base64

from openai import OpenAI

from .base import (
    AIConfigurationError,
    AIProviderError,
    IMAGE_ANALYSIS_PROMPT,
)


DEFAULT_QWEN_BASE_URL = (
    "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
SUPPORTED_IMAGE_MIME_TYPES = frozenset(
    {"image/jpeg", "image/png", "image/webp"}
)


class QwenVisionProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "qwen3-vl-flash",
        base_url: str = DEFAULT_QWEN_BASE_URL,
        timeout: float = 5.0,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise AIConfigurationError(
                "缺少 QWEN_API_KEY，请先配置后再启用 Qwen。"
            )
        if not model.strip():
            raise AIConfigurationError("QWEN_VISION_MODEL 不能为空。")
        if not base_url.strip():
            raise AIConfigurationError("QWEN_BASE_URL 不能为空。")

        self.model = model.strip()
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url.strip(),
            timeout=timeout,
            max_retries=0,
        )

    def analyze_image(self, image_bytes: bytes, mime_type: str) -> str:
        if mime_type not in SUPPORTED_IMAGE_MIME_TYPES:
            raise AIProviderError(
                f"Qwen 不支持的图片类型：{mime_type or 'missing'}"
            )

        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_data_url = f"data:{mime_type};base64,{image_base64}"
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {"url": image_data_url},
                            },
                        ],
                    }
                ],
                stream=False,
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise AIProviderError(
                f"Qwen 图片分析失败：{type(exc).__name__}"
            ) from exc

        if not isinstance(content, str) or not content:
            raise AIProviderError(
                "Qwen 图片分析成功，但没有返回文本内容。"
            )
        return content

    def close(self) -> None:
        self._client.close()

