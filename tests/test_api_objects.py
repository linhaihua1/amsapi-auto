# -*- coding: utf-8 -*-
"""
单元测试：api/ 下各业务接口对象（PO 风格封装）
==============================================
验证接口对象是否把「路径、参数、请求头」正确组装后交给 HTTP 层。
这是 PO 模式的价值所在：用例层只看方法名，不看 URL 与参数细节。
"""
import pytest

from api.admin_api import AdminApi
from api.base_api import BaseApi
from api.dict_api import DictApi
from api.login_api import LoginApi
from common.variable import GlobalVar
from tests.conftest import FakeResponse, FakeSession


@pytest.fixture(autouse=True)
def _silence_attach(monkeypatch):
    """拦截 Allure 附件，避免单元测试产生报告文件。"""
    monkeypatch.setattr("utils.allureutil.attach_request", lambda *a, **k: None)
    monkeypatch.setattr("utils.allureutil.attach_response", lambda *a, **k: None)


@pytest.fixture
def session():
    return FakeSession(FakeResponse(payload={"status": 200,
                                             "data": {"ticket": "TK-1"}}))


# ======================================================================
# 一、LoginApi
# ======================================================================
class TestLoginApi:
    def test_login_request(self, session):
        LoginApi(base_url="http://h", session=session).login("demo_user", "pwd")
        call = session.last_call
        assert call["url"] == "http://h/v1/users/login"
        assert call["method"] == "get"
        assert call["kwargs"]["params"] == {"username": "demo_user", "password": "pwd"}

    def test_login_with_sign(self, session):
        LoginApi(base_url="http://h", session=session).login("u", "p", sign="s")
        assert session.last_call["kwargs"]["params"]["sign"] == "s"

    def test_login_without_sign_omits_key(self, session):
        LoginApi(base_url="http://h", session=session).login("u", "p")
        assert "sign" not in session.last_call["kwargs"]["params"]

    def test_login_extra_params(self, session):
        LoginApi(base_url="http://h", session=session).login("u", "p", captcha="1234")
        assert session.last_call["kwargs"]["params"]["captcha"] == "1234"

    def test_login_and_save_ticket(self, session):
        ticket = LoginApi(base_url="http://h", session=session) \
            .login_and_save_ticket("u", "p")
        assert ticket == "TK-1"
        assert GlobalVar.get("ticket") == "TK-1"

    def test_login_and_save_ticket_asserts_business_code(self, session):
        """业务码不是 200 时应断言失败，不写入变量池。"""
        session._default = FakeResponse(payload={"status": 500})
        api = LoginApi(base_url="http://h", session=session)
        with pytest.raises(AssertionError):
            api.login_and_save_ticket("u", "p")
        assert GlobalVar.get("ticket") is None


# ======================================================================
# 二、DictApi
# ======================================================================
class TestDictApi:
    def test_get_dicts(self, session):
        DictApi(base_url="http://h", session=session).get_dicts(id="demo-type")
        call = session.last_call
        assert call["url"] == "http://h/dicts"
        assert call["kwargs"]["params"] == {"id": "demo-type"}

    def test_get_dicts_without_params(self, session):
        DictApi(base_url="http://h", session=session).get_dicts()
        assert session.last_call["url"] == "http://h/dicts"

    def test_get_dict_by_id(self, session):
        DictApi(base_url="http://h", session=session).get_dict_by_id(
            "demo-type", sys_code="demo-admin")
        assert session.last_call["kwargs"]["params"] == {
            "id": "demo-type", "sysCode": "demo-admin"}

    def test_get_dict_by_id_without_sys_code(self, session):
        DictApi(base_url="http://h", session=session).get_dict_by_id("x")
        assert "sysCode" not in session.last_call["kwargs"]["params"]

    def test_get_dict_rows(self, session):
        session._default = FakeResponse(payload={"status": 200,
                                                 "rows": [{"id": 1}]})
        assert DictApi(base_url="http://h", session=session).get_dict_rows() == [{"id": 1}]

    def test_get_dict_rows_when_no_rows(self, session):
        session._default = FakeResponse(payload={"status": 200})
        assert DictApi(base_url="http://h", session=session).get_dict_rows() == []

    def test_get_dict_rows_when_body_not_dict(self, session):
        session._default = FakeResponse(payload="plain text", json_error=True)
        assert DictApi(base_url="http://h", session=session).get_dict_rows() == []


