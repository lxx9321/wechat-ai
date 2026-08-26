import json
import os
import unittest
from unittest.mock import patch

import access_control
import memory
import message_dedup


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
                    channel="miniapp",
                )
            )
            self.assertEqual(
                fake_redis.eval_keys,
                (
                    "miniapp:rate:same-user:10s",
                    "miniapp:rate:same-user:60s",
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
            memory._history_key("same-user", channel="miniapp"),
            "miniapp:history:same-user",
        )


if __name__ == "__main__":
    unittest.main()

