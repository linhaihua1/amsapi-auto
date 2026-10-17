# -*- coding: utf-8 -*-
"""
单元测试：api/base_api.py（接口层基类，PO 模式核心）
===================================================
将被调用最频繁的一层：URL 组装、参数化替换、请求发送、关联提取、统一断言。
全部用会话替身拦截 HTTP，并 monkeypatch allure 附件，保证离线且无副作用。
"""
import base64

import pytest

from api.base_api import BaseApi, CASE_STATUS_PREFIX
from common import hooks
from common.exceptions import CaseSkipped
from common.profile import SystemProfile
from common.variable import GlobalVar
from config import settings
from tests.conftest import FakeResponse, FakeSession


@pytest.fixture
def capture_attach(monkeypatch):
    """拦截 Allure 附件调用，避免在单元测试中产生附件文件。"""
    calls = []
    monkeypatch.setattr("utils.allureutil.attach_request",
                        lambda *a, **k: calls.append(("request", a, k)))
    monkeypatch.setattr("utils.allureutil.attach_response",
                        lambda *a, **k: calls.append(("response", a, k)))
    return calls


@pytest.fixture
def api(fake_session, capture_attach):
    """带会话替身与固定域名的接口对象。"""
    return BaseApi(base_url="http://host:9050", session=fake_session)


# ======================================================================
# 一、URL 组装
# ======================================================================
class TestFullUrl:
    def test_relative_path(self, api):
        assert api._full_url("/v1/users/login") == "http://host:9050/v1/users/login"

    def test_relative_path_without_slash(self, api):
        assert api._full_url("v1/users") == "http://host:9050/v1/users"

    def test_absolute_http(self, api):
        assert api._full_url("http://other:80/x") == "http://other:80/x"

    def test_absolute_https(self, api):
        assert api._full_url("https://other/x") == "https://other/x"

    def test_base_url_trailing_slash_removed(self, fake_session, capture_attach):
        api = BaseApi(base_url="http://host:9050/", session=fake_session)
        assert api._full_url("/x") == "http://host:9050/x"

    def test_no_base_url_keeps_path(self, fake_session, capture_attach):
        settings.RunConfig.BASE_URL = ""
        api = BaseApi(session=fake_session)
        assert api._full_url("/x") == "/x"

    def test_base_url_from_settings(self, fake_session, capture_attach):
        settings.RunConfig.BASE_URL = "http://from-settings/"
        api = BaseApi(session=fake_session)
        assert api.base_url == "http://from-settings"
        assert api._full_url("/x") == "http://from-settings/x"

    def test_non_string_path(self, api):
        assert api._full_url(123) == "http://host:9050/123"


# ======================================================================
# 二、参数化
# ======================================================================
class TestResolve:
    def test_none(self):
        assert BaseApi.resolve(None) is None

    def test_no_placeholder_passthrough(self):
        data = {"a": 1}
        assert BaseApi.resolve(data) is data

    def test_placeholder_replaced(self):
        GlobalVar.set("ticket", "T-1")
        assert BaseApi.resolve({"access-ticket": "${ticket}"}) == {"access-ticket": "T-1"}

    def test_placeholder_in_string(self):
        GlobalVar.set("id", 7)
        assert BaseApi.resolve("id=${id}") == "id=7"

    def test_missing_placeholder_becomes_empty(self):
        assert BaseApi.resolve({"h": "${nope}"}) == {"h": ""}


# ======================================================================
# 三、请求发送
# ======================================================================
class TestRequest:
    def test_returns_unified_response(self, api):
        res = api.request("get", "/v1/x", data={"a": 1})
        assert res["code"] == 200
        assert res["body"] == {"status": 200}

    def test_url_assembled_and_method_lowercased(self, api, fake_session):
        api.request("POST", "/v1/x", data={"a": 1})
        assert fake_session.last_call["url"] == "http://host:9050/v1/x"
        assert fake_session.last_call["method"] == "post"

    def test_common_headers_merged_and_overridden(self, fake_session, capture_attach):
        api = BaseApi(base_url="http://h", headers={"A": "1", "B": "2"},
                      session=fake_session)
        api.request("get", "/x", headers={"B": "9"})
        assert fake_session.last_call["kwargs"]["headers"] == {"A": "1", "B": "9"}

    def test_headers_from_json_string(self, api, fake_session):
        api.request("get", "/x", headers='{"access-ticket": "abc"}')
        assert fake_session.last_call["kwargs"]["headers"] == {"access-ticket": "abc"}

    def test_placeholder_in_headers_resolved(self, api, fake_session):
        GlobalVar.set("ticket", "T-9")
        api.request("get", "/x", headers={"access-ticket": "${ticket}"})
        assert fake_session.last_call["kwargs"]["headers"]["access-ticket"] == "T-9"

    def test_json_string_data_parsed(self, api, fake_session):
        api.request("post", "/x", data='{"a": 1}')
        assert fake_session.last_call["kwargs"]["json"] == {"a": 1}

    def test_cookies_forwarded(self, api, fake_session):
        api.request("get", "/x", cookies={"sid": "1"})
        assert fake_session.last_call["kwargs"]["cookies"] == {"sid": "1"}

    def test_get_params_mounted_in_query(self, api, fake_session):
        api.request("get", "/x", data={"q": 1})
        assert fake_session.last_call["kwargs"]["params"] == {"q": 1}

    def test_post_body_mounted_in_json(self, api, fake_session):
        api.request("post", "/x", data={"q": 1})
        assert fake_session.last_call["kwargs"]["json"] == {"q": 1}

    def test_response_saved_on_instance(self, api):
        api.request("get", "/x")
        assert api.res["code"] == 200
        assert api.body == {"status": 200}
        assert api.code == 200

    def test_attachments_captured(self, api, capture_attach):
        api.request("post", "/x", data={"a": 1})
        kinds = [c[0] for c in capture_attach]
        assert kinds == ["request", "response"]

    def test_extra_kwargs_passed_through(self, api, fake_session):
        api.request("get", "/x", allow_redirects=False)
        assert fake_session.last_call["kwargs"]["allow_redirects"] is False

    # ---- 各 HTTP 方法在接口层的挂载位置（用例层直接依赖，需逐一固定） ----
    @pytest.mark.parametrize("method", ["get", "head", "options"])
    def test_readonly_methods_use_query(self, api, fake_session, method):
        api.request(method, "/x", data={"q": 1})
        call = fake_session.last_call
        assert call["method"] == method
        assert call["kwargs"]["params"] == {"q": 1}
        assert "json" not in call["kwargs"]

    @pytest.mark.parametrize("method", ["post", "put", "patch"])
    def test_write_methods_use_json_body(self, api, fake_session, method):
        api.request(method, "/x", data={"q": 1})
        call = fake_session.last_call
        assert call["method"] == method
        assert call["kwargs"]["json"] == {"q": 1}
        assert "params" not in call["kwargs"]

    def test_put_and_patch_via_api_object(self, api, fake_session):
        """连续调用多个方法时，每次请求都应使用自己声明的方法。"""
        api.request("put", "/x/1", data={"name": "a"})
        api.request("patch", "/x/1", data={"name": "b"})
        api.request("delete", "/x/1")
        assert [c["method"] for c in fake_session.calls] == ["put", "patch", "delete"]
        assert fake_session.calls[0]["kwargs"]["json"] == {"name": "a"}
        assert fake_session.calls[1]["kwargs"]["json"] == {"name": "b"}

    def test_delete_defaults_to_query(self, api, fake_session):
        api.request("delete", "/x", data={"id": 1})
        call = fake_session.last_call
        assert call["kwargs"]["params"] == {"id": 1}
        assert "json" not in call["kwargs"]

    def test_delete_with_json_content_type_uses_body(self, api, fake_session):
        """DELETE + application/json：请求体应进 json。"""
        api.request("delete", "/x", data={"ids": [1, 2]},
                    headers={"Content-Type": "application/json"})
        call = fake_session.last_call
        assert call["kwargs"]["json"] == {"ids": [1, 2]}
        assert "params" not in call["kwargs"]

    def test_delete_with_form_content_type_uses_data(self, api, fake_session):
        api.request("delete", "/x", data={"id": 1},
                    headers={"Content-Type": "application/x-www-form-urlencoded"})
        call = fake_session.last_call
        assert call["kwargs"]["data"] == {"id": 1}
        assert "json" not in call["kwargs"]

    # ---- Allure 附件的展示位置必须与实际挂载位置一致 ----
    @pytest.mark.parametrize("method", ["get", "head", "options"])
    def test_attach_uses_params_for_readonly(self, api, capture_attach, method):
        api.request(method, "/x", data={"q": 1})
        req = [c for c in capture_attach if c[0] == "request"][0]
        assert req[2].get("params") == {"q": 1}
        assert "body" not in req[2]

    @pytest.mark.parametrize("method", ["post", "put", "patch"])
    def test_attach_uses_body_for_write(self, api, capture_attach, method):
        api.request(method, "/x", data={"q": 1})
        req = [c for c in capture_attach if c[0] == "request"][0]
        assert req[2].get("body") == {"q": 1}
        assert "params" not in req[2]

    def test_attach_delete_with_json_body_shows_as_body(self, api, capture_attach):
        """DELETE 带 JSON 体时报告里应显示为「请求体」，而非查询参数。"""
        api.request("delete", "/x", data={"ids": [1]},
                    headers={"Content-Type": "application/json"})
        req = [c for c in capture_attach if c[0] == "request"][0]
        assert req[2].get("body") == {"ids": [1]}
        assert "params" not in req[2]

    def test_attach_delete_without_content_type_shows_as_params(self, api, capture_attach):
        api.request("delete", "/x", data={"id": 1})
        req = [c for c in capture_attach if c[0] == "request"][0]
        assert req[2].get("params") == {"id": 1}
        assert "body" not in req[2]


