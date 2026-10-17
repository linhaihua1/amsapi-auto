# -*- coding: utf-8 -*-
"""
单元测试：common/auth.py（认证策略层）
======================================
市场上主流 web 系统的鉴权方式差异很大，本层把它们收敛成可插拔策略。
这里逐种固定「令牌被放到了哪个请求要素上」，因为放错位置的后果是
一个很难查的 401，而不是一条清晰的报错。
"""
import base64

import pytest

from common import auth as auth_module
from common.auth import (ApiKeyAuth, BasicAuth, BearerAuth, CookieAuth, HeaderAuth,
                         NoAuth, OAuth2ClientCredentials, build_auth, resolve_credential)
from common.variable import GlobalVar


def targets():
    """统一的「请求要素」三元组，方便断言令牌落在哪里。"""
    return {}, {}, {}


# ======================================================================
# 一、凭证变量解析
# ======================================================================
class TestResolveCredential:
    def test_plain_value_untouched(self):
        assert resolve_credential("abc") == "abc"

    def test_variable_resolved_from_pool(self):
        """令牌通常是前序登录接口提取出来的，因此要支持 ${var}。"""
        GlobalVar.set("token", "T-123")
        assert resolve_credential("${token}") == "T-123"

    def test_non_string_untouched(self):
        assert resolve_credential(123) == 123


# ======================================================================
# 二、各认证策略
# ======================================================================
class TestNoAuth:
    def test_does_nothing(self):
        headers, cookies, params = targets()
        NoAuth().apply(headers, cookies, params)
        assert (headers, cookies, params) == ({}, {}, {})

    def test_name_and_describe(self):
        assert NoAuth().name == "none"
        assert NoAuth().describe()["认证方式"] == "none"


class TestBasicAuth:
    def test_authorization_header(self):
        headers, cookies, params = targets()
        BasicAuth("admin", "pwd").apply(headers, cookies, params)
        expected = "Basic " + base64.b64encode(b"admin:pwd").decode()
        assert headers["Authorization"] == expected

    def test_credentials_support_variables(self):
        GlobalVar.set("erp_password", "secret")
        headers, _, _ = targets()
        BasicAuth("admin", "${erp_password}").apply(headers, {}, {})
        assert headers["Authorization"] == \
            "Basic " + base64.b64encode(b"admin:secret").decode()

    def test_describe_hides_password(self):
        assert "password" not in str(BasicAuth("a", "b").describe()).lower()


class TestBearerAuth:
    def test_default_header_and_prefix(self):
        headers, _, _ = targets()
        BearerAuth("T-1").apply(headers, {}, {})
        assert headers["Authorization"] == "Bearer T-1"

    def test_custom_header_and_prefix(self):
        headers, _, _ = targets()
        BearerAuth("T-1", header="X-Token", prefix="Token ").apply(headers, {}, {})
        assert headers["X-Token"] == "Token T-1"

    def test_empty_prefix_gives_bare_token(self):
        """部分系统直接把裸 token 放请求头，不能强行加 Bearer。"""
        headers, _, _ = targets()
        BearerAuth("T-1", prefix="").apply(headers, {}, {})
        assert headers["Authorization"] == "T-1"

    def test_token_from_variable_pool(self):
        GlobalVar.set("token", "JWT-abc")
        headers, _, _ = targets()
        BearerAuth("${token}").apply(headers, {}, {})
        assert headers["Authorization"] == "Bearer JWT-abc"


class TestHeaderAuth:
    def test_lands_in_named_header(self):
        """政务系统常见：access-ticket 这类自定义头。"""
        headers, _, _ = targets()
        HeaderAuth("access-ticket", "T-9").apply(headers, {}, {})
        assert headers["access-ticket"] == "T-9"

    def test_default_header_name(self):
        headers, _, _ = targets()
        HeaderAuth(value="v").apply(headers, {}, {})
        assert headers["Token"] == "v"

    def test_prefix_supported(self):
        headers, _, _ = targets()
        HeaderAuth("Token", "v", prefix="Bearer ").apply(headers, {}, {})
        assert headers["Token"] == "Bearer v"


