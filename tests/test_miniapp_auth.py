import hashlib
import io
import json
import logging
import re
import unittest
from unittest.mock import patch

import httpx

import miniapp_auth


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

    def delete(self, key):
        return int(self.values.pop(key, None) is not None)


class FailingRedis:
    def set(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    def get(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")

    def delete(self, *args, **kwargs):
        raise ConnectionError("redis unavailable")


def fake_async_client(response, captured):
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

    return FakeAsyncClient


class ExchangeCodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_exchange_code_returns_openid_and_keeps_session_key_internal(self):
        request = httpx.Request("GET", miniapp_auth.JSCODE2SESSION_URL)
        response = httpx.Response(
            200,
            json={
                "openid": "miniapp-openid",
                "session_key": "private-session-key",
            },
            request=request,
        )
        captured = {}

        with (
            patch.object(miniapp_auth, "MINIAPP_APP_ID", "miniapp-app-id"),
            patch.object(
                miniapp_auth,
                "MINIAPP_APP_SECRET",
                "miniapp-app-secret",
            ),
            patch.object(
                miniapp_auth.httpx,
                "AsyncClient",
                fake_async_client(response, captured),
            ),
        ):
            openid = await miniapp_auth.exchange_code_for_openid("  code  ")

        self.assertEqual(openid, "miniapp-openid")
        self.assertEqual(captured["url"], miniapp_auth.JSCODE2SESSION_URL)
        self.assertEqual(captured["params"]["js_code"], "code")
        self.assertEqual(captured["params"]["appid"], "miniapp-app-id")
        self.assertEqual(
            captured["params"]["secret"],
            "miniapp-app-secret",
        )
        self.assertEqual(
            captured["params"]["grant_type"],
            "authorization_code",
        )
        self.assertEqual(
            captured["client_kwargs"]["timeout"].connect,
            miniapp_auth.WECHAT_API_TIMEOUT_SECONDS,
        )

    async def test_exchange_code_rejects_wechat_error(self):
        request = httpx.Request("GET", miniapp_auth.JSCODE2SESSION_URL)
        response = httpx.Response(
            200,
            json={"errcode": 40029, "errmsg": "invalid code"},
            request=request,
        )

        with (
            patch.object(miniapp_auth, "MINIAPP_APP_ID", "app-id"),
            patch.object(miniapp_auth, "MINIAPP_APP_SECRET", "secret"),
            patch.object(
                miniapp_auth.httpx,
                "AsyncClient",
                fake_async_client(response, {}),
            ),
        ):
            with self.assertRaises(miniapp_auth.MiniappExchangeError):
                await miniapp_auth.exchange_code_for_openid("bad-code")

    async def test_exchange_code_rejects_http_error_and_missing_openid(self):
        request = httpx.Request("GET", miniapp_auth.JSCODE2SESSION_URL)
        responses = (
            httpx.Response(500, request=request),
            httpx.Response(200, json={"session_key": "hidden"}, request=request),
        )

        for response in responses:
            with self.subTest(status_code=response.status_code):
                with (
                    patch.object(miniapp_auth, "MINIAPP_APP_ID", "app-id"),
                    patch.object(
                        miniapp_auth,
                        "MINIAPP_APP_SECRET",
                        "secret",
                    ),
                    patch.object(
                        miniapp_auth.httpx,
                        "AsyncClient",
                        fake_async_client(response, {}),
                    ),
                ):
                    with self.assertRaises(miniapp_auth.MiniappExchangeError):
                        await miniapp_auth.exchange_code_for_openid("code")

    async def test_credentials_and_user_values_are_not_logged(self):
        secret = "never-log-app-secret"
        token = "never-log-access-token"
        openid = "never-log-openid"
        request = httpx.Request("GET", miniapp_auth.JSCODE2SESSION_URL)
        response = httpx.Response(
            200,
            json={
                "errcode": 40029,
                "errmsg": f"{secret} {token} {openid}",
            },
            request=request,
        )
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        miniapp_auth.logger.addHandler(handler)
        try:
            with (
                patch.object(miniapp_auth, "MINIAPP_APP_ID", "app-id"),
                patch.object(miniapp_auth, "MINIAPP_APP_SECRET", secret),
                patch.object(
                    miniapp_auth.httpx,
                    "AsyncClient",
                    fake_async_client(response, {}),
                ),
            ):
                with self.assertRaises(miniapp_auth.MiniappExchangeError):
                    await miniapp_auth.exchange_code_for_openid("code")
        finally:
            miniapp_auth.logger.removeHandler(handler)

        logs = output.getvalue()
        self.assertNotIn(secret, logs)
        self.assertNotIn(token, logs)
        self.assertNotIn(openid, logs)

    def test_httpx_request_log_redacts_jscode2session_query(self):
        secret = "never-log-app-secret"
        code = "never-log-code"
        output = io.StringIO()
        handler = logging.StreamHandler(output)
        httpx_logger = logging.getLogger("httpx")
        original_level = httpx_logger.level
        httpx_logger.addHandler(handler)
        httpx_logger.setLevel(logging.INFO)
        try:
            httpx_logger.info(
                'HTTP Request: %s %s "%s %d %s"',
                "GET",
                (
                    f"{miniapp_auth.JSCODE2SESSION_URL}"
                    f"?appid=app-id&secret={secret}&js_code={code}"
                ),
                "HTTP/1.1",
                200,
                "OK",
            )
        finally:
            httpx_logger.removeHandler(handler)
            httpx_logger.setLevel(original_level)

        logs = output.getvalue()
        self.assertIn("[REDACTED]", logs)
        self.assertNotIn(secret, logs)
        self.assertNotIn(code, logs)


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.original_client = miniapp_auth._redis_client
        self.redis = FakeRedis()
        miniapp_auth._redis_client = self.redis

    def tearDown(self):
        miniapp_auth._redis_client = self.original_client

    def test_session_uses_strong_random_token_hashed_key_and_correct_ttl(self):
        with patch.object(
            miniapp_auth,
            "MINIAPP_SESSION_TTL_SECONDS",
            604800,
        ):
            first_token, expires_in = miniapp_auth.create_session("openid-1")
            second_token, _ = miniapp_auth.create_session("openid-1")

        self.assertNotEqual(first_token, second_token)
        self.assertGreaterEqual(len(first_token), 43)
        self.assertRegex(first_token, re.compile(r"^[A-Za-z0-9_-]+$"))
        token_hash = hashlib.sha256(first_token.encode("utf-8")).hexdigest()
        expected_key = f"miniapp:session:{token_hash}"
        self.assertIn(expected_key, self.redis.values)
        self.assertNotIn(first_token, expected_key)
        self.assertEqual(self.redis.ttls[expected_key], 604800)
        self.assertEqual(expires_in, 604800)
        self.assertEqual(
            json.loads(self.redis.values[expected_key]),
            {"user_id": "openid-1"},
        )

    def test_session_lookup_and_invalidation(self):
        token, _ = miniapp_auth.create_session("openid-1")
        self.assertEqual(miniapp_auth.get_user_for_token(token), "openid-1")

        miniapp_auth.invalidate_session(token)
        with self.assertRaises(miniapp_auth.InvalidMiniappSession):
            miniapp_auth.get_user_for_token(token)

    def test_missing_expired_and_invalid_session_are_rejected(self):
        with self.assertRaises(miniapp_auth.InvalidMiniappSession):
            miniapp_auth.get_user_for_token("unknown-token")

        invalid_token = "invalid-content-token"
        self.redis.values[miniapp_auth._session_key(invalid_token)] = "not-json"
        with self.assertRaises(miniapp_auth.InvalidMiniappSession):
            miniapp_auth.get_user_for_token(invalid_token)

    def test_redis_errors_fail_closed(self):
        miniapp_auth._redis_client = FailingRedis()
        with self.assertRaises(miniapp_auth.MiniappSessionStoreError):
            miniapp_auth.create_session("openid-1")
        with self.assertRaises(miniapp_auth.MiniappSessionStoreError):
            miniapp_auth.get_user_for_token("token")
        with self.assertRaises(miniapp_auth.MiniappSessionStoreError):
            miniapp_auth.invalidate_session("token")
