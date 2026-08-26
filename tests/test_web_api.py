import hashlib
import io
import json
import logging
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient

os.environ.setdefault("WECHAT_TOKEN", "test-wechat-token")

import access_control
import main
import memory
import web_api
import web_auth


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.lists = {}
        self.ttls = {}
        self.rate_counts = {}
        self.last_lrange_key = None
        self.last_eval_keys = None

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        deleted = self.values.pop(key, None) is not None
        deleted = self.lists.pop(key, None) is not None or deleted
        self.ttls.pop(key, None)
        return int(deleted)

    def lrange(self, key, start, end):
        self.last_lrange_key = key
        items = self.lists.get(key, [])
        stop = len(items) if end == -1 else end + 1
        return list(items[start:stop])

    def pipeline(self, transaction=True):
        return FakePipeline(self)

    def eval(self, script, number_of_keys, key_10s, key_60s):
        self.last_eval_keys = (key_10s, key_60s)
        self.rate_counts[key_10s] = self.rate_counts.get(key_10s, 0) + 1
        self.rate_counts[key_60s] = self.rate_counts.get(key_60s, 0) + 1
        return [self.rate_counts[key_10s], self.rate_counts[key_60s]]


class FakePipeline:
    def __init__(self, client):
        self.client = client
        self.operations = []

    def rpush(self, key, *items):
        self.operations.append(("rpush", key, items))
        return self

    def ltrim(self, key, start, end):
        self.operations.append(("ltrim", key, start, end))
        return self

    def expire(self, key, seconds):
        self.operations.append(("expire", key, seconds))
        return self

    def execute(self):
        results = []
        for operation in self.operations:
            name, key, *args = operation
            if name == "rpush":
                items = args[0]
                self.client.lists.setdefault(key, []).extend(items)
                results.append(len(self.client.lists[key]))
            elif name == "ltrim":
                start, end = args
                items = self.client.lists.get(key, [])
                start = max(len(items) + start, 0) if start < 0 else start
                end = len(items) + end if end < 0 else end
                self.client.lists[key] = items[start : end + 1]
                results.append(True)
            elif name == "expire":
                self.client.ttls[key] = args[0]
                results.append(True)
        return results


class FailingSessionRedis:
    def get(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class FailingHistoryRedis:
    def lrange(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class WebAPITestCase(unittest.TestCase):
    def setUp(self):
        self.original_auth_client = web_auth._redis_client
        self.original_memory_client = memory._redis_client
        self.original_rate_client = access_control._redis_client
        self.redis = FakeRedis()
        web_auth._redis_client = self.redis
        memory._redis_client = self.redis
        access_control._redis_client = self.redis
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        web_auth._redis_client = self.original_auth_client
        memory._redis_client = self.original_memory_client
        access_control._redis_client = self.original_rate_client

    def authenticate(self):
        token, _ = web_auth.create_session()
        user_id = web_auth.get_user_for_token(token)
        self.client.cookies.set(web_auth.WEB_COOKIE_NAME, token)
        return token, user_id


class WebHistoryTests(WebAPITestCase):
    def test_history_requires_cookie_and_session_store_failures_are_503(self):
        self.assertEqual(
            self.client.get("/api/web/v1/history").status_code,
            401,
        )

        self.authenticate()
        web_auth._redis_client = FailingSessionRedis()
        self.assertEqual(
            self.client.get("/api/web/v1/history").status_code,
            503,
        )

    def test_empty_and_ordered_history_are_isolated_by_user_and_channel(self):
        _, user_id = self.authenticate()
        self.assertEqual(
            self.client.get("/api/web/v1/history").json(),
            {"messages": []},
        )

        memory.save_turn(user_id, "web question", "web answer", channel="web")
        memory.save_turn(user_id, "wechat question", "wechat answer")
        memory.save_turn("other-user", "other question", "other answer", channel="web")

        response = self.client.get("/api/web/v1/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "messages": [
                    {"role": "user", "content": "web question"},
                    {"role": "assistant", "content": "web answer"},
                ]
            },
        )
        self.assertEqual(self.redis.last_lrange_key, f"web:history:{user_id}")

    def test_history_redis_failure_degrades_to_empty(self):
        self.authenticate()
        memory._redis_client = FailingHistoryRedis()
        response = self.client.get("/api/web/v1/history")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"messages": []})