class TestApiKeyAuth:
    def test_in_header_by_default(self):
        headers, _, params = targets()
        ApiKeyAuth("X-Api-Key", "K-1").apply(headers, {}, params)
        assert headers["X-Api-Key"] == "K-1"
        assert params == {}

    def test_in_query_when_configured(self):
        headers, _, params = targets()
        ApiKeyAuth("access_token", "K-1", location="query").apply(headers, {}, params)
        assert params["access_token"] == "K-1"
        assert "access_token" not in headers

    def test_location_case_insensitive(self):
        _, _, params = targets()
        ApiKeyAuth("k", "v", location="QUERY").apply({}, {}, params)
        assert params == {"k": "v"}


class TestCookieAuth:
    def test_from_cookie_string(self):
        """Cookie 串是最常见的配置形态，包括末尾分号与空格。"""
        _, cookies, _ = targets()
        CookieAuth(cookie_string="JSESSIONID=abc; token=xyz;").apply({}, cookies, {})
        assert cookies == {"JSESSIONID": "abc", "token": "xyz"}

    def test_from_dict(self):
        _, cookies, _ = targets()
        CookieAuth(cookies={"sid": "1"}).apply({}, cookies, {})
        assert cookies == {"sid": "1"}

    def test_dict_and_string_merged(self):
        _, cookies, _ = targets()
        CookieAuth(cookies={"a": "1"}, cookie_string="b=2").apply({}, cookies, {})
        assert cookies == {"a": "1", "b": "2"}

    def test_value_from_variable_pool(self):
        GlobalVar.set("sid", "S-1")
        _, cookies, _ = targets()
        CookieAuth(cookies={"sid": "${sid}"}).apply({}, cookies, {})
        assert cookies["sid"] == "S-1"

    def test_describe_counts_cookies(self):
        assert CookieAuth(cookie_string="a=1;b=2").describe()["Cookie 数"] == 2


class FakeTokenResponse:
    """OAuth2 取令牌响应的最小替身。"""

    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class TestOAuth2ClientCredentials:
    def _patch(self, monkeypatch, responses):
        """把 requests.post 换掉，并按顺序返回预设响应。"""
        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            item = responses.pop(0) if len(responses) > 1 else responses[0]
            if isinstance(item, Exception):
                raise item
            return item

        monkeypatch.setattr(auth_module.requests, "post", fake_post)
        return calls

    def test_fetches_token_and_applies_bearer(self, monkeypatch):
        calls = self._patch(monkeypatch, [FakeTokenResponse(payload={"access_token": "AT-1"})])
        api_auth = OAuth2ClientCredentials("http://sso/token", "cid", "sec", scope="read")
        headers, _, _ = targets()
        api_auth.apply(headers, {}, {})

        assert headers["Authorization"] == "Bearer AT-1"
        url, kwargs = calls[0]
        assert url == "http://sso/token"
        assert kwargs["data"]["grant_type"] == "client_credentials"
        assert kwargs["data"]["client_id"] == "cid"
        assert kwargs["data"]["scope"] == "read"

    def test_token_is_cached(self, monkeypatch):
        """令牌必须缓存 —— 否则每条用例都会去打一次认证服务。"""
        calls = self._patch(monkeypatch, [FakeTokenResponse(payload={"access_token": "AT-1"})])
        api_auth = OAuth2ClientCredentials("http://sso/token", "cid", "sec")
        api_auth.apply({}, {}, {})
        api_auth.apply({}, {}, {})
        api_auth.apply({}, {}, {})
        assert len(calls) == 1

    def test_basic_auth_mode_uses_http_basic(self, monkeypatch):
        calls = self._patch(monkeypatch, [FakeTokenResponse(payload={"access_token": "AT-2"})])
        api_auth = OAuth2ClientCredentials("http://sso/token", "cid", "sec", auth_mode="basic")
        api_auth.apply({}, {}, {})
        _, kwargs = calls[0]
        assert kwargs["auth"] == ("cid", "sec")
        assert "client_id" not in kwargs["data"]

    def test_expired_token_is_refreshed(self, monkeypatch):
        """
        临近过期时应重新取令牌。

        用 expires_in=1 而不是 0：0 在多数实现里被当作「未提供」而回退到默认有效期，
        而 1 秒有效期配合 60 秒的提前续期窗口，一定落在「需要刷新」的区间内。
        """
        calls = self._patch(monkeypatch, [
            FakeTokenResponse(payload={"access_token": "AT-1", "expires_in": 1}),
            FakeTokenResponse(payload={"access_token": "AT-2", "expires_in": 3600}),
        ])
        api_auth = OAuth2ClientCredentials("http://sso/token", "cid", "sec")
        assert api_auth.token == "AT-1"
        assert api_auth.token == "AT-2"       # 已过期，重新获取
        assert len(calls) == 2

    def test_expires_in_fallback_to_default(self, monkeypatch):
        """响应里没给 expires_in 时回退到默认有效期，不该立刻过期。"""
        calls = self._patch(monkeypatch, [FakeTokenResponse(payload={"access_token": "AT-1"})])
        api_auth = OAuth2ClientCredentials("http://sso/token", "cid", "sec")
        api_auth.apply({}, {}, {})
        api_auth.apply({}, {}, {})
        assert len(calls) == 1

    def test_http_error_raises_clear_message(self, monkeypatch):
        self._patch(monkeypatch, [FakeTokenResponse(status_code=401, text="bad client")])
        with pytest.raises(RuntimeError, match="OAuth2 取令牌失败"):
            OAuth2ClientCredentials("http://sso/token", "cid", "sec").token

    def test_missing_access_token_raises(self, monkeypatch):
        self._patch(monkeypatch, [FakeTokenResponse(payload={"token_type": "Bearer"})])
        with pytest.raises(RuntimeError, match="access_token"):
            OAuth2ClientCredentials("http://sso/token", "cid", "sec").token

    def test_alternative_token_field(self, monkeypatch):
        """部分平台返回的字段叫 token 而不是 access_token。"""
        self._patch(monkeypatch, [FakeTokenResponse(payload={"token": "T-9"})])
        assert OAuth2ClientCredentials("http://sso/token", "c", "s").token == "T-9"

    def test_describe(self):
        info = OAuth2ClientCredentials("http://sso/token", "c", "s").describe()
        assert info["认证方式"] == "oauth2"
        assert info["取令牌地址"] == "http://sso/token"


