import hashlib
import json
import os
import re
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("WECHAT_TOKEN", "test-wechat-token")

import main
import web_auth


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)


class FailingRedis:
    def set(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    def get(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


class WebSessionStoreTests(unittest.TestCase):
    def setUp(self):
        self.original_client = web_auth._redis_client
        self.redis = FakeRedis()
        web_auth._redis_client = self.redis

    def tearDown(self):
        web_auth._redis_client = self.original_client

    def test_session_uses_random_token_hashed_key_minimal_value_and_ttl(self):
        with patch.object(web_auth, "WEB_SESSION_TTL_SECONDS", 2592000):
            first_token, expires_in = web_auth.create_session()
            second_token, _ = web_auth.create_session()

        self.assertNotEqual(first_token, second_token)
        self.assertGreaterEqual(len(first_token), 43)
        self.assertRegex(first_token, re.compile(r"^[A-Za-z0-9_-]+$"))

        token_hash = hashlib.sha256(first_token.encode("utf-8")).hexdigest()
        expected_key = f"web:session:{token_hash}"
        self.assertIn(expected_key, self.redis.values)
        self.assertNotIn(first_token, expected_key)
        self.assertEqual(self.redis.ttls[expected_key], 2592000)
        self.assertEqual(expires_in, 2592000)

        stored_value = self.redis.values[expected_key]
        self.assertNotIn(first_token, stored_value)
        self.assertEqual(set(json.loads(stored_value)), {"user_id"})
        self.assertGreaterEqual(len(json.loads(stored_value)["user_id"]), 32)

    def test_session_lookup_rejects_missing_expired_and_malformed_values(self):
        token, _ = web_auth.create_session()
        user_id = web_auth.get_user_for_token(token)
        self.assertTrue(user_id)

        with self.assertRaises(web_auth.InvalidWebSession):
            web_auth.get_user_for_token("unknown-token")

        self.redis.values.pop(web_auth._session_key(token))
        with self.assertRaises(web_auth.InvalidWebSession):
            web_auth.get_user_for_token(token)

        malformed_token = "malformed-token"
        self.redis.values[web_auth._session_key(malformed_token)] = "not-json"
        with self.assertRaises(web_auth.InvalidWebSession):
            web_auth.get_user_for_token(malformed_token)

    def test_redis_errors_fail_closed_for_create_and_read(self):
        web_auth._redis_client = FailingRedis()
        with self.assertRaises(web_auth.WebSessionStoreError):
            web_auth.create_session()
        with self.assertRaises(web_auth.WebSessionStoreError):
            web_auth.get_user_for_token("session-token")


class WebSessionAPITests(unittest.TestCase):
    def setUp(self):
        self.original_client = web_auth._redis_client
        self.redis = FakeRedis()
        web_auth._redis_client = self.redis
        self.client = TestClient(main.app)

    def tearDown(self):
        self.client.close()
        web_auth._redis_client = self.original_client

    def test_create_session_sets_safe_cookie_and_returns_no_identity(self):
        with (
            patch.object(web_auth, "WEB_COOKIE_NAME", "custom_web_session"),
            patch.object(web_auth, "WEB_COOKIE_SECURE", False),
            patch.object(web_auth, "WEB_SESSION_TTL_SECONDS", 2592000),
        ):
            response = self.client.post("/api/web/v1/session")
            me_response = self.client.get("/api/web/v1/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertNotIn("user_id", response.text)
        self.assertNotIn("token", response.text.lower())

        set_cookie = response.headers["set-cookie"]
        self.assertIn("custom_web_session=", set_cookie)
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=lax", set_cookie)
        self.assertIn("Path=/", set_cookie)
        self.assertIn("Max-Age=2592000", set_cookie)
        self.assertNotIn("Secure", set_cookie)
        self.assertEqual(me_response.status_code, 200)

    def test_secure_cookie_configuration_is_honored(self):
        with patch.object(web_auth, "WEB_COOKIE_SECURE", True):
            response = self.client.post("/api/web/v1/session")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Secure", response.headers["set-cookie"])

    def test_session_creation_failure_returns_503_without_cookie(self):
        web_auth._redis_client = FailingRedis()
        response = self.client.post("/api/web/v1/session")

        self.assertEqual(response.status_code, 503)
        self.assertNotIn("set-cookie", response.headers)
        self.assertNotIn("redis", response.text.lower())

    def test_me_accepts_valid_cookie_without_exposing_identity(self):
        session_response = self.client.post("/api/web/v1/session")
        self.assertEqual(session_response.status_code, 200)

        response = self.client.get("/api/web/v1/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authenticated": True})
        self.assertNotIn("user_id", response.text)

    def test_me_rejects_missing_invalid_and_expired_cookie(self):
        missing = TestClient(main.app).get("/api/web/v1/me")
        self.assertEqual(missing.status_code, 401)

        invalid = self.client.get(
            "/api/web/v1/me",
            headers={"Cookie": f"{web_auth.WEB_COOKIE_NAME}=invalid"},
        )
        self.assertEqual(invalid.status_code, 401)

        token, _ = web_auth.create_session()
        self.redis.values.pop(web_auth._session_key(token))
        expired = self.client.get(
            "/api/web/v1/me",
            headers={"Cookie": f"{web_auth.WEB_COOKIE_NAME}={token}"},
        )
        self.assertEqual(expired.status_code, 401)

    def test_me_returns_503_when_session_redis_fails(self):
        web_auth._redis_client = FailingRedis()
        response = self.client.get(
            "/api/web/v1/me",
            headers={"Cookie": f"{web_auth.WEB_COOKIE_NAME}=token"},
        )
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("redis", response.text.lower())


if __name__ == "__main__":
    unittest.main()
