import hashlib
import io
import json
import logging
import os
import unittest
from unittest.mock import AsyncMock, Mock, call, patch
from xml.etree import ElementTree

from fastapi.testclient import TestClient

os.environ.setdefault("WECHAT_TOKEN", "test-wechat-token")

import access_control
import main
import memory
import miniapp_api
import miniapp_auth


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


class FailingRedis:
    def get(self, key):
        raise ConnectionError("redis unavailable")

    def set(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class FailingHistoryRedis:
    def lrange(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class MiniappAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.original_client = miniapp_auth._redis_client
        self.redis = FakeRedis()
        miniapp_auth._redis_client = self.redis

    def tearDown(self):
        miniapp_auth._redis_client = self.original_client

    def test_login_success_and_response_does_not_expose_openid_or_session_key(self):
        exchange = AsyncMock(return_value="private-openid")
        with patch.object(miniapp_api, "exchange_code_for_openid", exchange):
            response = self.client.post(
                "/api/miniapp/v1/login",
                json={"code": "  temporary-code  "},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["token_type"], "Bearer")
        self.assertEqual(
            body["expires_in"],
            miniapp_auth.MINIAPP_SESSION_TTL_SECONDS,
        )
        self.assertGreaterEqual(len(body["access_token"]), 43)
        self.assertNotIn("openid", json.dumps(body).lower())
        self.assertNotIn("session_key", body)
        exchange.assert_awaited_once_with("temporary-code")

    def test_login_rejects_empty_and_oversized_code(self):
        for code in ("   ", "x" * 257):
            with self.subTest(code_length=len(code)):
                response = self.client.post(
                    "/api/miniapp/v1/login",
                    json={"code": code},
                )
                self.assertEqual(response.status_code, 422)

    def test_login_maps_wechat_and_configuration_failures_safely(self):
        failures = (
            (miniapp_auth.MiniappExchangeError("sensitive"), 502),
            (miniapp_auth.MiniappConfigurationError("sensitive"), 503),
        )
        for exception, expected_status in failures:
            with self.subTest(expected_status=expected_status):
                with patch.object(
                    miniapp_api,
                    "exchange_code_for_openid",
                    AsyncMock(side_effect=exception),
                ):
                    response = self.client.post(
                        "/api/miniapp/v1/login",
                        json={"code": "code"},
                    )
                self.assertEqual(response.status_code, expected_status)
                self.assertNotIn("sensitive", response.text)

    def test_login_returns_503_when_session_store_fails(self):
        with (
            patch.object(
                miniapp_api,
                "exchange_code_for_openid",
                AsyncMock(return_value="openid"),
            ),
            patch.object(
                miniapp_api,
                "create_session",
                side_effect=miniapp_auth.MiniappSessionStoreError("private"),
            ),
        ):
            response = self.client.post(
                "/api/miniapp/v1/login",
                json={"code": "code"},
            )

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private", response.text)

    def test_me_authenticates_valid_token_without_returning_openid(self):
        token, _ = miniapp_auth.create_session("private-openid")
        response = self.client.get(
            "/api/miniapp/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertNotIn("private-openid", response.text)

    def test_me_without_token_or_with_non_bearer_token_returns_401(self):
        responses = (
            self.client.get("/api/miniapp/v1/me"),
            self.client.get(
                "/api/miniapp/v1/me",
                headers={"Authorization": "Basic value"},
            ),
        )
        for response in responses:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_me_with_wrong_or_expired_token_returns_401(self):
        wrong = self.client.get(
            "/api/miniapp/v1/me",
            headers={"Authorization": "Bearer wrong-token"},
        )
        self.assertEqual(wrong.status_code, 401)

        token, _ = miniapp_auth.create_session("openid")
        self.redis.delete(miniapp_auth._session_key(token))
        expired = self.client.get(
            "/api/miniapp/v1/me",
            headers={"Authorization": f"Bearer {token}"},
        )
        self.assertEqual(expired.status_code, 401)

    def test_me_returns_503_when_redis_fails(self):
        miniapp_auth._redis_client = FailingRedis()
        response = self.client.get(
            "/api/miniapp/v1/me",
            headers={"Authorization": "Bearer token"},
        )
        self.assertEqual(response.status_code, 503)


class MiniappChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.original_auth_client = miniapp_auth._redis_client
        self.original_memory_client = memory._redis_client
        self.original_rate_client = access_control._redis_client
        self.redis = FakeRedis()
        miniapp_auth._redis_client = self.redis
        memory._redis_client = self.redis
        access_control._redis_client = self.redis

    def tearDown(self):
        miniapp_auth._redis_client = self.original_auth_client
        memory._redis_client = self.original_memory_client
        access_control._redis_client = self.original_rate_client

    def _authorization(self, user_id="miniapp-user"):
        token, _ = miniapp_auth.create_session(user_id)
        return token, {"Authorization": f"Bearer {token}"}

    def test_chat_authenticates_and_preserves_trimmed_message_content(self):
        _, headers = self._authorization()
        history = [{"role": "assistant", "content": "Earlier"}]
        with (
            patch.object(
                miniapp_api,
                "is_within_rate_limit",
                return_value=True,
            ) as rate_limit,
            patch.object(
                miniapp_api,
                "get_history",
                return_value=history,
            ) as get_history,
            patch.object(
                miniapp_api,
                "ask_ai",
                return_value="AI reply",
            ) as ask_ai,
            patch.object(miniapp_api, "save_turn") as save_turn,
        ):
            response = self.client.post(
                "/api/miniapp/v1/chat",
                headers=headers,
                json={"message": "  HeLLo\nWorld  "},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"reply": "AI reply"})
        rate_limit.assert_called_once_with("miniapp-user", channel="miniapp")
        get_history.assert_called_once_with("miniapp-user", channel="miniapp")
        ask_ai.assert_called_once_with("HeLLo\nWorld", history)
        save_turn.assert_called_once_with(
            "miniapp-user",
            "HeLLo\nWorld",
            "AI reply",
            channel="miniapp",
        )

    def test_chat_and_memory_require_valid_unexpired_bearer_session(self):
        no_token = self.client.post(
            "/api/miniapp/v1/chat",
            json={"message": "hello"},
        )
        wrong_token = self.client.post(
            "/api/miniapp/v1/chat",
            headers={"Authorization": "Bearer wrong-token"},
            json={"message": "hello"},
        )
        token, headers = self._authorization()
        self.redis.delete(miniapp_auth._session_key(token))
        expired_token = self.client.post(
            "/api/miniapp/v1/chat",
            headers=headers,
            json={"message": "hello"},
        )
        memory_no_token = self.client.delete("/api/miniapp/v1/memory")
        memory_wrong_token = self.client.delete(
            "/api/miniapp/v1/memory",
            headers={"Authorization": "Bearer wrong-token"},
        )
        memory_expired_token = self.client.delete(
            "/api/miniapp/v1/memory",
            headers=headers,
        )

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(wrong_token.status_code, 401)
        self.assertEqual(expired_token.status_code, 401)
        self.assertEqual(memory_no_token.status_code, 401)
        self.assertEqual(memory_wrong_token.status_code, 401)
        self.assertEqual(memory_expired_token.status_code, 401)

    def test_chat_and_memory_return_503_when_session_redis_fails(self):
        miniapp_auth._redis_client = FailingRedis()
        chat_response = self.client.post(
            "/api/miniapp/v1/chat",
            headers={"Authorization": "Bearer token"},
            json={"message": "hello"},
        )
        memory_response = self.client.delete(
            "/api/miniapp/v1/memory",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(chat_response.status_code, 503)
        self.assertEqual(memory_response.status_code, 503)

    def test_chat_rejects_invalid_messages_before_business_calls(self):
        _, headers = self._authorization()
        invalid_messages = ("", "   ", "x" * 2001, 123)
        with (
            patch.object(miniapp_api, "is_within_rate_limit") as rate_limit,
            patch.object(miniapp_api, "get_history") as get_history,
            patch.object(miniapp_api, "ask_ai") as ask_ai,
            patch.object(miniapp_api, "save_turn") as save_turn,
        ):
            for message in invalid_messages:
                with self.subTest(message_type=type(message).__name__):
                    response = self.client.post(
                        "/api/miniapp/v1/chat",
                        headers=headers,
                        json={"message": message},
                    )
                    self.assertEqual(response.status_code, 422)

        rate_limit.assert_not_called()
        get_history.assert_not_called()
        ask_ai.assert_not_called()
        save_turn.assert_not_called()

    def test_chat_uses_miniapp_rate_keys(self):
        _, headers = self._authorization("same-user-id")
        with (
            patch.object(miniapp_api, "get_history", return_value=[]),
            patch.object(miniapp_api, "ask_ai", return_value="reply"),
            patch.object(miniapp_api, "save_turn"),
        ):
            response = self.client.post(
                "/api/miniapp/v1/chat",
                headers=headers,
                json={"message": "hello"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.redis.last_eval_keys,
            (
                "miniapp:rate:same-user-id:10s",
                "miniapp:rate:same-user-id:60s",
            ),
        )
        self.assertNotIn(
            "wechat:rate:same-user-id:10s",
            self.redis.rate_counts,
        )

    def test_rate_limit_returns_429_before_history_or_openai(self):
        _, headers = self._authorization()
        with (
            patch.object(
                miniapp_api,
                "is_within_rate_limit",
                return_value=False,
            ),
            patch.object(miniapp_api, "get_history") as get_history,
            patch.object(miniapp_api, "ask_ai") as ask_ai,
            patch.object(miniapp_api, "save_turn") as save_turn,
        ):
            response = self.client.post(
                "/api/miniapp/v1/chat",
                headers=headers,
                json={"message": "hello"},
            )

        self.assertEqual(response.status_code, 429)
        self.assertEqual(
            response.json(),
            {"detail": "消息发送太频繁，请稍后再试。"},
        )
        get_history.assert_not_called()
        ask_ai.assert_not_called()
        save_turn.assert_not_called()

    def test_second_chat_reads_history_saved_by_first_chat(self):
        _, headers = self._authorization("history-user")
        ask_ai = Mock(side_effect=["first reply", "second reply"])
        with (
            patch.object(
                miniapp_api,
                "is_within_rate_limit",
                return_value=True,
            ),
            patch.object(miniapp_api, "ask_ai", ask_ai),
        ):
            first = self.client.post(
                "/api/miniapp/v1/chat",
                headers=headers,
                json={"message": "first message"},
            )
            second = self.client.post(
                "/api/miniapp/v1/chat",
                headers=headers,
                json={"message": "second message"},
            )

        self.assertEqual(first.json(), {"reply": "first reply"})
        self.assertEqual(second.json(), {"reply": "second reply"})
        self.assertEqual(
            ask_ai.call_args_list,
            [
                call("first message", []),
                call(
                    "second message",
                    [
                        {"role": "user", "content": "first message"},
                        {"role": "assistant", "content": "first reply"},
                    ],
                ),
            ],
        )
        self.assertIn(
            "miniapp:history:history-user",
            self.redis.lists,
        )
        self.assertNotIn(
            "wechat:history:history-user",
            self.redis.lists,
        )

    def test_ai_failure_is_safe_not_logged_and_does_not_save(self):
        token, headers = self._authorization("never-log-openid")
        message = "never-log-message"
        internal_error = "never-expose-internal-openai-error"
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        miniapp_api.logger.addHandler(handler)
        try:
            with (
                patch.object(
                    miniapp_api,
                    "is_within_rate_limit",
                    return_value=True,
                ),
                patch.object(miniapp_api, "get_history", return_value=[]),
                patch.object(
                    miniapp_api,
                    "ask_ai",
                    side_effect=RuntimeError(internal_error),
                ),
                patch.object(miniapp_api, "save_turn") as save_turn,
            ):
                response = self.client.post(
                    "/api/miniapp/v1/chat",
                    headers=headers,
                    json={"message": message},
                )
        finally:
            miniapp_api.logger.removeHandler(handler)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "AI暂时无法回复，请稍后再试。"},
        )
        save_turn.assert_not_called()
        combined_output = response.text + output.getvalue()
        self.assertNotIn(internal_error, combined_output)
        self.assertNotIn(message, combined_output)
        self.assertNotIn("never-log-openid", combined_output)
        self.assertNotIn(token, combined_output)

    def test_delete_memory_is_idempotent_and_isolated(self):
        user_id = "same-user-id"
        other_user_id = "other-user"
        token, headers = self._authorization(user_id)
        session_key = miniapp_auth._session_key(token)
        session_value = self.redis.values[session_key]

        memory.save_turn(user_id, "wechat message", "wechat reply")
        memory.save_turn(
            user_id,
            "miniapp message",
            "miniapp reply",
            channel="miniapp",
        )
        memory.save_turn(
            other_user_id,
            "other message",
            "other reply",
            channel="miniapp",
        )
        access_control.is_within_rate_limit(user_id, channel="miniapp")
        rate_counts = dict(self.redis.rate_counts)

        first = self.client.delete(
            "/api/miniapp/v1/memory",
            headers=headers,
        )
        second = self.client.delete(
            "/api/miniapp/v1/memory",
            headers=headers,
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), {"cleared": True})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.json(), {"cleared": True})
        self.assertNotIn("miniapp:history:same-user-id", self.redis.lists)
        self.assertIn("wechat:history:same-user-id", self.redis.lists)
        self.assertIn("miniapp:history:other-user", self.redis.lists)
        self.assertEqual(self.redis.values[session_key], session_value)
        self.assertEqual(self.redis.rate_counts, rate_counts)

    def test_history_requires_valid_bearer_session(self):
        no_token = self.client.get("/api/miniapp/v1/history")
        wrong_token = self.client.get(
            "/api/miniapp/v1/history",
            headers={"Authorization": "Bearer wrong-token"},
        )
        token, headers = self._authorization("expired-user")
        self.redis.delete(miniapp_auth._session_key(token))
        expired_token = self.client.get(
            "/api/miniapp/v1/history",
            headers=headers,
        )

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(wrong_token.status_code, 401)
        self.assertEqual(expired_token.status_code, 401)

    def test_history_returns_503_when_session_redis_fails(self):
        miniapp_auth._redis_client = FailingRedis()
        response = self.client.get(
            "/api/miniapp/v1/history",
            headers={"Authorization": "Bearer token"},
        )

        self.assertEqual(response.status_code, 503)

    def test_history_returns_empty_messages_for_new_user(self):
        _, headers = self._authorization("new-user")
        response = self.client.get(
            "/api/miniapp/v1/history",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"messages": []})

    def test_history_returns_only_current_users_miniapp_messages_in_order(self):
        user_id = "same-user-id"
        _, headers = self._authorization(user_id)
        memory.save_turn(
            user_id,
            "current first",
            "current first reply",
            channel="miniapp",
        )
        memory.save_turn(
            user_id,
            "current second",
            "current second reply",
            channel="miniapp",
        )
        memory.save_turn(user_id, "wechat message", "wechat reply")
        memory.save_turn(
            "other-user",
            "other message",
            "other reply",
            channel="miniapp",
        )

        response = self.client.get(
            "/api/miniapp/v1/history",
            headers=headers,
            params={"user_id": "other-user", "openid": "other-user"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "messages": [
                    {"role": "user", "content": "current first"},
                    {
                        "role": "assistant",
                        "content": "current first reply",
                    },
                    {"role": "user", "content": "current second"},
                    {
                        "role": "assistant",
                        "content": "current second reply",
                    },
                ]
            },
        )
        self.assertEqual(
            set(response.json()["messages"][0]),
            {"role", "content"},
        )

    def test_history_redis_failure_degrades_to_empty_messages(self):
        _, headers = self._authorization("history-user")
        memory._redis_client = FailingHistoryRedis()

        response = self.client.get(
            "/api/miniapp/v1/history",
            headers=headers,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"messages": []})

    def test_history_is_empty_after_memory_clear(self):
        _, headers = self._authorization("history-user")
        memory.save_turn(
            "history-user",
            "message",
            "reply",
            channel="miniapp",
        )

        cleared = self.client.delete(
            "/api/miniapp/v1/memory",
            headers=headers,
        )
        history_response = self.client.get(
            "/api/miniapp/v1/history",
            headers=headers,
        )

        self.assertEqual(cleared.status_code, 200)
        self.assertEqual(history_response.status_code, 200)
        self.assertEqual(history_response.json(), {"messages": []})

    def test_chat_and_memory_routes_are_synchronous(self):
        import inspect

        self.assertFalse(inspect.iscoroutinefunction(miniapp_api.chat))
        self.assertFalse(inspect.iscoroutinefunction(miniapp_api.history))
        self.assertFalse(inspect.iscoroutinefunction(miniapp_api.delete_memory))


class MiniappImageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    def setUp(self):
        self.original_auth_client = miniapp_auth._redis_client
        self.original_memory_client = memory._redis_client
        self.original_rate_client = access_control._redis_client
        self.redis = FakeRedis()
        miniapp_auth._redis_client = self.redis
        memory._redis_client = self.redis
        access_control._redis_client = self.redis

    def tearDown(self):
        miniapp_auth._redis_client = self.original_auth_client
        memory._redis_client = self.original_memory_client
        access_control._redis_client = self.original_rate_client

    def _authorization(self, user_id="image-user"):
        token, _ = miniapp_auth.create_session(user_id)
        return token, {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _image_bytes(mime_type):
        samples = {
            "image/jpeg": b"\xff\xd8\xff\xe0jpeg-image-data",
            "image/png": b"\x89PNG\r\n\x1a\npng-image-data",
            "image/webp": b"RIFF\x10\x00\x00\x00WEBPwebp-image-data",
        }
        return samples[mime_type]

    def _post_image(self, headers, mime_type="image/jpeg", content=None):
        image_bytes = self._image_bytes(mime_type) if content is None else content
        return self.client.post(
            "/api/miniapp/v1/image",
            headers=headers,
            files={"file": ("image.bin", image_bytes, mime_type)},
        )

    def test_image_requires_bearer_session(self):
        no_token = self._post_image({})
        wrong_token = self._post_image(
            {"Authorization": "Bearer wrong-token"}
        )

        self.assertEqual(no_token.status_code, 401)
        self.assertEqual(wrong_token.status_code, 401)

    def test_image_accepts_jpeg_png_and_webp(self):
        _, headers = self._authorization()
        for mime_type in ("image/jpeg", "image/png", "image/webp"):
            image_bytes = self._image_bytes(mime_type)
            with self.subTest(mime_type=mime_type):
                with (
                    patch.object(
                        miniapp_api,
                        "is_within_rate_limit",
                        return_value=True,
                    ),
                    patch.object(
                        miniapp_api,
                        "analyze_image",
                        return_value="analysis result",
                    ) as analyze_image,
                    patch.object(miniapp_api, "save_turn") as save_turn,
                ):
                    response = self._post_image(headers, mime_type)

                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json(), {"reply": "analysis result"})
                analyze_image.assert_called_once_with(image_bytes, mime_type)
                save_turn.assert_called_once_with(
                    "image-user",
                    miniapp_api.IMAGE_HISTORY_PLACEHOLDER,
                    "analysis result",
                    channel="miniapp",
                )

    def test_image_rejects_empty_non_image_mismatched_and_oversized_files(self):
        _, headers = self._authorization()
        oversized = b"\xff\xd8\xff" + b"x" * (
            miniapp_api.MAX_IMAGE_BYTES - 2
        )
        invalid_files = (
            ("image/jpeg", b"", 422),
            ("text/plain", b"not-an-image", 422),
            ("image/jpeg", b"not-a-jpeg", 422),
            ("image/jpeg", oversized, 413),
        )

        with (
            patch.object(miniapp_api, "is_within_rate_limit") as rate_limit,
            patch.object(miniapp_api, "analyze_image") as analyze_image,
        ):
            for mime_type, content, expected_status in invalid_files:
                with self.subTest(
                    mime_type=mime_type,
                    expected_status=expected_status,
                ):
                    response = self._post_image(
                        headers,
                        mime_type=mime_type,
                        content=content,
                    )
                    self.assertEqual(response.status_code, expected_status)
                    self.assertEqual(
                        response.json(),
                        {"detail": miniapp_api.INVALID_IMAGE_DETAIL},
                    )

        rate_limit.assert_not_called()
        analyze_image.assert_not_called()

    def test_image_uses_miniapp_rate_keys(self):
        _, headers = self._authorization("same-user-id")
        with (
            patch.object(
                miniapp_api,
                "analyze_image",
                return_value="analysis result",
            ),
            patch.object(miniapp_api, "save_turn"),
        ):
            response = self._post_image(headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.redis.last_eval_keys,
            (
                "miniapp:rate:same-user-id:10s",
                "miniapp:rate:same-user-id:60s",
            ),
        )
        self.assertNotIn(
            "wechat:rate:same-user-id:10s",
            self.redis.rate_counts,
        )

    def test_image_rate_limit_returns_429_without_analyzing(self):
        _, headers = self._authorization()
        with (
            patch.object(
                miniapp_api,
                "is_within_rate_limit",
                return_value=False,
            ),
            patch.object(miniapp_api, "analyze_image") as analyze_image,
            patch.object(miniapp_api, "save_turn") as save_turn,
        ):
            response = self._post_image(headers)

        self.assertEqual(response.status_code, 429)
        analyze_image.assert_not_called()
        save_turn.assert_not_called()

    def test_image_analysis_failure_is_safe_and_does_not_save(self):
        token, headers = self._authorization("never-log-image-user")
        internal_error = "never-expose-image-error"
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        miniapp_api.logger.addHandler(handler)
        try:
            with (
                patch.object(
                    miniapp_api,
                    "is_within_rate_limit",
                    return_value=True,
                ),
                patch.object(
                    miniapp_api,
                    "analyze_image",
                    side_effect=RuntimeError(internal_error),
                ),
                patch.object(miniapp_api, "save_turn") as save_turn,
            ):
                response = self._post_image(headers)
        finally:
            miniapp_api.logger.removeHandler(handler)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            response.json(),
            {"detail": "AI暂时无法分析这张图片，请稍后再试。"},
        )
        save_turn.assert_not_called()
        combined_output = response.text + output.getvalue()
        self.assertNotIn(internal_error, combined_output)
        self.assertNotIn("never-log-image-user", combined_output)
        self.assertNotIn(token, combined_output)
        self.assertNotIn("jpeg-image-data", combined_output)

    def test_image_success_saves_only_text_in_isolated_history(self):
        user_id = "same-user-id"
        _, headers = self._authorization(user_id)
        memory.save_turn(user_id, "wechat message", "wechat reply")

        with (
            patch.object(
                miniapp_api,
                "is_within_rate_limit",
                return_value=True,
            ),
            patch.object(
                miniapp_api,
                "analyze_image",
                return_value="图片里有一只猫。",
            ),
        ):
            response = self._post_image(headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            memory.get_history(user_id, channel="miniapp"),
            [
                {
                    "role": "user",
                    "content": miniapp_api.IMAGE_HISTORY_PLACEHOLDER,
                },
                {"role": "assistant", "content": "图片里有一只猫。"},
            ],
        )
        self.assertEqual(
            memory.get_history(user_id),
            [
                {"role": "user", "content": "wechat message"},
                {"role": "assistant", "content": "wechat reply"},
            ],
        )
        raw_history = "".join(self.redis.lists["miniapp:history:same-user-id"])
        self.assertNotIn("base64", raw_history.lower())
        self.assertNotIn("jpeg-image-data", raw_history)
        self.assertNotIn("image.bin", raw_history)

    def test_image_route_is_synchronous(self):
        import inspect

        self.assertFalse(inspect.iscoroutinefunction(miniapp_api.image))


