import json
import os
import unittest
from unittest.mock import Mock, patch

import httpx

import access_control
import audio_utils
import memory
import message_dedup
import wechat_api


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.eval_keys = None

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def eval(self, script, number_of_keys, key_10s, key_60s):
        self.eval_keys = (key_10s, key_60s)
        return [1, 1]


class RuntimeControlRegressionTests(unittest.TestCase):
    def test_wechat_whitelist_behavior_is_unchanged(self):
        with patch.dict(
            os.environ,
            {
                "WECHAT_WHITELIST_ENABLED": "true",
                "WECHAT_ALLOWED_USERS": "allowed-1, allowed-2",
            },
        ):
            self.assertTrue(access_control.is_user_allowed("allowed-1"))
            self.assertTrue(access_control.is_user_allowed("allowed-2"))
            self.assertFalse(access_control.is_user_allowed("other-user"))
            self.assertFalse(access_control.is_user_allowed(""))

        with patch.dict(
            os.environ,
            {"WECHAT_WHITELIST_ENABLED": "false"},
        ):
            self.assertTrue(access_control.is_user_allowed("other-user"))

    def test_rate_limit_keys_remain_isolated_and_unchanged(self):
        fake_redis = FakeRedis()
        with patch.object(access_control, "_redis_client", fake_redis):
            self.assertTrue(access_control.is_within_rate_limit("same-user"))
            self.assertEqual(
                fake_redis.eval_keys,
                (
                    "wechat:rate:same-user:10s",
                    "wechat:rate:same-user:60s",
                ),
            )

            self.assertTrue(
                access_control.is_within_rate_limit(
                    "same-user",
                    channel="web",
                )
            )
            self.assertEqual(
                fake_redis.eval_keys,
                (
                    "web:rate:same-user:10s",
                    "web:rate:same-user:60s",
                ),
            )

    def test_message_dedup_key_ttl_hash_and_cached_reply_are_unchanged(self):
        fake_redis = FakeRedis()
        response_xml = b"<xml><Content>reply</Content></xml>"
        with patch.object(message_dedup, "_redis_client", fake_redis):
            message_dedup.cache_reply(
                "message-1",
                "private-user-id",
                response_xml,
            )

            key = "wechat:message:message-1"
            self.assertIn(key, fake_redis.values)
            self.assertEqual(
                fake_redis.ttls[key],
                message_dedup.MESSAGE_DEDUP_TTL_SECONDS,
            )
            payload = json.loads(fake_redis.values[key])
            self.assertNotIn("private-user-id", fake_redis.values[key])
            self.assertEqual(
                payload["user_hash"],
                message_dedup._user_hash("private-user-id"),
            )
            self.assertEqual(
                message_dedup.get_cached_reply(
                    "message-1",
                    "private-user-id",
                ),
                response_xml,
            )
            self.assertIsNone(
                message_dedup.get_cached_reply(
                    "message-1",
                    "different-user",
                )
            )

    def test_history_key_names_remain_unchanged(self):
        self.assertEqual(
            memory._history_key("same-user"),
            "wechat:history:same-user",
        )
        self.assertEqual(
            memory._history_key("same-user", channel="web"),
            "web:history:same-user",
        )

    def test_audio_conversion_contract_remains_unchanged(self):
        completed = Mock(
            returncode=0,
            stdout=b"RIFF\x04\x00\x00\x00WAVEaudio",
            stderr=b"",
        )
        with (
            patch.object(audio_utils.shutil, "which", return_value="ffmpeg"),
            patch.object(
                audio_utils.subprocess,
                "run",
                return_value=completed,
            ) as run,
        ):
            result = audio_utils.convert_audio_to_wav(b"audio", "amr")

        self.assertEqual(result, completed.stdout)
        command = run.call_args.args[0]
        self.assertIn("pcm_s16le", command)
        self.assertIn("16000", command)
        self.assertFalse(run.call_args.kwargs["shell"])


class WeChatAPIAccessTokenRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_access_token_still_uses_wechat_app_credentials_and_cache(self):
        captured = {}
        request = httpx.Request("GET", wechat_api.ACCESS_TOKEN_URL)
        response = httpx.Response(
            200,
            json={"access_token": "test-access-token", "expires_in": 7200},
            request=request,
        )

        class FakeAsyncClient:
            def __init__(self, **kwargs):
                captured["client_kwargs"] = kwargs

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def get(self, url, params):
                captured["url"] = url
                captured["params"] = params
                return response

        original_token = wechat_api._access_token
        original_expiry = wechat_api._access_token_expires_at
        wechat_api._access_token = None
        wechat_api._access_token_expires_at = 0.0
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "WECHAT_APP_ID": "test-app-id",
                        "WECHAT_APP_SECRET": "test-app-secret",
                    },
                ),
                patch.object(
                    wechat_api.httpx,
                    "AsyncClient",
                    FakeAsyncClient,
                ),
            ):
                first = await wechat_api.get_access_token()
                second = await wechat_api.get_access_token()
        finally:
            wechat_api._access_token = original_token
            wechat_api._access_token_expires_at = original_expiry

        self.assertEqual(first, "test-access-token")
        self.assertEqual(second, "test-access-token")
        self.assertEqual(captured["url"], wechat_api.ACCESS_TOKEN_URL)
        self.assertEqual(
            captured["params"],
            {
                "grant_type": "client_credential",
                "appid": "test-app-id",
                "secret": "test-app-secret",
            },
        )
        self.assertEqual(
            captured["client_kwargs"]["timeout"].connect,
            wechat_api.WECHAT_API_TIMEOUT_SECONDS,
        )


if __name__ == "__main__":
    unittest.main()
