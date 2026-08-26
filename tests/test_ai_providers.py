import base64
import os
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

import ai
from ai_providers import (
    AIConfigurationError,
    AIProviderError,
    DeepSeekProvider,
    OpenAIProvider,
    QwenVisionProvider,
    TranscriptionProvider,
    VisionProvider,
)
from ai_providers.base import IMAGE_ANALYSIS_PROMPT
from ai_providers.deepseek_provider import DEFAULT_DEEPSEEK_BASE_URL
from ai_providers.qwen_provider import DEFAULT_QWEN_BASE_URL


def chat_response(content):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
            )
        ]
    )


class OpenAIProviderTests(unittest.TestCase):
    def _provider(self, client):
        openai_patch = patch(
            "ai_providers.openai_provider.OpenAI",
            return_value=client,
        )
        constructor = openai_patch.start()
        self.addCleanup(openai_patch.stop)
        provider = OpenAIProvider(
            api_key="openai-test-key",
            model="gpt-5-nano",
            transcribe_model="gpt-4o-mini-transcribe",
        )
        constructor.assert_called_once_with(
            api_key="openai-test-key",
            timeout=5.0,
            max_retries=0,
        )
        return provider

    def test_text_without_and_with_history_preserves_responses_input(self):
        client = Mock()
        client.responses.create.side_effect = [
            SimpleNamespace(output_text="first reply"),
            SimpleNamespace(output_text="second reply"),
        ]
        provider = self._provider(client)
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "first reply"},
        ]

        self.assertEqual(provider.ask("hello"), "first reply")
        self.assertEqual(provider.ask("follow up", history), "second reply")
        self.assertEqual(
            client.responses.create.call_args_list,
            [
                call(
                    model="gpt-5-nano",
                    input="hello",
                    reasoning={"effort": "minimal"},
                ),
                call(
                    model="gpt-5-nano",
                    input=[
                        *history,
                        {"role": "user", "content": "follow up"},
                    ],
                    reasoning={"effort": "minimal"},
                ),
            ],
        )

    def test_image_uses_existing_prompt_and_temporary_data_url(self):
        client = Mock()
        client.responses.create.return_value = SimpleNamespace(
            output_text="image reply"
        )
        provider = self._provider(client)
        image_bytes = b"jpeg-bytes"

        self.assertEqual(
            provider.analyze_image(image_bytes, "image/jpeg"),
            "image reply",
        )
        request = client.responses.create.call_args.kwargs
        content = request["input"][0]["content"]
        self.assertEqual(request["model"], "gpt-5-nano")
        self.assertEqual(request["reasoning"], {"effort": "minimal"})
        self.assertEqual(content[0]["text"], IMAGE_ANALYSIS_PROMPT)
        self.assertEqual(
            content[1]["image_url"],
            "data:image/jpeg;base64,"
            + base64.b64encode(image_bytes).decode("ascii"),
        )

    def test_transcription_preserves_model_file_and_strips_result(self):
        client = Mock()
        client.audio.transcriptions.create.return_value = SimpleNamespace(
            text="  voice text  "
        )
        provider = self._provider(client)

        self.assertEqual(
            provider.transcribe_audio(b"wav-bytes", "voice.wav"),
            "voice text",
        )
        client.audio.transcriptions.create.assert_called_once_with(
            model="gpt-4o-mini-transcribe",
            file=("voice.wav", b"wav-bytes"),
        )

    def test_missing_key_and_api_error_are_safe(self):
        with self.assertRaises(AIConfigurationError) as missing:
            OpenAIProvider(api_key="")
        self.assertIn("OPENAI_API_KEY", str(missing.exception))

        client = Mock()
        client.responses.create.side_effect = RuntimeError(
            "openai-test-key private-message"
        )
        provider = self._provider(client)
        with self.assertRaises(AIProviderError) as failed:
            provider.ask("never-log-user-message")
        error_text = str(failed.exception)
        self.assertNotIn("openai-test-key", error_text)
        self.assertNotIn("private-message", error_text)
        self.assertNotIn("never-log-user-message", error_text)


