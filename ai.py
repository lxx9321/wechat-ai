import os
from threading import Lock
from typing import Callable, TypeVar, cast

from dotenv import load_dotenv

from ai_providers import (
    AIConfigurationError,
    AIError,
    AIProviderError,
    DeepSeekProvider,
    OpenAIProvider,
    QwenVisionProvider,
    TextProvider,
    TranscriptionProvider,
    VisionProvider,
)
from ai_providers.deepseek_provider import DEFAULT_DEEPSEEK_BASE_URL
from ai_providers.qwen_provider import DEFAULT_QWEN_BASE_URL


load_dotenv()

DEFAULT_OPENAI_MODEL = "gpt-5-nano"
DEFAULT_OPENAI_TRANSCRIBE_MODEL = "gpt-4o-mini-transcribe"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"
DEFAULT_QWEN_VISION_MODEL = "qwen3-vl-flash"
DEFAULT_PROVIDER = "openai"
PROVIDER_TIMEOUT_SECONDS = 5.0

_ProviderT = TypeVar("_ProviderT")
_provider_cache: dict[str, tuple[tuple[str, ...], object]] = {}
_provider_cache_lock = Lock()


def _env(name: str, default: str = "") -> str:
    load_dotenv()
    return os.getenv(name, default).strip()


def _selected_provider(
    env_name: str,
    allowed: frozenset[str],
) -> str:
    provider_name = _env(env_name, DEFAULT_PROVIDER).lower() or DEFAULT_PROVIDER
    if provider_name not in allowed:
        allowed_names = ", ".join(sorted(allowed))
        raise AIConfigurationError(
            f"不支持的 {env_name}={provider_name!r}；可选值：{allowed_names}。"
        )
    return provider_name


def _get_cached_provider(
    cache_key: str,
    fingerprint: tuple[str, ...],
    factory: Callable[[], _ProviderT],
) -> _ProviderT:
    with _provider_cache_lock:
        cached = _provider_cache.get(cache_key)
        if cached and cached[0] == fingerprint:
            return cast(_ProviderT, cached[1])

        if cached:
            _provider_cache.pop(cache_key, None)
            close = getattr(cached[1], "close", None)
            if callable(close):
                close()

        provider = factory()
        _provider_cache[cache_key] = (fingerprint, provider)
        return provider


def _get_openai_provider() -> OpenAIProvider:
    api_key = _env("OPENAI_API_KEY")
    model = _env("OPENAI_MODEL", DEFAULT_OPENAI_MODEL)
    transcribe_model = _env(
        "OPENAI_TRANSCRIBE_MODEL",
        DEFAULT_OPENAI_TRANSCRIBE_MODEL,
    )
    fingerprint = (api_key, model, transcribe_model)
    return _get_cached_provider(
        "openai",
        fingerprint,
        lambda: OpenAIProvider(
            api_key=api_key,
            model=model,
            transcribe_model=transcribe_model,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        ),
    )


def _get_deepseek_provider() -> DeepSeekProvider:
    api_key = _env("DEEPSEEK_API_KEY")
    model = _env("DEEPSEEK_MODEL", DEFAULT_DEEPSEEK_MODEL)
    base_url = _env("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL)
    fingerprint = (api_key, model, base_url)
    return _get_cached_provider(
        "deepseek",
        fingerprint,
        lambda: DeepSeekProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        ),
    )


def _get_qwen_provider() -> QwenVisionProvider:
    api_key = _env("QWEN_API_KEY")
    model = _env("QWEN_VISION_MODEL", DEFAULT_QWEN_VISION_MODEL)
    base_url = _env("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL)
    fingerprint = (api_key, model, base_url)
    return _get_cached_provider(
        "qwen",
        fingerprint,
        lambda: QwenVisionProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout=PROVIDER_TIMEOUT_SECONDS,
        ),
    )


def get_text_provider() -> TextProvider:
    provider_name = _selected_provider(
        "AI_TEXT_PROVIDER",
        frozenset({"openai", "deepseek"}),
    )
    if provider_name == "deepseek":
        return _get_deepseek_provider()
    return _get_openai_provider()


def get_vision_provider() -> VisionProvider:
    provider_name = _selected_provider(
        "AI_VISION_PROVIDER",
        frozenset({"openai", "qwen"}),
    )
    if provider_name == "qwen":
        return _get_qwen_provider()
    return _get_openai_provider()


def get_transcription_provider() -> TranscriptionProvider:
    _selected_provider(
        "AI_TRANSCRIBE_PROVIDER",
        frozenset({"openai"}),
    )
    return _get_openai_provider()


def clear_provider_cache() -> None:
    with _provider_cache_lock:
        providers = [entry[1] for entry in _provider_cache.values()]
        _provider_cache.clear()

    for provider in providers:
        close = getattr(provider, "close", None)
        if callable(close):
            close()


def ask_ai(message: str, history: list[dict] | None = None) -> str:
    return get_text_provider().ask(message, history)


def analyze_image(image_bytes: bytes, mime_type: str) -> str:
    return get_vision_provider().analyze_image(image_bytes, mime_type)


def transcribe_audio(audio_bytes: bytes, filename: str) -> str:
    return get_transcription_provider().transcribe_audio(audio_bytes, filename)


__all__ = [
    "AIConfigurationError",
    "AIError",
    "AIProviderError",
    "analyze_image",
    "ask_ai",
    "clear_provider_cache",
    "get_text_provider",
    "get_transcription_provider",
    "get_vision_provider",
    "transcribe_audio",
]