# ======================================================================
# 四、关联提取
# ======================================================================
class TestExtract:
    def test_extract_writes_global_var(self, api):
        api.res = {"code": 200, "body": {"data": {"ticket": "TK"}}}
        result = api.extract("ticket=body.data.ticket")
        assert result == {"ticket": "TK"}
        assert GlobalVar.get("ticket") == "TK"

    def test_multiple_expressions(self, api):
        api.res = {"code": 200, "body": {"data": {"ticket": "TK", "uid": 7}}}
        result = api.extract("ticket=body.data.ticket,uid=body.data.uid")
        assert result == {"ticket": "TK", "uid": 7}
        assert GlobalVar.get("uid") == 7

    def test_list_index_path(self, api):
        api.res = {"code": 200, "body": {"rows": [{"name": "第一"}]}}
        assert api.extract("first=body.rows.0.name") == {"first": "第一"}

    @pytest.mark.parametrize("relation", [None, "", "  ", "None", "none", "null", "NULL"])
    def test_empty_relation_returns_empty(self, api, relation):
        """None 字符串表示「无关联」，不能被当成表达式去解析。"""
        assert api.extract(relation) == {}

    def test_empty_expression_segments_ignored(self, api):
        """表达式里有多余逗号产生的空片段应被跳过，不影响其它变量提取。"""
        api.res = {"code": 200, "body": {"data": {"ticket": "TK", "uid": 7}}}
        assert api.extract("ticket=body.data.ticket,,uid=body.data.uid") == \
            {"ticket": "TK", "uid": 7}

    def test_missing_path_sets_none(self, api):
        api.res = {"code": 200, "body": {}}
        assert api.extract("x=body.data.ticket") == {"x": None}

    def test_extract_without_response(self, api):
        api.res = None
        assert api.extract("x=body.data") == {"x": None}


# ======================================================================
# 五、统一断言
# ======================================================================
class TestAssertions:
    def test_check_status_pass(self, api):
        api.res = {"code": 200}
        assert api.check_status(200) is True

    def test_check_status_fail(self, api):
        api.res = {"code": 500}
        with pytest.raises(AssertionError) as exc:
            api.check_status(200)
        assert "500" in str(exc.value)

    def test_check_status_without_response(self, api):
        api.res = None
        with pytest.raises(AssertionError):
            api.check_status(200)

    def test_check_business_code_pass(self, api):
        api.res = {"code": 200, "body": {"status": 200}}
        assert api.check_business_code(200) is True

    def test_check_business_code_fail(self, api):
        api.res = {"code": 200, "body": {"status": 500}}
        with pytest.raises(AssertionError) as exc:
            api.check_business_code(200)
        assert "500" in str(exc.value)

    def test_check_business_code_missing_field(self, api):
        api.res = {"code": 200, "body": {}}
        with pytest.raises(AssertionError):
            api.check_business_code(200)

    def test_check_business_code_non_dict_body(self, api):
        api.res = {"code": 200, "body": "text"}
        with pytest.raises(AssertionError):
            api.check_business_code(200)

    def test_check_business_code_custom_path(self, api):
        api.res = {"code": 200, "body": {"code": 0}}
        assert api.check_business_code(0, path="code") is True

    def test_check_json_pass(self, api):
        api.res = {"code": 200, "body": {"data": {"ticket": "TK"}}}
        assert api.check_json("body.data.ticket", "TK") is True

    def test_check_json_fail(self, api):
        api.res = {"code": 200, "body": {"data": {"ticket": "OTHER"}}}
        with pytest.raises(AssertionError) as exc:
            api.check_json("body.data.ticket", "TK")
        assert "body.data.ticket" in str(exc.value)

    def test_check_json_top_level(self, api):
        api.res = {"code": 200, "body": {}}
        assert api.check_json("code", 200) is True


