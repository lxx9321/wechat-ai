from typing import Protocol, runtime_checkable


IMAGE_ANALYSIS_PROMPT = (
    "请分析这张图片，用简洁的中文说明图片中的主要内容。"
    "如果图片中有明显文字，也请概括重要文字信息。"
)


class AIError(RuntimeError):
    """AI配置或Provider调用失败。"""


class AIConfigurationError(AIError):
    """AI Provider配置无效或缺少必要配置。"""


class AIProviderError(AIError):
    """AI Provider请求失败或返回无效结果。"""


@runtime_checkable
class TextProvider(Protocol):
    def ask(
        self,
        message: str,
        history: list[dict] | None = None,
    ) -> str: ...


@runtime_checkable
class VisionProvider(Protocol):
    def analyze_image(self, image_bytes: bytes, mime_type: str) -> str: ...


@runtime_checkable
class TranscriptionProvider(Protocol):
    def transcribe_audio(self, audio_bytes: bytes, filename: str) -> str: ...