# ======================================================================
# 三、工厂
# ======================================================================
class TestBuildAuth:
    def test_empty_config_yields_no_auth(self):
        assert isinstance(build_auth(None), NoAuth)
        assert isinstance(build_auth({}), NoAuth)

    def test_none_type(self):
        assert isinstance(build_auth({"type": "none"}), NoAuth)

    def test_type_case_insensitive_and_trimmed(self):
        assert isinstance(build_auth({"type": " Bearer "}), BearerAuth)

    def test_basic(self):
        result = build_auth({"type": "basic", "username": "u", "password": "p"})
        assert isinstance(result, BasicAuth)
        assert (result.username, result.password) == ("u", "p")

    def test_bearer_with_custom_header(self):
        result = build_auth({"type": "bearer", "token": "t", "header": "X-T", "prefix": ""})
        assert isinstance(result, BearerAuth)
        assert result.header == "X-T" and result.prefix == ""

    def test_header(self):
        result = build_auth({"type": "header", "header": "access-ticket", "token": "${ticket}"})
        assert isinstance(result, HeaderAuth)
        assert result.header == "access-ticket"

    def test_apikey(self):
        result = build_auth({"type": "apikey", "key_name": "k", "token": "v", "key_in": "query"})
        assert isinstance(result, ApiKeyAuth)
        assert result.location == "query"

    def test_cookie_from_json_string(self):
        """档案里 cookie 用 JSON 字符串写，需能被解析成字典。"""
        result = build_auth({"type": "cookie", "cookies": '{"sid": "1"}'})
        assert isinstance(result, CookieAuth)
        assert result.cookies == {"sid": "1"}

    def test_oauth2(self):
        result = build_auth({"type": "oauth2", "token_url": "http://t", "client_id": "c",
                             "client_secret": "s", "timeout": "5"})
        assert isinstance(result, OAuth2ClientCredentials)
        assert result.timeout == 5

    def test_keys_case_insensitive(self):
        """档案段落的键可能大小写不一，工厂需自行归一。"""
        result = build_auth({"TYPE": "bearer", "TOKEN": "t"})
        assert isinstance(result, BearerAuth)
        assert result.token == "t"

    def test_unknown_type_raises_with_choices(self):
        """打错认证类型必须立刻报错，否则会变成难查的 401。"""
        with pytest.raises(ValueError, match="不支持的认证类型"):
            build_auth({"type": "kerberos"})

    def test_auth_types_constant_lists_all(self):
        assert set(auth_module.AUTH_TYPES) == {
            "none", "basic", "bearer", "header", "apikey", "cookie", "oauth2"}