# ======================================================================
# 三、AdminApi
# ======================================================================
class TestAdminApi:
    def test_get_authority(self, session):
        AdminApi(base_url="http://h", session=session).get_authority("demo-app")
        call = session.last_call
        assert call["url"] == "http://h/admin/resource/authority"
        assert call["kwargs"]["params"] == {"appCode": "demo-app", "type": "btn"}

    def test_get_authority_custom_type(self, session):
        AdminApi(base_url="http://h", session=session).get_authority("demo-app", type_="menu")
        assert session.last_call["kwargs"]["params"]["type"] == "menu"

    def test_get_authority_headers(self, session):
        AdminApi(base_url="http://h", session=session).get_authority(
            "demo-app", headers={"access-ticket": "T"})
        assert session.last_call["kwargs"]["headers"] == {"access-ticket": "T"}

    def test_get_authority_with_ticket_injects_header(self, session):
        GlobalVar.set("ticket", "T-777")
        AdminApi(base_url="http://h", session=session).get_authority_with_ticket("demo-app")
        assert session.last_call["kwargs"]["headers"] == {"access-ticket": "T-777"}

    def test_get_authority_with_ticket_and_username(self, session):
        GlobalVar.set("ticket", "T-777")
        AdminApi(base_url="http://h", session=session).get_authority_with_ticket(
            "demo-app", username="demo_user")
        assert session.last_call["kwargs"]["headers"] == {
            "access-ticket": "T-777", "username": "demo_user"}

    def test_get_authority_without_ticket(self, session):
        """变量池没有 ticket 时，请求头值为 None（由服务端返回鉴权失败）。"""
        AdminApi(base_url="http://h", session=session).get_authority_with_ticket("demo-app")
        assert session.last_call["kwargs"]["headers"] == {"access-ticket": None}

    def test_get_org_tree_page(self, session):
        AdminApi(base_url="http://h", session=session).get_org_tree_page("demo-org", page=2, size=50)
        call = session.last_call
        assert call["url"] == "http://h/admin/org/getTreeRootParentCodePage"
        assert call["kwargs"]["params"] == {"page": 2, "size": 50, "code": "demo-org"}

    def test_get_org_tree_default_paging(self, session):
        AdminApi(base_url="http://h", session=session).get_org_tree_page("demo-org")
        assert session.last_call["kwargs"]["params"] == {"page": 1, "size": 20, "code": "demo-org"}

    def test_get_org_rows(self, session):
        session._default = FakeResponse(payload={"status": 200, "rows": [{"code": "demo-org"}]})
        assert AdminApi(base_url="http://h", session=session).get_org_rows("demo-org") == \
            [{"code": "demo-org"}]

    def test_get_org_rows_empty(self, session):
        session._default = FakeResponse(payload={"status": 200})
        assert AdminApi(base_url="http://h", session=session).get_org_rows("demo-org") == []


# ======================================================================
# 四、继承关系与公共能力
# ======================================================================
class TestInheritance:
    @pytest.mark.parametrize("cls", [LoginApi, DictApi, AdminApi])
    def test_inherits_base_api(self, cls):
        assert issubclass(cls, BaseApi)

    @pytest.mark.parametrize("cls", [LoginApi, DictApi, AdminApi])
    def test_has_common_helpers(self, cls):
        instance = cls(base_url="http://h")
        for method in ("request", "extract", "check_status", "check_business_code",
                       "check_json", "run_case"):
            assert callable(getattr(instance, method))
