# -*- coding: utf-8 -*-
"""
单元测试：utils/requestsutil.py（HTTP 请求工具层）
=================================================
框架所有真实请求都经过这里，因此重点验证「参数挂载位置」的判定逻辑——
原实现只在 headers 完全等于两种固定值时才能发 POST，其它情况返回 None 导致崩溃，
这里用穷举方式把该行为固定下来。
"""
import pytest
import requests

from tests.conftest import FakeResponse, FakeSession
from utils.requestsutil import (CT_FORM, CT_JSON, CT_MULTIPART, CT_TEXT, CT_XML,
                                RequestSend, host_matches, is_internal_host)


# ======================================================================
# 一、请求体规范化
# ======================================================================
class TestNormBody:
    def test_none(self):
        assert RequestSend._norm_body(None) is None

    def test_empty_string(self):
        assert RequestSend._norm_body("   ") is None

    def test_json_string_is_parsed(self):
        assert RequestSend._norm_body('{"a": 1}') == {"a": 1}

    def test_plain_string_kept(self):
        assert RequestSend._norm_body("hello") == "hello"

    def test_dict_passthrough(self):
        obj = {"a": 1}
        assert RequestSend._norm_body(obj) is obj


# ======================================================================
# 二、Content-Type 识别
# ======================================================================
class TestContentType:
    def test_case_insensitive_key(self):
        assert RequestSend._content_type({"Content-Type": "application/json"}) == CT_JSON
        assert RequestSend._content_type({"content-type": "application/json"}) == CT_JSON

    def test_value_lowercased(self):
        assert RequestSend._content_type({"Content-Type": "Application/JSON"}) == CT_JSON

    def test_no_headers(self):
        assert RequestSend._content_type(None) == ""
        assert RequestSend._content_type({}) == ""


# ======================================================================
# 三、参数挂载位置判定（核心逻辑）
# ======================================================================
class TestBuildKwargs:
    def setup_method(self):
        self.sender = RequestSend()

    def test_data_none_returns_empty(self):
        assert self.sender._build_kwargs("post", None, {}) == {}

    @pytest.mark.parametrize("method", ["get", "head", "options", "delete"])
    def test_bodyless_methods_use_params(self, method):
        assert self.sender._build_kwargs(method, {"a": 1}, {}) == {"params": {"a": 1}}

    def test_post_without_content_type_defaults_to_json(self):
        """原实现在此场景返回 None 并导致崩溃，现应走 json。"""
        assert self.sender._build_kwargs("post", {"a": 1}, {}) == {"json": {"a": 1}}

    @pytest.mark.parametrize("method", ["post", "put", "patch"])
    def test_write_methods_default_to_json(self, method):
        kwargs = self.sender._build_kwargs(method, {"a": 1}, {"Content-Type": CT_JSON})
        assert kwargs == {"json": {"a": 1}}

    def test_form_urlencoded(self):
        headers = {"Content-Type": "{}; charset=utf-8".format(CT_FORM)}
        assert self.sender._build_kwargs("post", {"a": 1}, headers) == {"data": {"a": 1}}

    def test_multipart(self):
        headers = {"Content-Type": "{}; boundary=xxx".format(CT_MULTIPART)}
        assert self.sender._build_kwargs("post", {"f": "x"}, headers) == {"files": {"f": "x"}}

    def test_delete_without_content_type_stays_params(self):
        """历史兼容：DELETE 未声明 Content-Type 时仍按 query 参数处理。"""
        assert self.sender._build_kwargs("delete", {"id": 1}, {}) == {"params": {"id": 1}}

    def test_delete_with_json_content_type_uses_body(self):
        """REST 批量删除常见写法：DELETE + JSON 请求体。"""
        headers = {"Content-Type": CT_JSON}
        kwargs = self.sender._build_kwargs("delete", {"ids": [1, 2]}, headers)
        assert kwargs == {"json": {"ids": [1, 2]}}

    def test_delete_with_form_content_type(self):
        headers = {"Content-Type": "{}; charset=utf-8".format(CT_FORM)}
        assert self.sender._build_kwargs("delete", {"id": 1}, headers) == {"data": {"id": 1}}

    def test_delete_with_multipart_content_type(self):
        headers = {"Content-Type": "{}; boundary=x".format(CT_MULTIPART)}
        assert self.sender._build_kwargs("delete", {"f": "x"}, headers) == {"files": {"f": "x"}}

    @pytest.mark.parametrize("method", ["get", "head", "options"])
    def test_readonly_methods_ignore_content_type(self, method):
        """只读方法即使声明了 json，也不应把数据塞进请求体。"""
        kwargs = self.sender._build_kwargs(method, {"a": 1}, {"Content-Type": CT_JSON})
        assert kwargs == {"params": {"a": 1}}


