import hashlib
import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch
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
        self.ttls = {}
        self.last_lrange_key = None
        self.last_eval_keys = None

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)

    def lrange(self, key, start, end):
        self.last_lrange_key = key
        return []

    def eval(self, script, number_of_keys, key_10s, key_60s):
        self.last_eval_keys = (key_10s, key_60s)
        return [1, 1]


class FailingRedis:
    def get(self, key):
        raise ConnectionError("redis unavailable")

    def set(self, *args, **kwargs):
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