class DeepSeekProviderTests(unittest.TestCase):
    def _provider(self, client):
        deepseek_patch = patch(
            "ai_providers.deepseek_provider.OpenAI",
            return_value=client,
        )
        constructor = deepseek_patch.start()
        self.addCleanup(deepseek_patch.stop)
        provider = DeepSeekProvider(api_key="deepseek-test-key")
        constructor.assert_called_once_with(
            api_key="deepseek-test-key",
            base_url=DEFAULT_DEEPSEEK_BASE_URL,
            timeout=5.0,
            max_retries=0,
        )
        return provider

    def test_text_history_returns_plain_string(self):
        client = Mock()
        client.chat.completions.create.return_value = chat_response(
            "deepseek reply"
        )
        provider = self._provider(client)
        history = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "answer"},
        ]

        result = provider.ask("follow up", history)

        self.assertIsInstance(result, str)
        self.assertEqual(result, "deepseek reply")
        client.chat.completions.create.assert_called_once_with(
            model="deepseek-v4-flash",
            messages=[
                *history,
                {"role": "user", "content": "follow up"},
            ],
            stream=False,
            extra_body={"thinking": {"type": "disabled"}},
        )
        self.assertNotIsInstance(provider, VisionProvider)

    def test_missing_key_and_api_error_are_safe(self):
        with self.assertRaises(AIConfigurationError) as missing:
            DeepSeekProvider(api_key="")
        self.assertIn("DEEPSEEK_API_KEY", str(missing.exception))

        client = Mock()
        client.chat.completions.create.side_effect = RuntimeError(
            "deepseek-test-key private-message"
        )
        provider = self._provider(client)
        with self.assertRaises(AIProviderError) as failed:
            provider.ask("never-log-user-message")
        error_text = str(failed.exception)
        self.assertNotIn("deepseek-test-key", error_text)
        self.assertNotIn("private-message", error_text)
        self.assertNotIn("never-log-user-message", error_text)


class QwenVisionProviderTests(unittest.TestCase):
    def _provider(self, client):
        qwen_patch = patch(
            "ai_providers.qwen_provider.OpenAI",
            return_value=client,
        )
        constructor = qwen_patch.start()
        self.addCleanup(qwen_patch.stop)
        provider = QwenVisionProvider(api_key="qwen-test-key")
        constructor.assert_called_once_with(
            api_key="qwen-test-key",
            base_url=DEFAULT_QWEN_BASE_URL,
            timeout=5.0,
            max_retries=0,
        )
        return provider

    def test_jpeg_png_and_webp_return_plain_string(self):
        client = Mock()
        client.chat.completions.create.return_value = chat_response(
            "qwen image reply"
        )
        provider = self._provider(client)
        samples = (
            ("image/jpeg", b"jpeg"),
            ("image/png", b"png"),
            ("image/webp", b"webp"),
        )

        for mime_type, image_bytes in samples:
            with self.subTest(mime_type=mime_type):
                result = provider.analyze_image(image_bytes, mime_type)
                self.assertIsInstance(result, str)
                self.assertEqual(result, "qwen image reply")
                request = client.chat.completions.create.call_args.kwargs
                content = request["messages"][0]["content"]
                self.assertEqual(request["model"], "qwen3-vl-flash")
                self.assertFalse(request["stream"])
                self.assertEqual(content[0]["text"], IMAGE_ANALYSIS_PROMPT)
                self.assertEqual(
                    content[1]["image_url"]["url"],
                    f"data:{mime_type};base64,"
                    + base64.b64encode(image_bytes).decode("ascii"),
                )

        self.assertNotIsInstance(provider, TranscriptionProvider)

    def test_missing_key_unsupported_mime_and_api_error_are_safe(self):
        with self.assertRaises(AIConfigurationError) as missing:
            QwenVisionProvider(api_key="")
        self.assertIn("QWEN_API_KEY", str(missing.exception))

        client = Mock()
        provider = self._provider(client)
        with self.assertRaises(AIProviderError):
            provider.analyze_image(b"gif", "image/gif")
        client.chat.completions.create.assert_not_called()

        client.chat.completions.create.side_effect = RuntimeError(
            "qwen-test-key private-base64"
        )
        with self.assertRaises(AIProviderError) as failed:
            provider.analyze_image(b"never-log-image", "image/jpeg")
        error_text = str(failed.exception)
        self.assertNotIn("qwen-test-key", error_text)
        self.assertNotIn("private-base64", error_text)
        self.assertNotIn("never-log-image", error_text)