class WebChatTests(WebAPITestCase):
    def test_chat_requires_cookie_and_validates_message(self):
        self.assertEqual(
            self.client.post(
                "/api/web/v1/chat",
                json={"message": "hello"},
            ).status_code,
            401,
        )
        self.authenticate()

        for payload in (
            {"message": ""},
            {"message": "   "},
            {"message": "x" * 2001},
            {"message": 123},
            {},
        ):
            with self.subTest(payload_type=type(payload.get("message"))):
                response = self.client.post("/api/web/v1/chat", json=payload)
                self.assertEqual(response.status_code, 422)

    def test_chat_passes_history_saves_web_turn_and_trims_input(self):
        _, user_id = self.authenticate()
        expected_history = [{"role": "user", "content": "earlier"}]
        with (
            patch.object(web_api, "is_within_rate_limit", return_value=True) as rate,
            patch.object(web_api, "get_history", return_value=expected_history) as get,
            patch.object(web_api, "ask_ai", return_value="reply") as ask,
            patch.object(web_api, "save_turn") as save,
        ):
            response = self.client.post(
                "/api/web/v1/chat",
                json={"message": "  Hello Web  "},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "reply"})
        rate.assert_called_once_with(user_id, channel="web")
        get.assert_called_once_with(user_id, channel="web")
        ask.assert_called_once_with("Hello Web", expected_history)
        save.assert_called_once_with(
            user_id,
            "Hello Web",
            "reply",
            channel="web",
        )

    def test_second_chat_receives_first_web_turn(self):
        _, user_id = self.authenticate()
        received_histories = []

        def fake_ask(message, history):
            received_histories.append(list(history))
            return f"reply:{message}"

        with (
            patch.object(web_api, "is_within_rate_limit", return_value=True),
            patch.object(web_api, "ask_ai", side_effect=fake_ask),
        ):
            first = self.client.post(
                "/api/web/v1/chat",
                json={"message": "first"},
            )
            second = self.client.post(
                "/api/web/v1/chat",
                json={"message": "second"},
            )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(received_histories[0], [])
        self.assertEqual(
            received_histories[1],
            [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "reply:first"},
            ],
        )
        self.assertIn(f"web:history:{user_id}", self.redis.lists)

    def test_chat_uses_web_rate_keys(self):
        _, user_id = self.authenticate()
        with (
            patch.object(web_api, "get_history", return_value=[]),
            patch.object(web_api, "ask_ai", return_value="reply"),
            patch.object(web_api, "save_turn"),
        ):
            response = self.client.post(
                "/api/web/v1/chat",
                json={"message": "hello"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.redis.last_eval_keys,
            (f"web:rate:{user_id}:10s", f"web:rate:{user_id}:60s"),
        )
        self.assertNotIn(f"wechat:rate:{user_id}:10s", self.redis.rate_counts)

    def test_rate_limit_returns_429_before_history_and_ai(self):
        self.authenticate()
        with (
            patch.object(web_api, "is_within_rate_limit", return_value=False),
            patch.object(web_api, "get_history") as get,
            patch.object(web_api, "ask_ai") as ask,
            patch.object(web_api, "save_turn") as save,
        ):
            response = self.client.post(
                "/api/web/v1/chat",
                json={"message": "hello"},
            )

        self.assertEqual(response.status_code, 429)
        get.assert_not_called()
        ask.assert_not_called()
        save.assert_not_called()

    def test_ai_failure_is_safe_not_logged_and_does_not_save(self):
        _, user_id = self.authenticate()
        private_message = "private-user-message"
        private_token = next(iter(self.client.cookies.values()))
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        web_api.logger.addHandler(handler)
        try:
            with (
                patch.object(web_api, "is_within_rate_limit", return_value=True),
                patch.object(web_api, "get_history", return_value=[]),
                patch.object(
                    web_api,
                    "ask_ai",
                    side_effect=RuntimeError("private-provider-error"),
                ),
                patch.object(web_api, "save_turn") as save,
            ):
                response = self.client.post(
                    "/api/web/v1/chat",
                    json={"message": private_message},
                )
        finally:
            web_api.logger.removeHandler(handler)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "AI暂时无法回复，请稍后再试。"},
        )
        save.assert_not_called()
        logs = output.getvalue()
        for private_value in (private_message, private_token, user_id, "private-provider-error"):
            self.assertNotIn(private_value, logs)


