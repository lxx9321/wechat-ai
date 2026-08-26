from openai import OpenAI

from .base import AIConfigurationError, AIProviderError


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "deepseek-v4-flash",
        base_url: str = DEFAULT_DEEPSEEK_BASE_URL,
        timeout: float = 5.0,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise AIConfigurationError(
                "缺少 DEEPSEEK_API_KEY，请先配置后再启用 DeepSeek。"
            )
        if not model.strip():
            raise AIConfigurationError("DEEPSEEK_MODEL 不能为空。")
        if not base_url.strip():
            raise AIConfigurationError("DEEPSEEK_BASE_URL 不能为空。")

        self.model = model.strip()
        self._client = OpenAI(
            api_key=api_key,
            base_url=base_url.strip(),
            timeout=timeout,
            max_retries=0,
        )

    def ask(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> str:
        messages = [*(history or []), {"role": "user", "content": message}]
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=messages,
                stream=False,
                extra_body={"thinking": {"type": "disabled"}},
            )
            content = response.choices[0].message.content
        except Exception as exc:
            raise AIProviderError(
                f"DeepSeek API 调用失败：{type(exc).__name__}"
            ) from exc

        if not isinstance(content, str) or not content:
            raise AIProviderError(
                "DeepSeek API 调用成功，但没有返回文本内容。"
            )
        return content

    def close(self) -> None:
        self._client.close()