class NamespaceCompatibilityTests(unittest.TestCase):
    def test_memory_default_and_miniapp_keys(self):
        self.assertEqual(
            memory._history_key("user-1"),
            "wechat:history:user-1",
        )
        self.assertEqual(
            memory._history_key("user-1", channel="miniapp"),
            "miniapp:history:user-1",
        )

        fake_redis = FakeRedis()
        with patch.object(memory, "_redis_client", fake_redis):
            memory.get_history("user-1")
            self.assertEqual(
                fake_redis.last_lrange_key,
                "wechat:history:user-1",
            )
            memory.get_history("user-1", channel="miniapp")
            self.assertEqual(
                fake_redis.last_lrange_key,
                "miniapp:history:user-1",
            )

    def test_memory_rejects_unsafe_channel(self):
        with self.assertRaises(ValueError):
            memory.get_history("user", channel="miniapp:unsafe")

    def test_rate_default_and_miniapp_keys(self):
        self.assertEqual(
            access_control._rate_keys("user-1"),
            (
                "wechat:rate:user-1:10s",
                "wechat:rate:user-1:60s",
            ),
        )
        self.assertEqual(
            access_control._rate_keys("user-1", channel="miniapp"),
            (
                "miniapp:rate:user-1:10s",
                "miniapp:rate:user-1:60s",
            ),
        )

        fake_redis = FakeRedis()
        with patch.object(access_control, "_redis_client", fake_redis):
            self.assertTrue(access_control.is_within_rate_limit("user-1"))
            self.assertEqual(
                fake_redis.last_eval_keys,
                (
                    "wechat:rate:user-1:10s",
                    "wechat:rate:user-1:60s",
                ),
            )
            self.assertTrue(
                access_control.is_within_rate_limit(
                    "user-1",
                    channel="miniapp",
                )
            )
            self.assertEqual(
                fake_redis.last_eval_keys,
                (
                    "miniapp:rate:user-1:10s",
                    "miniapp:rate:user-1:60s",
                ),
            )

    def test_rate_rejects_unsafe_channel(self):
        with self.assertRaises(ValueError):
            access_control.is_within_rate_limit(
                "user",
                channel="miniapp:unsafe",
            )


class WeChatRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(main.app)

    @staticmethod
    def _signed_params():
        timestamp = "1700000000"
        nonce = "nonce"
        values = sorted([main.WECHAT_TOKEN, timestamp, nonce])
        signature = hashlib.sha1("".join(values).encode("utf-8")).hexdigest()
        return {
            "signature": signature,
            "timestamp": timestamp,
            "nonce": nonce,
        }

    @staticmethod
    def _xml(message_type, **fields):
        root = ElementTree.Element("xml")
        defaults = {
            "ToUserName": "official-account",
            "FromUserName": "wechat-user",
            "CreateTime": "1700000000",
            "MsgType": message_type,
            "MsgId": "message-id",
        }
        defaults.update(fields)
        for name, value in defaults.items():
            ElementTree.SubElement(root, name).text = value
        return ElementTree.tostring(root, encoding="utf-8")

    def test_get_wechat_signature_verification_is_unchanged(self):
        response = self.client.get(
            "/wechat",
            params={**self._signed_params(), "echostr": "echo-value"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "echo-value")

    def test_post_wechat_text_path_is_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "get_history", return_value=[]),
            patch.object(main, "ask_ai", return_value="text-reply") as ask_ai,
            patch.object(main, "save_turn") as save_turn,
        ):
            response = self.client.post(
                "/wechat",
                params=self._signed_params(),
                content=self._xml("text", Content="hello"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ElementTree.fromstring(response.content).findtext("Content"),
            "text-reply",
        )
        ask_ai.assert_called_once_with("hello", [])
        save_turn.assert_called_once_with("wechat-user", "hello", "text-reply")

    def test_post_wechat_image_path_is_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(
                main,
                "download_wechat_image",
                AsyncMock(return_value=(b"image", "image/jpeg")),
            ),
            patch.object(
                main,
                "analyze_image",
                return_value="image-reply",
            ) as analyze_image,
            patch.object(main, "save_turn"),
        ):
            response = self.client.post(
                "/wechat",
                params=self._signed_params(),
                content=self._xml("image", PicUrl="https://example/image"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ElementTree.fromstring(response.content).findtext("Content"),
            "image-reply",
        )
        analyze_image.assert_called_once_with(b"image", "image/jpeg")

    def test_post_wechat_voice_recognition_path_is_unchanged(self):
        with (
            patch.object(main, "get_cached_reply", return_value=None),
            patch.object(main, "cache_reply"),
            patch.object(main, "is_user_allowed", return_value=True),
            patch.object(main, "is_within_rate_limit", return_value=True),
            patch.object(main, "get_history", return_value=[]),
            patch.object(main, "ask_ai", return_value="voice-reply") as ask_ai,
            patch.object(main, "save_turn"),
        ):
            response = self.client.post(
                "/wechat",
                params=self._signed_params(),
                content=self._xml("voice", Recognition="voice text"),
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            ElementTree.fromstring(response.content).findtext("Content"),
            "voice-reply",
        )
        ask_ai.assert_called_once_with("voice text", [])