class WebImageTests(WebAPITestCase):
    IMAGE_CASES = (
        ("photo.jpg", b"\xff\xd8\xffimage", "image/jpeg"),
        ("photo.png", b"\x89PNG\r\n\x1a\nimage", "image/png"),
        ("photo.webp", b"RIFF\x04\x00\x00\x00WEBPimage", "image/webp"),
    )

    def test_image_requires_cookie(self):
        response = self.client.post(
            "/api/web/v1/image",
            files={"file": self.IMAGE_CASES[0]},
        )
        self.assertEqual(response.status_code, 401)

    def test_image_accepts_jpeg_png_and_webp(self):
        self.authenticate()
        for filename, image_bytes, mime_type in self.IMAGE_CASES:
            with self.subTest(mime_type=mime_type):
                with (
                    patch.object(web_api, "is_within_rate_limit", return_value=True),
                    patch.object(web_api, "analyze_image", return_value="analysis") as analyze,
                    patch.object(web_api, "save_turn"),
                ):
                    response = self.client.post(
                        "/api/web/v1/image",
                        files={"file": (filename, image_bytes, mime_type)},
                    )
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"reply": "analysis"})
                analyze.assert_called_once_with(image_bytes, mime_type)

    def test_image_rejects_empty_bad_mime_bad_signature_and_oversize(self):
        self.authenticate()
        cases = (
            ("empty.jpg", b"", "image/jpeg", 422),
            ("text.txt", b"plain text", "text/plain", 422),
            ("fake.png", b"\xff\xd8\xffimage", "image/png", 422),
            (
                "large.jpg",
                b"\xff\xd8\xff" + b"x" * (10 * 1024 * 1024 - 2),
                "image/jpeg",
                413,
            ),
        )
        for filename, image_bytes, mime_type, expected_status in cases:
            with self.subTest(filename=filename):
                with patch.object(web_api, "analyze_image") as analyze:
                    response = self.client.post(
                        "/api/web/v1/image",
                        files={"file": (filename, image_bytes, mime_type)},
                    )
                self.assertEqual(response.status_code, expected_status)
                analyze.assert_not_called()

    def test_image_uses_web_rate_keys_and_429_skips_ai(self):
        _, user_id = self.authenticate()
        with (
            patch.object(web_api, "analyze_image", return_value="analysis"),
            patch.object(web_api, "save_turn"),
        ):
            response = self.client.post(
                "/api/web/v1/image",
                files={"file": self.IMAGE_CASES[0]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.redis.last_eval_keys,
            (f"web:rate:{user_id}:10s", f"web:rate:{user_id}:60s"),
        )

        with (
            patch.object(web_api, "is_within_rate_limit", return_value=False),
            patch.object(web_api, "analyze_image") as analyze,
            patch.object(web_api, "save_turn") as save,
        ):
            limited = self.client.post(
                "/api/web/v1/image",
                files={"file": self.IMAGE_CASES[0]},
            )
        self.assertEqual(limited.status_code, 429)
        analyze.assert_not_called()
        save.assert_not_called()

    def test_image_ai_failure_is_safe_and_does_not_save(self):
        self.authenticate()
        with (
            patch.object(web_api, "is_within_rate_limit", return_value=True),
            patch.object(
                web_api,
                "analyze_image",
                side_effect=RuntimeError("private-provider-error"),
            ),
            patch.object(web_api, "save_turn") as save,
        ):
            response = self.client.post(
                "/api/web/v1/image",
                files={"file": self.IMAGE_CASES[0]},
            )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private-provider-error", response.text)
        save.assert_not_called()

    def test_image_success_saves_only_text_in_web_history(self):
        _, user_id = self.authenticate()
        image_bytes = self.IMAGE_CASES[0][1]
        with (
            patch.object(web_api, "is_within_rate_limit", return_value=True),
            patch.object(web_api, "analyze_image", return_value="image analysis"),
        ):
            response = self.client.post(
                "/api/web/v1/image",
                files={"file": self.IMAGE_CASES[0]},
            )

        self.assertEqual(response.status_code, 200)
        history = memory.get_history(user_id, channel="web")
        self.assertEqual(
            history,
            [
                {"role": "user", "content": web_api.IMAGE_HISTORY_PLACEHOLDER},
                {"role": "assistant", "content": "image analysis"},
            ],
        )
        raw_history = "".join(self.redis.lists[f"web:history:{user_id}"])
        self.assertNotIn(image_bytes.decode("latin1"), raw_history)
        self.assertNotIn("/9j/", raw_history)
        self.assertNotIn("file", raw_history.lower())
        self.assertNotIn(f"wechat:history:{user_id}", self.redis.lists)


class WebMemoryAndNamespaceTests(WebAPITestCase):
    def test_memory_is_idempotent_and_only_clears_current_web_history(self):
        token, user_id = self.authenticate()
        session_key = web_auth._session_key(token)
        memory.save_turn(user_id, "web", "reply", channel="web")
        memory.save_turn(user_id, "wechat", "reply")
        memory.save_turn("other-user", "other", "reply", channel="web")
        access_control.is_within_rate_limit(user_id, channel="web")
        rate_keys = access_control._rate_keys(user_id, channel="web")

        first = self.client.delete("/api/web/v1/memory")
        second = self.client.delete("/api/web/v1/memory")

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"cleared": True})
        self.assertEqual(second.status_code, 200)
        self.assertNotIn(f"web:history:{user_id}", self.redis.lists)
        self.assertIn(f"wechat:history:{user_id}", self.redis.lists)
        self.assertIn("web:history:other-user", self.redis.lists)
        self.assertIn(session_key, self.redis.values)
        for key in rate_keys:
            self.assertIn(key, self.redis.rate_counts)
        self.assertEqual(
            self.client.get("/api/web/v1/history").json(),
            {"messages": []},
        )

    def test_wechat_defaults_and_web_namespace_are_exact_and_safe(self):
        self.assertEqual(memory._history_key("same"), "wechat:history:same")
        self.assertEqual(
            memory._history_key("same", channel="web"),
            "web:history:same",
        )
        self.assertEqual(
            access_control._rate_keys("same"),
            ("wechat:rate:same:10s", "wechat:rate:same:60s"),
        )
        self.assertEqual(
            access_control._rate_keys("same", channel="web"),
            ("web:rate:same:10s", "web:rate:same:60s"),
        )
        for invalid_channel in ("mobile", "web:unsafe", "", "WEB"):
            with self.subTest(channel=invalid_channel):
                with self.assertRaises(ValueError):
                    memory._history_key("same", channel=invalid_channel)
                with self.assertRaises(ValueError):
                    access_control._rate_keys("same", channel=invalid_channel)


class WeChatRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    @staticmethod
    def signed_params():
        timestamp = "1700000000"
        nonce = "nonce"
        values = sorted([main.WECHAT_TOKEN, timestamp, nonce])
        signature = hashlib.sha1("".join(values).encode("utf-8")).hexdigest()
        return {"signature": signature, "timestamp": timestamp, "nonce": nonce}

    @staticmethod
    def xml(message_type, **fields):
        root = ElementTree.Element("xml")
        values = {
            "ToUserName": "official-account",
            "FromUserName": "wechat-user",
            "CreateTime": "1700000000",
            "MsgType": message_type,
            "MsgId": "message-id",
        }
        values.update(fields)
        for name, value in values.items():
            ElementTree.SubElement(root, name).text = value
        return ElementTree.tostring(root, encoding="utf-8")

    def post_wechat(self, message_type, **fields):
        return self.client.post(
            "/wechat",
            params=self.signed_params(),
            content=self.xml(message_type, **fields),
        )

    def test_root_and_wechat_signature_routes_are_unchanged(self):
        self.assertEqual(self.client.get("/").json(), {"status": "ok"})
        response = self.client.get(
            "/wechat",
            params={**self.signed_params(), "echostr": "echo-value"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "echo-value")

    def test_wechat_text_provider_and_history_path_are_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "get_history", return_value=[]),
            patch.object(main, "ask_ai", return_value="text-reply") as ask,
            patch.object(main, "save_turn") as save,
        ):
            response = self.post_wechat("text", Content="hello")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ElementTree.fromstring(response.content).findtext("Content"), "text-reply")
        ask.assert_called_once_with("hello", [])
        save.assert_called_once_with("wechat-user", "hello", "text-reply")

    def test_wechat_image_path_is_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "download_wechat_image", AsyncMock(return_value=(b"image", "image/jpeg"))),
            patch.object(main, "analyze_image", return_value="image-reply") as analyze,
            patch.object(main, "save_turn") as save,
        ):
            response = self.post_wechat("image", PicUrl="https://example/image")
        self.assertEqual(ElementTree.fromstring(response.content).findtext("Content"), "image-reply")
        analyze.assert_called_once_with(b"image", "image/jpeg")
        save.assert_called_once_with("wechat-user", "[用户发送了一张图片]", "image-reply")

    def test_wechat_voice_recognition_and_media_fallback_are_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "get_history", return_value=[]),
            patch.object(main, "ask_ai", return_value="voice-reply") as ask,
            patch.object(main, "save_turn"),
        ):
            response = self.post_wechat("voice", Recognition="voice text")
        self.assertEqual(ElementTree.fromstring(response.content).findtext("Content"), "voice-reply")
        ask.assert_called_once_with("voice text", [])

        with (
            patch.object(main, "WECHAT_MEDIA_VOICE_FALLBACK_ENABLED", True),
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "download_voice_media", AsyncMock(return_value=b"audio")) as download,
            patch.object(main, "convert_audio_to_wav", return_value=b"wav") as convert,
            patch.object(main, "transcribe_audio", return_value="transcribed") as transcribe,
            patch.object(main, "get_history", return_value=[]),
            patch.object(main, "ask_ai", return_value="fallback-reply"),
            patch.object(main, "save_turn"),
        ):
            fallback = self.post_wechat("voice", Recognition="", MediaId="media-id", Format="amr")
        self.assertEqual(ElementTree.fromstring(fallback.content).findtext("Content"), "fallback-reply")
        download.assert_awaited_once_with("media-id")
        convert.assert_called_once_with(b"audio", "amr")
        transcribe.assert_called_once_with(b"wav", "voice.wav")

    def test_wechat_commands_whitelist_rate_limit_and_dedup_are_unchanged(self):
        common = (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
        )
        with common[0], common[1]:
            help_response = self.post_wechat("text", Content="帮助")
        self.assertIn("AI 助手使用说明", ElementTree.fromstring(help_response.content).findtext("Content"))

        with patch.object(main, "get_cached_reply", return_value=None), patch.object(main, "cache_reply"):
            id_response = self.post_wechat("text", Content="我的ID")
        self.assertIn("wechat-user", ElementTree.fromstring(id_response.content).findtext("Content"))

        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "clear_history") as clear,
        ):
            clear_response = self.post_wechat("text", Content="清空记忆")
        self.assertEqual(ElementTree.fromstring(clear_response.content).findtext("Content"), "聊天记忆已清空。")
        clear.assert_called_once_with("wechat-user")

        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=False),
            patch.object(main, "ask_ai") as ask,
        ):
            denied = self.post_wechat("text", Content="hello")
        self.assertEqual(ElementTree.fromstring(denied.content).findtext("Content"), "当前账号暂未开放AI功能。")
        ask.assert_not_called()

        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=False),
            patch.object(main, "ask_ai") as ask,
        ):
            limited = self.post_wechat("text", Content="hello")
        self.assertEqual(ElementTree.fromstring(limited.content).findtext("Content"), "消息发送太频繁，请稍后再试。")
        ask.assert_not_called()

        cached_xml = b"<xml><Content>cached</Content></xml>"
        with patch.object(main, "get_cached_reply", return_value=cached_xml), patch.object(main, "ask_ai") as ask:
            cached = self.post_wechat("text", Content="hello")
        self.assertEqual(cached.content, cached_xml)
        ask.assert_not_called()


if __name__ == "__main__":
    unittest.main()