class ProviderSelectionTests(unittest.TestCase):
    def setUp(self):
        ai.clear_provider_cache()

    def tearDown(self):
        ai.clear_provider_cache()

    def test_text_provider_selection_openai_and_deepseek(self):
        openai_provider = Mock()
        openai_provider.ask.return_value = "openai reply"
        deepseek_provider = Mock()
        deepseek_provider.ask.return_value = "deepseek reply"

        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-openai-key",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                return_value=openai_provider,
            ) as openai_constructor,
        ):
            self.assertEqual(ai.ask_ai("hello"), "openai reply")
            self.assertEqual(ai.ask_ai("again"), "openai reply")
            openai_constructor.assert_called_once()

        ai.clear_provider_cache()
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "test-deepseek-key",
                },
            ),
            patch.object(
                ai,
                "DeepSeekProvider",
                return_value=deepseek_provider,
            ) as deepseek_constructor,
        ):
            self.assertEqual(ai.ask_ai("hello"), "deepseek reply")
            deepseek_constructor.assert_called_once()

    def test_empty_provider_configuration_defaults_all_capabilities_to_openai(self):
        provider = Mock()
        provider.ask.return_value = "text reply"
        provider.analyze_image.return_value = "image reply"
        provider.transcribe_audio.return_value = "voice text"
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "",
                    "AI_VISION_PROVIDER": "",
                    "AI_TRANSCRIBE_PROVIDER": "",
                    "OPENAI_API_KEY": "test-openai-key",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                return_value=provider,
            ) as constructor,
        ):
            self.assertEqual(ai.ask_ai("message"), "text reply")
            self.assertEqual(
                ai.analyze_image(b"image", "image/jpeg"),
                "image reply",
            )
            self.assertEqual(
                ai.transcribe_audio(b"wav", "voice.wav"),
                "voice text",
            )
            constructor.assert_called_once()

    def test_vision_provider_selection_openai_and_qwen(self):
        openai_provider = Mock()
        openai_provider.analyze_image.return_value = "openai image"
        qwen_provider = Mock()
        qwen_provider.analyze_image.return_value = "qwen image"

        with (
            patch.dict(
                os.environ,
                {
                    "AI_VISION_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-openai-key",
                },
            ),
            patch.object(ai, "OpenAIProvider", return_value=openai_provider),
        ):
            self.assertEqual(
                ai.analyze_image(b"image", "image/jpeg"),
                "openai image",
            )

        ai.clear_provider_cache()
        with (
            patch.dict(
                os.environ,
                {
                    "AI_VISION_PROVIDER": "qwen",
                    "QWEN_API_KEY": "test-qwen-key",
                },
            ),
            patch.object(ai, "QwenVisionProvider", return_value=qwen_provider),
        ):
            self.assertEqual(
                ai.analyze_image(b"image", "image/png"),
                "qwen image",
            )

    def test_transcription_provider_selection_is_openai_only(self):
        provider = Mock()
        provider.transcribe_audio.return_value = "voice text"
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TRANSCRIBE_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-openai-key",
                },
            ),
            patch.object(ai, "OpenAIProvider", return_value=provider),
        ):
            self.assertEqual(
                ai.transcribe_audio(b"wav", "voice.wav"),
                "voice text",
            )

    def test_invalid_provider_values_fail_clearly(self):
        cases = (
            ("AI_TEXT_PROVIDER", "abc", lambda: ai.ask_ai("message")),
            (
                "AI_VISION_PROVIDER",
                "abc",
                lambda: ai.analyze_image(b"image", "image/jpeg"),
            ),
            (
                "AI_TRANSCRIBE_PROVIDER",
                "abc",
                lambda: ai.transcribe_audio(b"wav", "voice.wav"),
            ),
        )
        for env_name, value, operation in cases:
            with self.subTest(env_name=env_name):
                with patch.dict(os.environ, {env_name: value}):
                    with self.assertRaises(AIConfigurationError) as failed:
                        operation()
                self.assertIn(env_name, str(failed.exception))
                self.assertIn("abc", str(failed.exception))

    def test_missing_deepseek_or_qwen_key_never_falls_back_to_openai(self):
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "deepseek",
                    "DEEPSEEK_API_KEY": "",
                },
            ),
            patch.object(ai, "OpenAIProvider") as openai_constructor,
        ):
            with self.assertRaises(AIConfigurationError):
                ai.ask_ai("message")
            openai_constructor.assert_not_called()

        ai.clear_provider_cache()
        with (
            patch.dict(
                os.environ,
                {
                    "AI_VISION_PROVIDER": "qwen",
                    "QWEN_API_KEY": "",
                },
            ),
            patch.object(ai, "OpenAIProvider") as openai_constructor,
        ):
            with self.assertRaises(AIConfigurationError):
                ai.analyze_image(b"image", "image/jpeg")
            openai_constructor.assert_not_called()

    def test_clear_cache_closes_provider_and_allows_reconfiguration(self):
        provider = Mock()
        provider.ask.return_value = "reply"
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "test-openai-key",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                return_value=provider,
            ) as constructor,
        ):
            ai.ask_ai("first")
            ai.ask_ai("second")
            constructor.assert_called_once()
            ai.clear_provider_cache()
            provider.close.assert_called_once()

    def test_failed_reconfiguration_does_not_leave_closed_provider_cached(self):
        first_provider = Mock()
        first_provider.ask.return_value = "first reply"
        replacement_provider = Mock()
        replacement_provider.ask.return_value = "replacement reply"
        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "first-key",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                return_value=first_provider,
            ),
        ):
            self.assertEqual(ai.ask_ai("first"), "first reply")

        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                side_effect=AIConfigurationError("missing key"),
            ),
        ):
            with self.assertRaises(AIConfigurationError):
                ai.ask_ai("fails")
        first_provider.close.assert_called_once()

        with (
            patch.dict(
                os.environ,
                {
                    "AI_TEXT_PROVIDER": "openai",
                    "OPENAI_API_KEY": "replacement-key",
                },
            ),
            patch.object(
                ai,
                "OpenAIProvider",
                return_value=replacement_provider,
            ) as replacement_constructor,
        ):
            self.assertEqual(
                ai.ask_ai("replacement"),
                "replacement reply",
            )
            replacement_constructor.assert_called_once()


if __name__ == "__main__":
    unittest.main()