# ======================================================================
# 六、数据驱动入口 run_case
# ======================================================================
class TestRunCase:
    def test_full_case_execution(self, api, fake_session):
        case = {
            "url": "/v1/users/login",
            "method": "get",
            "headers": '{"Content-Type": "application/json"}',
            "cookies": "{}",
            "request_body": '{"username": "demo_user"}',
            "relation": "ticket=body.data.ticket",
        }
        fake_session._default = FakeResponse(payload={"status": 200,
                                                      "data": {"ticket": "TK"}})
        res = api.run_case(case)

        assert res["code"] == 200
        assert GlobalVar.get("ticket") == "TK"
        assert fake_session.last_call["kwargs"]["params"] == {"username": "demo_user"}

    def test_case_without_body(self, api, fake_session):
        case = {"url": "/v1/x", "method": "get", "headers": "{}", "cookies": "{}",
                "request_body": None, "relation": "None"}
        api.run_case(case)
        assert fake_session.last_call["url"] == "http://host:9050/v1/x"

    def test_case_with_placeholder_relation(self, api, fake_session):
        """用例间的参数传递：${ticket} 在请求前被替换为变量池中的值。"""
        GlobalVar.set("ticket", "T-PRE")
        case = {"url": "/admin/x", "method": "get",
                "headers": '{"access-ticket": "${ticket}"}', "cookies": "{}",
                "request_body": None, "relation": "None"}
        api.run_case(case)
        assert fake_session.last_call["kwargs"]["headers"]["access-ticket"] == "T-PRE"

    def test_defaults_when_fields_missing(self, api, fake_session):
        """用例缺字段时不应抛异常。"""
        res = api.run_case({"url": "/v1/x", "method": "get"})
        assert res["code"] == 200


# ======================================================================
# 七、便捷属性
# ======================================================================
class TestProperties:
    def test_before_request(self, api):
        assert api.body is None
        assert api.code is None

    def test_after_request(self, api):
        api.request("get", "/x")
        assert api.body == {"status": 200}
        assert api.code == 200


