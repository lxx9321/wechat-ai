import base64

from openai import OpenAI

from .base import (
    AIConfigurationError,
    AIProviderError,
    IMAGE_ANALYSIS_PROMPT,
)


class OpenAIProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5-nano",
        transcribe_model: str = "gpt-4o-mini-transcribe",
        timeout: float = 5.0,
    ) -> None:
        api_key = api_key.strip()
        if not api_key:
            raise AIConfigurationError(
                "缺少 OPENAI_API_KEY，请先在 .env 中配置。"
            )
        if not model.strip():
            raise AIConfigurationError("OPENAI_MODEL 不能为空。")
        if not transcribe_model.strip():
            raise AIConfigurationError("OPENAI_TRANSCRIBE_MODEL 不能为空。")

        self.model = model.strip()
        self.transcribe_model = transcribe_model.strip()
        self._client = OpenAI(
            api_key=api_key,
            timeout=timeout,
            max_retries=0,
        )

    @staticmethod
    def _request_error(action: str, exc: Exception) -> AIProviderError:
        return AIProviderError(
            f"OpenAI {action}失败：{type(exc).__name__}"
        )

    def ask(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> str:
        request_input: str | list[dict] = message
        if history:
            request_input = [*history, {"role": "user", "content": message}]

        try:
            response = self._client.responses.create(
                model=self.model,
                input=request_input,
                reasoning={"effort": "minimal"},
            )
        except Exception as exc:
            raise self._request_error("API 调用", exc) from exc

        if not response.output_text:
            raise AIProviderError(
                "OpenAI API 调用成功，但没有返回文本内容。"
            )
        return response.output_text

    def analyze_image(self, image_bytes: bytes, mime_type: str) -> str:
        image_base64 = base64.b64encode(image_bytes).decode("ascii")
        image_data_url = f"data:{mime_type};base64,{image_base64}"
        try:
            response = self._client.responses.create(
                model=self.model,
                input=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": IMAGE_ANALYSIS_PROMPT,
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
            raise self._request_error("图片分析", exc) from exc

        if not response.output_text:
            raise AIProviderError(
                "OpenAI 图片分析成功，但没有返回文本内容。"
            )
        return response.output_text

    def transcribe_audio(self, audio_bytes: bytes, filename: str) -> str:
        try:
            transcription = self._client.audio.transcriptions.create(
                model=self.transcribe_model,
                file=(filename, audio_bytes),
            )
        except Exception as exc:
            raise self._request_error("语音识别", exc) from exc

        transcript_text = (
            transcription
            if isinstance(transcription, str)
            else getattr(transcription, "text", "")
        )
        transcript_text = transcript_text.strip()
        if not transcript_text:
            raise AIProviderError(
                "OpenAI 语音识别成功，但没有返回文字内容。"
            )
        return transcript_text

    def close(self) -> None:
        self._client.close()