# ======================================================================
# 三之二、body_location：挂载位置判定的唯一事实来源
# ======================================================================
class TestBodyLocation:
    """body_location 同时被请求层与接口层（Allure 附件）复用，需固定其全部取值。"""

    @pytest.mark.parametrize("method", ["get", "GET", "head", "options"])
    def test_readonly_methods(self, method):
        assert RequestSend.body_location(method, {}) == "params"

    @pytest.mark.parametrize("method", ["post", "put", "patch", "POST", "Put"])
    def test_write_methods(self, method):
        assert RequestSend.body_location(method, {}) == "json"
        assert RequestSend.body_location(method, {"Content-Type": CT_JSON}) == "json"

    @pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
    def test_form_and_multipart(self, method):
        assert RequestSend.body_location(method, {"Content-Type": CT_FORM}) == "data"
        assert RequestSend.body_location(method, {"Content-Type": CT_MULTIPART}) == "files"

    def test_delete_defaults_to_params(self):
        assert RequestSend.body_location("delete", {}) == "params"
        assert RequestSend.body_location("delete", None) == "params"

    def test_delete_with_raw_text_content_type_uses_data(self):
        """
        text/plain、xml 属于「原文发送」类型：报文本身就是文本，
        交给 requests 做 json 序列化会多套一层引号转义，必须走 data 原样发出。
        """
        assert RequestSend.body_location("delete", {"Content-Type": CT_TEXT}) == "data"
        assert RequestSend.body_location("delete", {"Content-Type": CT_XML}) == "data"

    def test_delete_with_unknown_content_type_falls_back_to_json(self):
        """
        真正无法识别的 Content-Type（如 octet-stream）仍按 json 提交，
        与 POST/PUT/PATCH 保持一致——否则「显式声明了请求体」的语义会被悄悄丢掉。
        """
        assert RequestSend.body_location(
            "delete", {"Content-Type": "application/octet-stream"}) == "json"

    def test_delete_with_explicit_json(self):
        assert RequestSend.body_location("delete", {"Content-Type": CT_JSON}) == "json"