# ======================================================================
# 八、超时与配置继承
# ======================================================================
class TestConfigInheritance:
    def test_timeout_from_settings(self, fake_session, capture_attach):
        settings.RunConfig.TIMEOUT = 33
        api = BaseApi(session=fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["timeout"] == 33

    def test_explicit_timeout_wins(self, fake_session, capture_attach):
        settings.RunConfig.TIMEOUT = 33
        api = BaseApi(timeout=5, session=fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["timeout"] == 5


# ======================================================================
# 九、系统适配层（档案 / 认证 / 钩子 / 响应判定 / 生命周期 / 分页）
# ======================================================================
# 这一节验证「一套框架适配市场上主流 web 系统」的核心链路。
# 之所以必须在 BaseApi 的真实调用链上固定（而不是只单测各模块），
# 是因为适配能力一旦回归，框架就从「能测多个系统」悄悄退化成
# 「只能测原来那一个系统」，而存量用例仍然全绿，问题不会自己暴露。
#
# 涉及的档案字段与用法详见 docs/08-系统适配指南.md。
def _record_headers_hook(ctx):
    """
    记录当前请求头。

    用 GlobalVar 中转（而不是模块级列表），是因为钩子以 `包.模块:函数名`
    的字符串形式加载时，只有全局单例能保证与测试断言读到同一份数据。
    """
    GlobalVar.set("__hook_headers__", dict(ctx.get("headers") or {}))
    return ctx


def make_profile(**sections):
    """
    就地组装一份临时系统档案（不落盘，避免污染 config/systems）。

    用法：make_profile(env={"base_url": "..."}, response={"style": "code"})
    """
    return SystemProfile("unit-test", sections)


def make_api(profile, session, **kwargs):
    """用指定档案 + 会话替身构造接口对象。"""
    return BaseApi(profile=profile, session=session, **kwargs)


# ----------------------------------------------------------------------
# 9.1 档案驱动的请求行为
# ----------------------------------------------------------------------
class TestProfileDrivenRequest:
    def test_profile_base_url_used_when_settings_empty(self, fake_session, capture_attach):
        settings.RunConfig.BASE_URL = ""
        api = make_api(make_profile(env={"base_url": "http://profile-host:8080"}), fake_session)
        api.request("get", "/v1/x")
        assert fake_session.last_call["url"] == "http://profile-host:8080/v1/x"

    def test_settings_base_url_wins_over_profile(self, fake_session, capture_attach):
        """域名是 CI 里最常被临时替换的东西，因此运行配置优先于档案。"""
        settings.RunConfig.BASE_URL = "http://ci-host:9999"
        api = make_api(make_profile(env={"base_url": "http://profile-host:8080"}), fake_session)
        api.request("get", "/v1/x")
        assert fake_session.last_call["url"] == "http://ci-host:9999/v1/x"

    def test_explicit_base_url_wins_over_all(self, fake_session, capture_attach):
        settings.RunConfig.BASE_URL = "http://ci-host:9999"
        api = make_api(make_profile(env={"base_url": "http://profile-host:8080"}), fake_session,
                       base_url="http://explicit")
        api.request("get", "/v1/x")
        assert fake_session.last_call["url"] == "http://explicit/v1/x"

    def test_profile_headers_are_common_headers(self, fake_session, capture_attach):
        """档案 [headers] 是系统级公共头，用例级 headers 覆盖同名键。"""
        api = make_api(make_profile(headers={"X-Client": "amsapi", "App-Code": "demo"}),
                       fake_session)
        api.request("get", "/x", headers={"App-Code": "other"})
        expected = {"X-Client": "amsapi", "App-Code": "other"}
        assert fake_session.last_call["kwargs"]["headers"] == expected

    def test_profile_header_name_case_preserved(self, fake_session, capture_attach):
        """请求头名必须保留大小写，否则 X-Auth-Token 之类的头会发错。"""
        api = make_api(make_profile(headers={"X-Auth-Token": "t"}), fake_session)
        api.request("get", "/x")
        assert "X-Auth-Token" in fake_session.last_call["kwargs"]["headers"]

    def test_profile_encoding_and_format_passed_to_client(self, fake_session, capture_attach):
        """GBK 编码 / XML 报文这类系统固有属性由档案一次性声明。"""
        api = make_api(make_profile(env={"encoding": "gbk", "response_format": "xml"}),
                       fake_session)
        assert api.client.encoding == "gbk"
        assert api.client.response_format == "xml"

    def test_default_encoding_and_format(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        assert api.client.encoding is None
        assert api.client.response_format == "auto"


class TestProfileCookies:
    """档案 [cookies] 段应当每次请求都带上（政务/ERP 常靠它区分租户上下文）。"""

    def test_profile_cookies_attached(self, fake_session, capture_attach):
        api = make_api(make_profile(cookies={"X-Tenant": "gs"}), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["cookies"] == {"X-Tenant": "gs"}

    def test_case_cookies_override_profile(self, fake_session, capture_attach):
        api = make_api(make_profile(cookies={"X-Tenant": "gs", "lang": "zh"}), fake_session)
        api.request("get", "/x", cookies={"X-Tenant": "other"})
        assert fake_session.last_call["kwargs"]["cookies"] == {"X-Tenant": "other", "lang": "zh"}

    def test_constructor_cookies_override_profile(self, fake_session, capture_attach):
        api = make_api(make_profile(cookies={"X-Tenant": "gs"}), fake_session,
                       cookies={"X-Tenant": "module"})
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["cookies"] == {"X-Tenant": "module"}

    def test_cookies_placeholder_resolved(self, fake_session, capture_attach):
        GlobalVar.set("sid", "S-9")
        api = make_api(make_profile(cookies={"sid": "${sid}"}), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["cookies"] == {"sid": "S-9"}

    def test_no_cookies_sends_none(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["cookies"] is None


class TestContentTypeFromProfile:
    """档案声明默认请求体类型后，用例不必逐条写 Content-Type（财务/ERP 常是表单提交）。"""

    def test_profile_content_type_applied(self, fake_session, capture_attach):
        api = make_api(make_profile(env={"content_type": "application/x-www-form-urlencoded"}),
                       fake_session)
        api.run_case({"url": "/x", "method": "post", "request_body": '{"a": 1}'})
        assert fake_session.last_call["kwargs"]["data"] == {"a": 1}

    def test_case_content_type_overrides_profile(self, fake_session, capture_attach):
        api = make_api(make_profile(env={"content_type": "application/x-www-form-urlencoded"}),
                       fake_session)
        api.run_case({"url": "/x", "method": "post", "request_body": '{"a": 1}',
                      "content_type": "application/json"})
        assert fake_session.last_call["kwargs"]["json"] == {"a": 1}

    def test_request_type_column_still_supported(self, fake_session, capture_attach):
        """兼容 Excel 原有的 request_type 列，存量数据不用改。"""
        api = make_api(make_profile(), fake_session)
        api.run_case({"url": "/x", "method": "post", "request_body": '{"a": 1}',
                      "request_type": "application/x-www-form-urlencoded"})
        assert fake_session.last_call["kwargs"]["data"] == {"a": 1}

    def test_case_headers_content_type_not_overwritten(self, fake_session, capture_attach):
        api = make_api(make_profile(env={"content_type": "application/json"}), fake_session)
        api.run_case({"url": "/x", "method": "post", "request_body": '{"a": 1}',
                      "headers": '{"Content-Type": "application/x-www-form-urlencoded"}'})
        assert fake_session.last_call["kwargs"]["data"] == {"a": 1}


# ----------------------------------------------------------------------
# 9.2 认证策略
# ----------------------------------------------------------------------
class TestAuthInjection:
    def test_header_auth_puts_token_in_declared_header(self, fake_session, capture_attach):
        """政务系统典型写法：令牌放在自定义头 access-ticket 上。"""
        api = make_api(make_profile(auth={"type": "header", "header": "access-ticket",
                                          "token": "T-1"}), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["access-ticket"] == "T-1"

    def test_token_resolved_per_request(self, fake_session, capture_attach):
        """令牌多来自前序接口，必须在每次请求前解析，而不是构造时解析一次。"""
        GlobalVar.set("ticket", "T-1")
        api = make_api(make_profile(auth={"type": "header", "header": "access-ticket",
                                          "token": "${ticket}"}), fake_session)
        api.request("get", "/x")
        GlobalVar.set("ticket", "T-2")
        api.request("get", "/x")
        assert fake_session.calls[0]["kwargs"]["headers"]["access-ticket"] == "T-1"
        assert fake_session.calls[1]["kwargs"]["headers"]["access-ticket"] == "T-2"

    def test_bearer_auth(self, fake_session, capture_attach):
        """商城 / 中台 / 微服务网关：Authorization: Bearer <jwt>。"""
        api = make_api(make_profile(auth={"type": "bearer", "token": "jwt-abc"}), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["Authorization"] == "Bearer jwt-abc"

    def test_bearer_auth_with_empty_prefix(self, fake_session, capture_attach):
        """部分网关要求裸 token，不带 Bearer 前缀。"""
        api = make_api(make_profile(auth={"type": "bearer", "token": "raw", "prefix": ""}),
                       fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["Authorization"] == "raw"

    def test_basic_auth(self, fake_session, capture_attach):
        """老政务 / 内部管理后台：HTTP Basic。"""
        api = make_api(make_profile(auth={"type": "basic", "username": "u", "password": "p"}),
                       fake_session)
        api.request("get", "/x")
        expected = "Basic " + base64.b64encode(b"u:p").decode("ascii")
        assert fake_session.last_call["kwargs"]["headers"]["Authorization"] == expected

    def test_apikey_in_header(self, fake_session, capture_attach):
        api = make_api(make_profile(auth={"type": "apikey", "key_name": "X-Api-Key",
                                          "token": "K-2"}), fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["X-Api-Key"] == "K-2"
        assert fake_session.last_call["kwargs"].get("params") is None

    def test_apikey_in_query_merges_into_get_params(self, fake_session, capture_attach):
        """GET 的 query 参数与认证参数是同一个位置，必须合并而非相互顶掉。"""
        api = make_api(make_profile(auth={"type": "apikey", "key_name": "appKey",
                                          "token": "K-1", "key_in": "query"}), fake_session)
        api.request("get", "/x", data={"page": 1})
        assert fake_session.last_call["kwargs"]["params"] == {"appKey": "K-1", "page": 1}

    def test_case_param_wins_over_auth_param(self, fake_session, capture_attach):
        """用例显式声明的参数优先级更高，避免被认证参数默默覆盖。"""
        api = make_api(make_profile(auth={"type": "apikey", "key_name": "appKey",
                                          "token": "K-1", "key_in": "query"}), fake_session)
        api.request("get", "/x", data={"appKey": "FROM-CASE"})
        assert fake_session.last_call["kwargs"]["params"]["appKey"] == "FROM-CASE"

    def test_apikey_in_query_on_post_goes_to_url_not_body(self, fake_session, capture_attach):
        """POST 上 query 与请求体是两个位置，认证参数不能混进 body。"""
        api = make_api(make_profile(auth={"type": "apikey", "key_name": "appKey",
                                          "token": "K-1", "key_in": "query"}), fake_session)
        api.request("post", "/x", data={"name": "n"})
        call = fake_session.last_call
        assert call["kwargs"]["params"] == {"appKey": "K-1"}
        assert call["kwargs"]["json"] == {"name": "n"}

    def test_cookie_auth(self, fake_session, capture_attach):
        """传统 web / 老 ERP：会话 Cookie。"""
        api = make_api(make_profile(auth={"type": "cookie",
                                          "cookie_string": "JSESSIONID=abc; tenant=1"}),
                       fake_session)
        api.request("get", "/x")
        expected = {"JSESSIONID": "abc", "tenant": "1"}
        assert fake_session.last_call["kwargs"]["cookies"] == expected

    def test_no_auth_adds_nothing(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.request("get", "/x")
        assert not (fake_session.last_call["kwargs"]["headers"] or {})
        assert fake_session.last_call["kwargs"]["cookies"] is None

    def test_explicit_auth_argument_overrides_profile(self, fake_session, capture_attach):
        api = make_api(make_profile(auth={"type": "bearer", "token": "profile-token"}),
                       fake_session,
                       auth=_header_auth("arg-token"))
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["X-Token"] == "arg-token"


def _header_auth(token):
    """构造一个简单的自定义头认证（用于验证 auth 参数可覆盖档案声明）。"""
    from common.auth import HeaderAuth
    return HeaderAuth("X-Token", token)


class TestOAuth2Integration:
    def test_oauth2_token_fetched_and_attached(self, fake_session, capture_attach, monkeypatch):
        """数据中台 / 开放平台：client_credentials 自动取令牌并附加到请求头。"""
        calls = []

        class FakeTokenResponse:
            status_code = 200

            @staticmethod
            def json():
                return {"access_token": "AT-1", "expires_in": 3600}

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            return FakeTokenResponse()

        monkeypatch.setattr("common.auth.requests.post", fake_post)
        api = make_api(make_profile(auth={"type": "oauth2",
                                          "token_url": "http://auth/oauth/token",
                                          "client_id": "cid", "client_secret": "sec"}),
                       fake_session)
        api.request("get", "/x")
        assert fake_session.last_call["kwargs"]["headers"]["Authorization"] == "Bearer AT-1"
        assert calls[0][0] == "http://auth/oauth/token"

    def test_oauth2_token_reused_across_requests(self, fake_session, capture_attach,
                                                 monkeypatch):
        """令牌在有效期内只取一次，避免每条用例都打一次认证接口。"""
        count = {"n": 0}

        class FakeTokenResponse:
            status_code = 200

            @staticmethod
            def json():
                count["n"] += 1
                return {"access_token": "AT-{}".format(count["n"]), "expires_in": 3600}

        monkeypatch.setattr("common.auth.requests.post",
                            lambda url, **kwargs: FakeTokenResponse())
        api = make_api(make_profile(auth={"type": "oauth2",
                                          "token_url": "http://auth/token",
                                          "client_id": "cid", "client_secret": "sec"}),
                       fake_session)
        api.request("get", "/x")
        api.request("get", "/x")
        assert count["n"] == 1
        assert fake_session.calls[1]["kwargs"]["headers"]["Authorization"] == "Bearer AT-1"


# ----------------------------------------------------------------------
# 9.3 域名别名路由（网关 + 多服务的微服务系统）
# ----------------------------------------------------------------------
class TestHostAliasRouting:
    @pytest.fixture
    def routed(self, fake_session, capture_attach):
        settings.RunConfig.BASE_URL = ""
        profile = make_profile(env={"base_url": "http://gateway:80"},
                               hosts={"user": "http://user-svc:9001",
                                      "order": "http://order-svc:9002"})
        return make_api(profile, fake_session), fake_session

    def test_host_field_selects_alias(self, routed):
        api, session = routed
        api.request("get", "/v1/user/1", host="user")
        assert session.last_call["url"] == "http://user-svc:9001/v1/user/1"

    def test_inline_alias_in_path(self, routed):
        api, session = routed
        api.request("get", "order:/v1/orders")
        assert session.last_call["url"] == "http://order-svc:9002/v1/orders"

    def test_relative_path_uses_main_host(self, routed):
        api, session = routed
        api.request("get", "/v1/health")
        assert session.last_call["url"] == "http://gateway:80/v1/health"

    def test_unknown_alias_falls_back_to_main_host(self, routed):
        api, session = routed
        api.request("get", "/v1/x", host="nope")
        assert session.last_call["url"] == "http://gateway:80/v1/x"

    def test_colon_in_path_that_is_not_alias_is_kept(self, routed):
        """形如 /v1/a:b 但不是别名的路径不能被误当成域名前缀切掉。"""
        api, session = routed
        api.request("get", "/v1/a:b")
        assert session.last_call["url"] == "http://gateway:80/v1/a:b"

    def test_absolute_url_ignores_alias(self, routed):
        api, session = routed
        api.request("get", "http://third-party:7000/api", host="user")
        assert session.last_call["url"] == "http://third-party:7000/api"

    def test_run_case_host_field(self, routed):
        api, session = routed
        api.run_case({"url": "/v1/orders", "method": "get", "host": "order"})
        assert session.last_call["url"] == "http://order-svc:9002/v1/orders"


# ----------------------------------------------------------------------
# 9.4 协议钩子（签名 / 时间戳 / 加解密）
# ----------------------------------------------------------------------
class TestBeforeHooks:
    def test_module_path_hook_runs(self, fake_session, capture_attach):
        """钩子声明支持 `包.模块:函数名` 的直接引用写法。"""
        api = make_api(make_profile(hooks={
            "before_request": "tests.test_api_base_api:_record_headers_hook"}), fake_session)
        api.request("get", "/x", headers={"X-A": "1"})
        assert GlobalVar.get("__hook_headers__") == {"X-A": "1"}

    def test_hook_runs_after_auth(self, fake_session, capture_attach):
        """签名必须覆盖认证之后的完整报文，因此钩子必须晚于认证执行。"""
        GlobalVar.set("ticket", "T-1")
        api = make_api(make_profile(
            auth={"type": "header", "header": "access-ticket", "token": "${ticket}"},
            hooks={"before_request": "tests.test_api_base_api:_record_headers_hook"}),
            fake_session)
        api.request("get", "/x")
        assert GlobalVar.get("__hook_headers__")["access-ticket"] == "T-1"

    def test_sign_hook_factory_with_json_args(self, fake_session, capture_attach):
        """工厂带 JSON 参数的写法：`common.hooks:make_sign_hook({"salt": "s"})`。"""
        api = make_api(make_profile(hooks={
            "before_request": 'common.hooks:make_sign_hook({"salt": "s", "upper": true})'}),
            fake_session)
        api.request("post", "/x", data={"b": 2, "a": 1})
        body = fake_session.last_call["kwargs"]["json"]
        assert body["sign"] == hooks.sign_sorted({"b": 2, "a": 1}, salt="s", upper=True)

    def test_sign_hook_writes_header_instead_of_body(self, fake_session, capture_attach):
        api = make_api(make_profile(hooks={
            "before_request": 'common.hooks:make_sign_hook({"target": "header", '
                              '"header": "Sign"})'}), fake_session)
        api.request("post", "/x", data={"a": 1})
        call = fake_session.last_call
        assert call["kwargs"]["headers"]["Sign"]
        assert "sign" not in call["kwargs"]["json"]

    def test_timestamp_nonce_hook(self, fake_session, capture_attach):
        """防重放：注入时间戳与随机串。"""
        api = make_api(make_profile(hooks={
            "before_request": "common.hooks:make_timestamp_nonce_hook()"}), fake_session)
        api.request("post", "/x", data={"a": 1})
        body = fake_session.last_call["kwargs"]["json"]
        assert isinstance(body["timestamp"], int)
        assert len(body["nonce"]) == 16

    def test_hooks_chain_in_declaration_order(self, fake_session, capture_attach):
        """多个钩子按声明顺序串行执行，前一个的产出能传进后一个。"""
        api = make_api(make_profile(hooks={
            "before_request": "common.hooks:make_timestamp_nonce_hook(), "
                              'common.hooks:make_sign_hook({"salt": "s"})'}), fake_session)
        api.request("post", "/x", data={"a": 1})
        body = fake_session.last_call["kwargs"]["json"]
        # 签名应覆盖到时间戳，说明时间戳钩子先跑
        assert body["sign"] == hooks.sign_sorted(
            {"a": 1, "timestamp": body["timestamp"], "nonce": body["nonce"]}, salt="s")

    def test_hook_not_applied_to_raw_text_payload(self, fake_session, capture_attach):
        """XML / 文本报文不是字典，注入型钩子应安全跳过而不是报错。"""
        api = make_api(make_profile(hooks={
            "before_request": "common.hooks:make_timestamp_nonce_hook()"}), fake_session)
        api.request("post", "/x", data="<xml><a>1</a></xml>",
                    headers={"Content-Type": "application/xml"})
        assert fake_session.last_call["kwargs"]["data"] == "<xml><a>1</a></xml>"

    def test_aes_roundtrip(self, fake_session, capture_attach):
        """可选依赖 cryptography：装了就用，支持 AES 加解密钩子。"""
        pytest.importorskip("cryptography")
        api = make_api(make_profile(hooks={
            "before_request": 'common.hooks:make_aes_hook({"key": "0123456789abcdef", '
                              '"fields": ["data"]})'}), fake_session)
        api.request("post", "/x", data={"data": {"a": 1}})
        cipher = fake_session.last_call["kwargs"]["json"]["data"]
        assert hooks.aes_decrypt(cipher, "0123456789abcdef") == '{"a":1}'


class TestAfterHooks:
    def test_after_hook_can_rewrite_response(self, fake_session, capture_attach):
        """响应后钩子（解密等）的产出必须回写到 api.res 上。"""
        profile = make_profile()

        def rewrite(ctx):
            ctx["response"]["body"] = {"status": 200, "msg": "已解密"}
            return ctx

        profile.hooks.add_after(rewrite)
        api = make_api(profile, fake_session)
        api.request("get", "/x")
        assert api.body == {"status": 200, "msg": "已解密"}

    def test_after_hook_applies_before_assertion(self, fake_session, capture_attach):
        """解密必须发生在断言之前，否则加密字段永远断言不过。"""
        fake_session._default = FakeResponse(payload={"status": 200, "data": "CIPHER"})
        profile = make_profile()

        def decrypt(ctx):
            ctx["response"]["body"]["data"] = "PLAIN"
            return ctx

        profile.hooks.add_after(decrypt)
        api = make_api(profile, fake_session)
        api.run_case({"url": "/x", "method": "get", "expects": "equals:body.data=PLAIN"})

    def test_after_hook_applies_before_extract(self, fake_session, capture_attach):
        """关联提取也应基于解密后的报文，否则提出来的令牌是密文。"""
        fake_session._default = FakeResponse(payload={"status": 200, "data": {"token": "CIPHER"}})
        profile = make_profile()

        def decrypt(ctx):
            ctx["response"]["body"]["data"]["token"] = "TK-REAL"
            return ctx

        profile.hooks.add_after(decrypt)
        api = make_api(profile, fake_session)
        api.run_case({"url": "/x", "method": "get", "relation": "tk=body.data.token"})
        assert GlobalVar.get("tk") == "TK-REAL"


# ----------------------------------------------------------------------
# 9.5 业务成功判定（响应风格）
# ----------------------------------------------------------------------
class TestCheckSuccess:
    def test_status_style_matches_legacy_behaviour(self, fake_session, capture_attach):
        """内置默认档案：body.status == expected_code，与改造前完全一致。"""
        api = make_api(make_profile(), fake_session)
        api.res = {"code": 200, "body": {"status": 200}}
        assert api.check_success(200) is True

    def test_code_style(self, fake_session, capture_attach):
        """党政 / 财务 / ERP：{"code": 200, ...}。"""
        api = make_api(make_profile(response={"style": "code"}), fake_session)
        api.res = {"code": 200, "body": {"code": 0, "msg": "ok"}}
        assert api.check_success(0) is True

    def test_success_style_without_expected_code(self, fake_session, capture_attach):
        """商城 / 中台：{"success": true}，用例可以不写 expected_code。"""
        api = make_api(make_profile(response={"style": "success"}), fake_session)
        api.res = {"code": 200, "body": {"success": True}}
        assert api.check_success() is True

    def test_success_style_false_fails(self, fake_session, capture_attach):
        api = make_api(make_profile(response={"style": "success"}), fake_session)
        api.res = {"code": 200, "body": {"success": False}}
        with pytest.raises(AssertionError):
            api.check_success()

    def test_custom_success_path(self, fake_session, capture_attach):
        """档案可自定义业务码路径，覆盖风格的默认候选。"""
        api = make_api(make_profile(response={"style": "code",
                                              "success_path": "body.biz.resultCode"}),
                       fake_session)
        api.res = {"code": 200, "body": {"biz": {"resultCode": "0000"}}}
        assert api.check_success("0000") is True

    def test_failure_message_contains_server_msg(self, fake_session, capture_attach):
        """断言失败信息里要带服务端原话，否则排障只能靠猜。"""
        api = make_api(make_profile(response={"style": "code"}), fake_session)
        api.res = {"code": 200, "body": {"code": 500, "msg": "库存不足"}}
        with pytest.raises(AssertionError) as exc:
            api.check_success(0)
        assert "库存不足" in str(exc.value)

    def test_non_2xx_http_fails_even_if_body_looks_ok(self, fake_session, capture_attach):
        """HTTP 层失败时，业务码再「成功」也不能算通过。"""
        api = make_api(make_profile(response={"style": "code"}), fake_session)
        api.res = {"code": 500, "body": {"code": 0}}
        with pytest.raises(AssertionError):
            api.check_success()

    def test_run_case_fails_on_wrong_business_code(self, fake_session, capture_attach):
        """业务判定下沉到 run_case，三个数据源驱动共用同一规则。"""
        fake_session._default = FakeResponse(payload={"code": 500, "msg": "系统异常"})
        api = make_api(make_profile(response={"style": "code"}), fake_session)
        with pytest.raises(AssertionError):
            api.run_case({"url": "/x", "method": "get", "expected_code": 0})

    def test_business_code_property(self, fake_session, capture_attach):
        api = make_api(make_profile(response={"style": "code"}), fake_session)
        api.res = {"code": 200, "body": {"code": 0, "msg": "ok"}}
        assert api.business_code == 0
        assert api.message == "ok"


# ----------------------------------------------------------------------
# 9.6 expects 断言列表
# ----------------------------------------------------------------------
class TestExpectsParsing:
    def test_none_and_empty(self):
        for raw in (None, "", "   ", [], {}):
            assert BaseApi._as_expects(raw) == []

    def test_shorthand_single(self):
        assert BaseApi._as_expects("contains:body.msg=操作成功") == [
            {"op": "contains", "path": "body.msg", "value": "操作成功"}]

    def test_shorthand_multiple_and_value_less(self):
        assert BaseApi._as_expects(
            "contains:body.msg=操作成功; gt:body.data.total=0; elapsed=3000") == [
            {"op": "contains", "path": "body.msg", "value": "操作成功"},
            {"op": "gt", "path": "body.data.total", "value": "0"},
            {"op": "elapsed", "path": None, "value": "3000"},
        ]

    def test_shorthand_value_keeps_inner_equals(self):
        """简写里 `=` 只按第一个切分，期望值本身可以带等号。"""
        assert BaseApi._as_expects("equals:body.a=1=2") == [
            {"op": "equals", "path": "body.a", "value": "1=2"}]

    def test_shorthand_path_less(self):
        assert BaseApi._as_expects("exists:body.data") == [
            {"op": "exists", "path": "body.data", "value": None}]

    def test_structured_dict(self):
        assert BaseApi._as_expects({"op": "gt", "path": "body.n", "value": 3, "msg": "m"}) == [
            {"op": "gt", "path": "body.n", "value": 3, "msg": "m"}]

    def test_structured_dict_chinese_keys(self):
        """表格里可能用中文列名，一并支持，降低填写门槛。"""
        assert BaseApi._as_expects({"断言": "gt", "路径": "body.n", "值": 3}) == [
            {"op": "gt", "path": "body.n", "value": 3, "msg": ""}]

    def test_json_string_list(self):
        assert BaseApi._as_expects('[{"op": "gt", "path": "body.n", "value": 1}]') == [
            {"op": "gt", "path": "body.n", "value": 1, "msg": ""}]

    def test_mixed_list(self):
        assert BaseApi._as_expects(
            ["exists:body.a", {"op": "gt", "path": "body.n", "value": 1}]) == [
            {"op": "exists", "path": "body.a", "value": None},
            {"op": "gt", "path": "body.n", "value": 1, "msg": ""},
        ]


class TestCheckExpects:
    def test_shorthand_executes(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.res = {"code": 200, "body": {"msg": "操作成功", "data": {"total": 5}}}
        assert api.check_expects(
            "contains:body.msg=操作成功; gt:body.data.total=0") is True

    def test_failure_raises_assertion_error(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.res = {"code": 200, "body": {"msg": "失败"}}
        with pytest.raises(AssertionError):
            api.check_expects("contains:body.msg=操作成功")

    def test_elapsed_op_uses_response_timing(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.res = {"code": 200, "body": {}, "elapsed": 12.5}
        assert api.check_expects("elapsed=1000") is True
        with pytest.raises(AssertionError):
            api.check_expects("elapsed=1")

    def test_unknown_op_lists_available(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.res = {"code": 200, "body": {}}
        with pytest.raises(AssertionError) as exc:
            api.check_expects("nope:body.a=1")
        assert "equals" in str(exc.value)


# ----------------------------------------------------------------------
# 9.7 用例生命周期（setup / teardown / depends）
# ----------------------------------------------------------------------
class TestCaseLifecycle:
    @staticmethod
    def _paging_profile():
        return make_profile(env={"base_url": "http://h"},
                            response={"style": "code", "success_values": "0"})

    def test_setup_then_request_then_teardown_order(self, capture_attach):
        session = FakeSession(responses=[
            FakeResponse(payload={"code": 0, "data": {"id": 9}}),   # setup 造数据
            FakeResponse(payload={"code": 0}),                      # 主请求
            FakeResponse(payload={"code": 0}),                      # teardown 清理
        ])
        api = make_api(self._paging_profile(), session)
        api.run_case({
            "id": "C1",
            "url": "/v1/goods",
            "method": "get",
            "setup": [{"url": "/v1/goods", "method": "post",
                       "request_body": '{"name": "g"}'}],
            "teardown": [{"url": "/v1/goods/9", "method": "delete"}],
            "expected_code": 0,
        })
        assert [call["method"] for call in session.calls] == ["post", "get", "delete"]

    def test_setup_relation_feeds_main_request(self, capture_attach):
        """前置步骤提取出来的 id 能被主请求用 ${var} 引用。"""
        session = FakeSession(responses=[
            FakeResponse(payload={"code": 0, "data": {"id": 7}}),
            FakeResponse(payload={"code": 0}),
        ])
        api = make_api(self._paging_profile(), session)
        api.run_case({
            "url": "/v1/goods/${gid}",
            "method": "get",
            "setup": [{"url": "/v1/goods", "method": "post",
                       "request_body": '{"name": "g"}', "relation": "gid=body.data.id"}],
            "expected_code": 0,
        })
        assert session.calls[1]["url"] == "http://h/v1/goods/7"

    def test_teardown_runs_even_when_assertion_fails(self, capture_attach):
        """断言失败也必须清理，否则脏数据会污染后续用例和下一次构建。"""
        session = FakeSession(responses=[
            FakeResponse(payload={"code": 500, "msg": "入库失败"}),
            FakeResponse(payload={"code": 0}),
        ])
        api = make_api(make_profile(response={"style": "code"}), session)
        with pytest.raises(AssertionError):
            api.run_case({"url": "/v1/x", "method": "get", "expected_code": 0,
                          "teardown": [{"url": "/v1/x/clean", "method": "delete"}]})
        assert [call["method"] for call in session.calls] == ["get", "delete"]

    def test_teardown_error_does_not_mask_original_failure(self, capture_attach):
        """清理自身报错时，仍应抛出原始的断言失败，方便定位真正的问题。"""
        session = FakeSession(responses=[
            FakeResponse(payload={"code": 500}),
            RuntimeError("清理接口炸了"),
        ])
        api = make_api(make_profile(response={"style": "code"}), session)
        with pytest.raises(AssertionError):
            api.run_case({"url": "/v1/x", "method": "get", "expected_code": 0,
                          "teardown": [{"url": "/v1/x", "method": "delete"}]})

    def test_depends_missing_case_raises_skipped(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        with pytest.raises(CaseSkipped):
            api.check_depends({"depends": "C404"})

    def test_skipped_case_clears_previous_response(self, fake_session, capture_attach):
        """被 depends 跳过的用例不能把上一条用例的响应留在 res 上（结果回写会串行）。"""
        api = make_api(make_profile(), fake_session)
        api.run_case({"id": "C1", "url": "/x", "method": "get"})
        assert api.res is not None
        with pytest.raises(CaseSkipped):
            api.run_case({"id": "C2", "url": "/x", "method": "get", "depends": "C404"})
        assert api.res is None

    def test_depends_failed_case_raises_skipped(self, fake_session, capture_attach):
        GlobalVar.set(CASE_STATUS_PREFIX + "C1", "fail")
        api = make_api(make_profile(), fake_session)
        with pytest.raises(CaseSkipped):
            api.check_depends({"depends": "C1"})

    def test_depends_passed_allows_run(self, fake_session, capture_attach):
        GlobalVar.set(CASE_STATUS_PREFIX + "C1", "pass")
        api = make_api(make_profile(), fake_session)
        assert api.check_depends({"depends": "C1"}) is True

    def test_depends_multiple_with_chinese_comma(self, fake_session, capture_attach):
        GlobalVar.set(CASE_STATUS_PREFIX + "C1", "pass")
        GlobalVar.set(CASE_STATUS_PREFIX + "C2", "pass")
        api = make_api(make_profile(), fake_session)
        assert api.check_depends({"depends": "C1，C2"}) is True

    def test_record_case_status(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.record_case_status({"id": "C9"}, True)
        assert GlobalVar.get(CASE_STATUS_PREFIX + "C9") == "pass"
        api.record_case_status({"id": "C9"}, False)
        assert GlobalVar.get(CASE_STATUS_PREFIX + "C9") == "fail"

    def test_record_case_status_without_id_is_noop(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.record_case_status({}, True)
        assert GlobalVar.get(CASE_STATUS_PREFIX, None) is None

    def test_run_case_records_pass(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_case({"id": "C1", "url": "/x", "method": "get"})
        assert GlobalVar.get(CASE_STATUS_PREFIX + "C1") == "pass"

    def test_run_case_records_fail(self, fake_session, capture_attach):
        fake_session._default = FakeResponse(payload={"status": 500})
        api = make_api(make_profile(), fake_session)
        with pytest.raises(AssertionError):
            api.run_case({"id": "C2", "url": "/x", "method": "get", "expected_code": 200})
        assert GlobalVar.get(CASE_STATUS_PREFIX + "C2") == "fail"

    def test_run_case_clears_hook_context_after_run(self, fake_session, capture_attach):
        """用例结束后必须清掉上下文，避免钩子读到上一条用例的数据。"""
        api = make_api(make_profile(), fake_session)
        api.run_case({"id": "C1", "url": "/x", "method": "get"})
        assert api._current_case is None

    def test_check_business_disabled_skips_business_assertion(self, fake_session, capture_attach):
        """令牌 / 文件下载 / 健康检查类接口不遵循业务码信封，可关掉业务断言。"""
        fake_session._default = FakeResponse(payload={"access_token": "AT-1"})
        api = make_api(make_profile(response={"style": "code", "success_values": "0"}),
                       fake_session)
        api.run_case({"url": "/oauth/token", "method": "post", "check_business": "0",
                      "expects": "exists:body.access_token"})

    def test_check_business_defaults_to_enabled(self, fake_session, capture_attach):
        """默认仍然做业务断言，避免「忘了写 expected_code 悄悄变绿」。"""
        fake_session._default = FakeResponse(payload={"msg": "响应里没有业务码"})
        api = make_api(make_profile(response={"style": "code", "success_values": "0"}),
                       fake_session)
        with pytest.raises(AssertionError):
            api.run_case({"url": "/x", "method": "get"})


class TestRunSteps:
    def test_json_string_list(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_steps('[{"url": "/a", "method": "get"}, {"url": "/b", "method": "post"}]')
        assert [call["method"] for call in fake_session.calls] == ["get", "post"]

    def test_json_string_single_dict(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_steps('{"url": "/a", "method": "get"}')
        assert fake_session.call_count == 1

    def test_single_dict(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_steps({"url": "/a", "method": "get"})
        assert fake_session.call_count == 1

    def test_shorthand_string(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_steps("post /v1/goods")
        assert fake_session.last_call["method"] == "post"
        assert fake_session.last_call["url"].endswith("/v1/goods")

    def test_unparsable_string_is_skipped(self, fake_session, capture_attach):
        """无法识别的步骤只告警并跳过，不能把整条用例拖挂。"""
        api = make_api(make_profile(), fake_session)
        assert api.run_steps("garbage") == []
        assert fake_session.call_count == 0

    def test_none_returns_empty(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        assert api.run_steps(None) == []
        assert api.run_steps([]) == []

    def test_step_headers_and_body(self, fake_session, capture_attach):
        api = make_api(make_profile(), fake_session)
        api.run_steps([{"url": "/a", "method": "post", "request_body": '{"a": 1}',
                        "headers": '{"X-T": "1"}'}])
        assert fake_session.last_call["kwargs"]["json"] == {"a": 1}
        assert fake_session.last_call["kwargs"]["headers"]["X-T"] == "1"


# ----------------------------------------------------------------------
# 9.8 分页抓取（中台 / 商城的列表接口）
# ----------------------------------------------------------------------
class TestPaginate:
    @staticmethod
    def _api(responses):
        session = FakeSession(responses=responses)
        profile = make_profile(env={"base_url": "http://h"},
                               response={"style": "code", "success_values": "0"})
        return make_api(profile, session), session

    def test_collects_until_page_smaller_than_size(self, capture_attach):
        api, session = self._api([
            FakeResponse(payload={"code": 0, "data": [{"id": i} for i in range(3)]}),
            FakeResponse(payload={"code": 0, "data": [{"id": 99}]}),
        ])
        items = api.paginate("/v1/list", size=3)
        assert [item["id"] for item in items] == [0, 1, 2, 99]
        assert session.call_count == 2
        assert session.calls[0]["kwargs"]["params"] == {"page": 1, "pageSize": 3}
        assert session.calls[1]["kwargs"]["params"] == {"page": 2, "pageSize": 3}

    def test_max_pages_safety_valve(self, capture_attach):
        """服务端不翻页时必须能自行停下，否则就是死循环。"""
        api, session = self._api([
            FakeResponse(payload={"code": 0, "data": [{"id": i} for i in range(5)]})
            for _ in range(10)
        ])
        items = api.paginate("/v1/list", size=5, max_pages=3)
        assert session.call_count == 3
        assert len(items) == 15

    def test_stop_callback_ends_early(self, capture_attach):
        api, session = self._api([
            FakeResponse(payload={"code": 0, "data": [{"id": 1}]}),
            FakeResponse(payload={"code": 0, "data": [{"id": 2}]}),
        ])
        items = api.paginate("/v1/list", size=1, max_pages=10,
                             stop=lambda page_items, res: page_items[0]["id"] == 1)
        assert [item["id"] for item in items] == [1]
        assert session.call_count == 1

    def test_custom_data_path(self, capture_attach):
        api, _ = self._api([
            FakeResponse(payload={"code": 0, "result": {"rows": [{"id": 7}]}}),
        ])
        assert api.paginate("/v1/list", size=10,
                            data_path="body.result.rows") == [{"id": 7}]

    def test_non_list_data_is_wrapped(self, capture_attach):
        api, _ = self._api([FakeResponse(payload={"code": 0, "data": {"id": 1}})])
        assert api.paginate("/v1/list", size=10) == [{"id": 1}]

    def test_missing_list_stops_quietly(self, capture_attach):
        api, _ = self._api([FakeResponse(payload={"code": 0})])
        assert api.paginate("/v1/list") == []

    def test_page_failure_raises_with_server_message(self, capture_attach):
        api, _ = self._api([FakeResponse(payload={"code": 500, "msg": "查询失败"})])
        with pytest.raises(AssertionError) as exc:
            api.paginate("/v1/list")
        assert "查询失败" in str(exc.value)

    def test_custom_page_and_size_field(self, capture_attach):
        """不同系统的分页字段名不同（pageNum / limit 等），由调用方指定。"""
        session = FakeSession(responses=[
            FakeResponse(payload={"code": 0, "data": [{"id": 1}]}),
            FakeResponse(payload={"code": 0, "data": []}),
        ])
        api = make_api(make_profile(response={"style": "code", "success_values": "0"}), session)
        items = api.paginate("/v1/list", page_field="pageNum", size_field="limit", size=1)
        assert items == [{"id": 1}]
        assert session.calls[0]["kwargs"]["params"] == {"pageNum": 1, "limit": 1}
        assert session.calls[1]["kwargs"]["params"] == {"pageNum": 2, "limit": 1}