# ======================================================================
# 四、send：统一响应结构
# ======================================================================
class TestSend:
    def test_response_structure(self):
        session = FakeSession(FakeResponse(
            status_code=200, payload={"status": 200}, cookies={"sid": "1"},
            headers={"Server": "mock"}, url="http://x/api"))
        result = RequestSend(session=session).send("http://x/api", "GET")

        assert set(result) == {"code", "body", "cookies", "headers",
                               "elapsed", "url", "method"}
        assert result["code"] == 200
        assert result["body"] == {"status": 200}
        assert result["cookies"] == {"sid": "1"}
        assert result["url"] == "http://x/api"
        assert result["method"] == "GET"                # 统一大写
        assert isinstance(result["elapsed"], float)
        assert result["elapsed"] >= 0

    def test_method_normalized_to_lower_for_request(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send("http://x/api", "POST")
        assert session.last_call["method"] == "post"

    # ---- 各 HTTP 方法在 send() 全链路的表现（get/post 之外的方法同样要验证） ----
    @pytest.mark.parametrize("method", ["get", "GET", "head", "options"])
    def test_readonly_methods_send_data_as_params(self, method):
        session = FakeSession(FakeResponse(payload={"status": 200}))
        result = RequestSend(session=session).send("http://x/api", method, data={"a": 1})
        call = session.last_call
        assert call["method"] == method.lower()
        assert call["kwargs"]["params"] == {"a": 1}
        assert "json" not in call["kwargs"]
        assert result["method"] == method.upper()

    @pytest.mark.parametrize("method", ["post", "put", "patch"])
    def test_write_methods_send_data_as_json(self, method):
        session = FakeSession(FakeResponse(payload={"status": 200}))
        result = RequestSend(session=session).send(
            "http://x/api", method, data={"a": 1},
            headers={"Content-Type": CT_JSON})
        call = session.last_call
        assert call["method"] == method
        assert call["kwargs"]["json"] == {"a": 1}
        assert "params" not in call["kwargs"]
        assert result["method"] == method.upper()

    def test_delete_without_content_type_sends_params(self):
        session = FakeSession(FakeResponse(payload={"status": 200}))
        RequestSend(session=session).send("http://x/api", "delete", data={"id": 1})
        assert session.last_call["kwargs"]["params"] == {"id": 1}

    def test_delete_with_json_body(self):
        """DELETE + JSON 请求体：数据必须进 json 而**不是** params。"""
        session = FakeSession(FakeResponse(payload={"status": 200}))
        RequestSend(session=session).send(
            "http://x/api", "delete", data={"ids": [1, 2]},
            headers={"Content-Type": CT_JSON})
        kwargs = session.last_call["kwargs"]
        assert kwargs["json"] == {"ids": [1, 2]}
        assert "params" not in kwargs

    def test_put_with_form_content_type_sends_data(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send(
            "http://x/api", "put", data={"a": 1}, headers={"Content-Type": CT_FORM})
        kwargs = session.last_call["kwargs"]
        assert kwargs["data"] == {"a": 1}
        assert "json" not in kwargs

    def test_patch_with_multipart_sends_files(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send(
            "http://x/api", "patch", data={"f": "x"},
            headers={"Content-Type": CT_MULTIPART})
        assert session.last_call["kwargs"]["files"] == {"f": "x"}

    def test_no_body_methods_send_no_payload_kwargs(self):
        """不传 data 时不应凭空造出 params / json 键。"""
        for method in ("get", "post", "put", "delete", "patch", "head", "options"):
            session = FakeSession(FakeResponse(payload={}))
            RequestSend(session=session).send("http://x/api", method)
            kwargs = session.last_call["kwargs"]
            assert not {"params", "json", "data", "files"} & set(kwargs), method

    def test_non_json_response_falls_back_to_text(self):
        session = FakeSession(FakeResponse(payload=None, text="<html>err</html>",
                                           json_error=True))
        result = RequestSend(session=session).send("http://x/api", "get")
        assert result["body"] == "<html>err</html>"

    def test_default_timeout_and_verify_applied(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(timeout=7, verify=True, session=session).send("http://x", "get")
        assert session.last_call["kwargs"]["timeout"] == 7
        assert session.last_call["kwargs"]["verify"] is True

    def test_explicit_params_and_files_win(self):
        """显式传入的 params / files 优先级高于自动判定。"""
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send("http://x", "post", data={"a": 1},
                                          params={"q": 2}, files={"f": "x"})
        kwargs = session.last_call["kwargs"]
        assert kwargs["params"] == {"q": 2}
        assert kwargs["files"] == {"f": "x"}

    def test_json_string_body_is_parsed_before_send(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send("http://x", "post",
                                          data='{"a": 1}',
                                          headers={"Content-Type": CT_JSON})
        assert session.last_call["kwargs"]["json"] == {"a": 1}

    def test_extra_kwargs_passed_through(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send("http://x", "get", allow_redirects=False)
        assert session.last_call["kwargs"]["allow_redirects"] is False

    def test_network_exception_is_raised(self):
        """网络层异常应向上抛（由用例层捕获为失败），而不是被吞掉。"""
        session = FakeSession(requests.ConnectionError("boom"))
        with pytest.raises(requests.RequestException):
            RequestSend(session=session).send("http://x", "get")

    def test_headers_and_cookies_forwarded(self):
        session = FakeSession(FakeResponse(payload={}))
        RequestSend(session=session).send("http://x", "get",
                                          headers={"A": "1"}, cookies={"c": "2"})
        kwargs = session.last_call["kwargs"]
        assert kwargs["headers"] == {"A": "1"}
        assert kwargs["cookies"] == {"c": "2"}

    def test_api_run_alias(self):
        """兼容旧调用名 api_run。"""
        session = FakeSession(FakeResponse(payload={"status": 200}))
        result = RequestSend(session=session).api_run("http://x", "get", data={"a": 1})
        assert result["code"] == 200
        assert session.last_call["kwargs"]["params"] == {"a": 1}


# ======================================================================
# 五、代理绕过（内网直连不被系统代理拦截）
# ======================================================================
class TestIsInternalHost:
    """
    企业环境下 CI 机器普遍配置了「出公网」代理，而被测系统在内网。
    若不绕过，内网请求会被代理拦下，报出指不到根因的 502。
    """

    @pytest.mark.parametrize("host", [
        "localhost", "127.0.0.1", "127.1.2.3", "0.0.0.0", "::1",
        "10.0.0.5", "192.168.1.100", "169.254.1.1",
        "172.16.0.1", "172.20.10.3", "172.31.255.254",
        "sso.local", "api.internal", "erp.corp", "gw.lan",
        "LOCALHOST", " 10.1.1.1 ", "[::1]",
    ])
    def test_internal(self, host):
        assert is_internal_host(host) is True, host

    @pytest.mark.parametrize("host", [
        "api.example.com", "8.8.8.8", "172.15.0.1", "172.32.0.1",
        "192.169.1.1", "100.64.0.1", "", None,
    ])
    def test_external(self, host):
        assert is_internal_host(host) is False, host


class TestHostMatches:
    def test_exact(self):
        assert host_matches("api.corp.com", ["api.corp.com"]) is True

    def test_suffix(self):
        assert host_matches("a.corp.internal", ["corp.internal"]) is True

    def test_network_prefix(self):
        assert host_matches("10.9.9.9", ["10."]) is True

    def test_no_match(self):
        assert host_matches("api.example.com", ["corp.internal"]) is False
        assert host_matches("", ["x"]) is False


class TestProxiesFor:
    def test_internal_host_bypasses_proxy(self):
        sender = RequestSend(session=FakeSession(FakeResponse(payload={})))
        assert sender.proxies_for("http://127.0.0.1:18080/v1/users/login") == {
            "http": None, "https": None}

    def test_public_host_keeps_env_proxy(self):
        sender = RequestSend(session=FakeSession(FakeResponse(payload={})))
        assert sender.proxies_for("https://api.example.com/v1/users") is None

    def test_auto_bypass_can_be_disabled(self):
        from config import settings
        settings.NetworkConfig.AUTO_BYPASS_PROXY = False
        try:
            sender = RequestSend(session=FakeSession(FakeResponse(payload={})))
            assert sender.proxies_for("http://10.0.0.1/x") is None
        finally:
            settings.NetworkConfig.AUTO_BYPASS_PROXY = True

    def test_trust_env_false_means_no_proxy_handling(self):
        from config import settings
        settings.NetworkConfig.TRUST_ENV = False
        try:
            sender = RequestSend(session=FakeSession(FakeResponse(payload={})))
            assert sender.proxies_for("http://10.0.0.1/x") is None
        finally:
            settings.NetworkConfig.TRUST_ENV = True

    def test_bypass_hosts_config_for_public_domain(self):
        from config import settings
        settings.NetworkConfig.BYPASS_HOSTS = "corp.internal,10."
        try:
            sender = RequestSend(session=FakeSession(FakeResponse(payload={})))
            assert sender.proxies_for("https://sso.corp.internal/token") is not None
        finally:
            settings.NetworkConfig.BYPASS_HOSTS = ""

    def test_send_passes_proxies_for_internal_url(self):
        session = FakeSession(FakeResponse(payload={"status": 200}))
        RequestSend(session=session).send("http://127.0.0.1:18080/v1/x", "get")
        assert session.last_call["kwargs"]["proxies"] == {"http": None, "https": None}

    def test_send_does_not_touch_proxies_for_public_url(self):
        """公网地址必须维持原有行为（沿用系统代理），不做任何额外声明。"""
        session = FakeSession(FakeResponse(payload={"status": 200}))
        RequestSend(session=session).send("https://api.example.com/x", "get")
        assert "proxies" not in session.last_call["kwargs"]
