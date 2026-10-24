# -*- coding: utf-8 -*-
"""
单元测试：testcase/ 用例层（conftest 钩子 + 用例 id 生成 + SQL 驱动单条执行）
==========================================================================
用例层本身是「数据的组织者」，逻辑不多，但其中的钩子与执行细节直接决定：
    1. 只读运行（--collect-only）是否真的不产生副作用
    2. 结果是否正确回写
    3. SQL 驱动能否正常拿到接口对象与用例数据

本文件只做「结构级」验证，不发起真实请求。
"""
import importlib

import pytest

from common import profile
from config import settings
from tests.conftest import FakeDbMysql
from utils.readmysql import RdTestcase

import testcase.conftest as case_conftest


def _load_driver(name):
    """
    加载用例层驱动模块。

    驱动模块在导入时会读取运行时配置（冒烟模式会按 tags 过滤用例）；
    若过滤后没有任何用例，模块会按设计调用 pytest.skip(allow_module_level=True)，
    此时降级为 None，由相关测试跳过，而不是让整个测试文件报收集错误。
    """
    try:
        return importlib.import_module(name)
    except BaseException as exc:                       # noqa: BLE001 —— Skipped 不是 Exception 子类
        if type(exc).__name__ == "Skipped":
            return None
        raise


excel_driver = _load_driver("testcase.test_excel_driver")
yaml_driver = _load_driver("testcase.test_yaml_driver")
sql_driver = _load_driver("testcase.test_sql_driver")


# ======================================================================
# 一、conftest 钩子
# ======================================================================
class FakeOption:
    def __init__(self, allure_report_dir=None):
        self.allure_report_dir = allure_report_dir


class FakePytestConfig:
    def __init__(self, allure_report_dir=None):
        self.option = FakeOption(allure_report_dir)
        self.markers = []

    def addinivalue_line(self, name, value):
        self.markers.append((name, value))


class TestConftestHooks:
    def test_registers_all_markers(self):
        config = FakePytestConfig()
        case_conftest.pytest_configure(config)

        # addinivalue_line 的调用形式为 ("markers", "excel: 说明文字")
        assert {name for name, _ in config.markers} == {"markers"}
        registered = {value.split(":")[0].strip() for _, value in config.markers}
        assert registered == {"excel", "yaml", "mysql", "network", "smoke"}

    def test_fills_allure_dir_when_needed(self):
        settings.RunConfig.REPORT_TYPE = "allure"
        config = FakePytestConfig(allure_report_dir=None)
        case_conftest.pytest_configure(config)
        assert config.option.allure_report_dir == settings.ALLURE_RESULTS_DIR

    def test_keeps_user_specified_allure_dir(self):
        settings.RunConfig.REPORT_TYPE = "allure"
        config = FakePytestConfig(allure_report_dir="D:/custom/allure")
        case_conftest.pytest_configure(config)
        assert config.option.allure_report_dir == "D:/custom/allure"

    def test_no_allure_dir_when_report_disabled(self):
        settings.RunConfig.REPORT_TYPE = "none"
        config = FakePytestConfig(allure_report_dir=None)
        case_conftest.pytest_configure(config)
        assert config.option.allure_report_dir is None

    def test_unknown_system_profile_reported_as_usage_error(self):
        """
        档案名写错时应给出「清晰一句话 + 可用档案清单」，而不是 INTERNALERROR 堆栈。

        此前校验发生在 pytest_sessionstart 里，ConfigError 会冒成
        `INTERNALERROR> ... ConfigError`，看起来像框架崩了 —— 而真实原因
        只是 AMSAPI_SYSTEM 拼错了一个字母。
        """
        settings.RunConfig.SYSTEM = "no_such_system"
        profile.clear_cache()
        with pytest.raises(pytest.UsageError) as exc:
            case_conftest.pytest_configure(FakePytestConfig())
        text = str(exc.value)
        assert "no_such_system" in text
        assert "可用档案" in text
        assert "INTERNALERROR" not in text

    def test_sessionstart_writes_environment_when_allure(self, monkeypatch):
        settings.RunConfig.REPORT_TYPE = "allure"
        calls = []
        monkeypatch.setattr("utils.allureutil.write_environment",
                            lambda d, env: calls.append((d, env)))

        case_conftest.pytest_sessionstart(None)

        assert len(calls) == 1
        env = calls[0][1]
        # 项目名与标题来自 conf.ini [report]，断言取配置而非硬编码字面量
        assert env["项目"] == settings.ReportConfig.PROJECT
        assert env["报告标题"] == settings.ReportConfig.TITLE
        assert env["数据源"] == settings.RunConfig.DATA_SOURCE
        assert env["Allure可用"] in ("True", "False")

    def test_sessionstart_is_read_only_when_report_disabled(self, monkeypatch):
        """--report none / --collect-only 时不得写出任何文件。"""
        settings.RunConfig.REPORT_TYPE = "none"
        calls = []
        monkeypatch.setattr("utils.allureutil.write_environment",
                            lambda d, env: calls.append(d))

        case_conftest.pytest_sessionstart(None)
        assert calls == []

    def test_sessionstart_clears_global_var(self, monkeypatch):
        from common.variable import GlobalVar
        GlobalVar.set("dirty", 1)
        settings.RunConfig.REPORT_TYPE = "none"
        case_conftest.pytest_sessionstart(None)
        assert GlobalVar.all() == {}

    def test_sessionfinish_flushes_when_write_back(self, monkeypatch):
        settings.RunConfig.WRITE_BACK = True
        calls = []
        monkeypatch.setattr("utils.excelutil.ExcelUtil.flush",
                            classmethod(lambda cls: calls.append(1)))
        case_conftest.pytest_sessionfinish(None, 0)
        assert calls == [1]

    def test_sessionfinish_skips_flush_when_disabled(self, monkeypatch):
        settings.RunConfig.WRITE_BACK = False
        calls = []
        monkeypatch.setattr("utils.excelutil.ExcelUtil.flush",
                            classmethod(lambda cls: calls.append(1)))
        case_conftest.pytest_sessionfinish(None, 0)
        assert calls == []

    def test_api_client_fixture_returns_base_api(self):
        from api.base_api import BaseApi
        factory = getattr(case_conftest.api_client, "__wrapped__", None)
        assert factory is not None, "api_client 应是 pytest fixture"
        assert isinstance(factory(), BaseApi)


def _require_excel_drivers():
    """Excel / YAML 驱动在冒烟筛选无匹配用例时会整模块跳过，相关测试随之跳过。"""
    if excel_driver is None or yaml_driver is None:
        pytest.skip("用例层驱动在当前运行配置下整体跳过（冒烟筛选无匹配用例）")


# ======================================================================
# 二、用例 id 生成（报告与筛选可读性）
# ======================================================================
class TestCaseId:
    @pytest.fixture(autouse=True)
    def _check(self):
        _require_excel_drivers()

    def test_excel_case_id(self):
        assert excel_driver._case_id({"id": 3, "title": "权限查询"}) == "id3[权限查询]"

    def test_excel_case_id_missing_fields(self):
        assert excel_driver._case_id({}) == "idNone[None]"

    def test_yaml_case_id(self):
        assert yaml_driver._case_id({"id": 1001, "__source__": "login.yaml",
                                     "title": "登录系统"}) == "id1001[login.yaml::登录系统]"

    def test_yaml_case_id_defaults(self):
        assert yaml_driver._case_id({}) == "idNone[yaml::case]"

    def test_yaml_case_id_has_ascii_anchor(self):
        """
        用例 id 必须以 ASCII 的 `id<编号>` 开头。

        pytest 会把 nodeid 里的非 ASCII 字符转义成 \\uXXXX，中文关键字
        （`-k 登录`）匹配不到任何用例；带 ASCII 锚点后 `-k id1001` 可稳定筛选。
        """
        case_id = yaml_driver._case_id({"id": 1002, "title": "中文标题"})
        assert case_id.startswith("id1002[")
        assert case_id.isascii() or "id1002[" in case_id


class TestDriverMarkers:
    @pytest.fixture(autouse=True)
    def _check(self):
        _require_excel_drivers()

    @staticmethod
    def _marker_names(obj):
        """把类/模块上的 pytestmark（单个或列表）统一为名称集合。"""
        marks = getattr(obj, "pytestmark", [])
        if not isinstance(marks, (list, tuple)):
            marks = [marks]
        return {getattr(mark, "name", None) for mark in marks}

    def test_excel_class_marker(self):
        assert "excel" in self._marker_names(excel_driver.TestExcelDriver)

    def test_yaml_class_marker(self):
        assert "yaml" in self._marker_names(yaml_driver.TestYamlDriver)

    def test_sql_module_marker(self):
        assert self._marker_names(sql_driver) == {"mysql"}

    def test_sql_driver_exposes_single_entry(self):
        """SQL 驱动以单个入口方法批量执行，便于整体跳过与结果统计。"""
        methods = [name for name in vars(sql_driver.TestSqlDriver) if name.startswith("test_")]
        assert methods == ["test_api"]
        assert callable(sql_driver.TestSqlDriver.test_api)

    def test_sql_run_one_is_staticmethod(self):
        """_run_one 为静态方法，因此接口对象必须以参数传入（不能依赖 fixture）。"""
        assert isinstance(vars(sql_driver.TestSqlDriver)["_run_one"], staticmethod)

    def test_excel_cases_loaded_from_real_file(self):
        """模块级已加载真实用例，应至少有一条（isdel=1）。"""
        assert len(excel_driver.CASES) >= 1
        assert all(str(c["isdel"]).strip() == "1" for c in excel_driver.CASES)

    def test_yaml_cases_loaded_from_real_dir(self):
        assert len(yaml_driver.CASES) >= 1


# ======================================================================
# 三、SQL 驱动单条用例执行
# ======================================================================
class FakeApiClient:
    """接口对象替身：记录请求要素，返回预设响应。"""

    def __init__(self, payload=None):
        self.res = {"code": 200, "body": payload if payload is not None else {"status": 200}}
        self.requests = []
        self.relations = []

    def request(self, method, path, data=None, headers=None, cookies=None):
        self.requests.append({"method": method, "path": path, "data": data,
                              "headers": headers, "cookies": cookies})
        return self.res

    def extract(self, relation):
        self.relations.append(relation)

    def run_case(self, case):
        """
        与真实接口层同构的最简实现：请求 -> 关联 -> 业务断言。

        驱动的职责已收敛为「准备数据 + 报告 + 结果落库」，请求与断言都在这一层，
        因此替身也必须提供 run_case，并保留「断言失败即抛 AssertionError」的语义。
        """
        self.request(case.get("method"), case.get("url"),
                     data=case.get("request_body"), headers=case.get("headers"),
                     cookies=case.get("cookies"))
        self.extract(case.get("relation"))

        expected = case.get("expected_code")
        body = self.res.get("body")
        actual = body.get("status") if isinstance(body, dict) else None
        if expected is not None and actual != expected:
            raise AssertionError("业务状态码不符：期望 {}，实际 {}（响应体={}）".format(
                expected, actual, body))
        return self.res


@pytest.fixture
def repo():
    return RdTestcase(mysql=FakeDbMysql(), web="gov")


CASE = {
    "id": 12,
    "title": "权限查询",
    "url": "/admin/resource/authority",
    "method": "get",
    "port_num": 9050,
    "headers": '{"access-ticket": "${ticket}"}',
    "request_body": '{"appCode": "demo-app"}',
    "relation": "None",
    "expected_code": 200,
    "isdel": 1,
}


class TestSqlDriverRunOne:
    def test_success_writes_result(self, repo, monkeypatch):
        """修复点：api_client 必须以参数传入（原实现为 staticmethod，会 NameError）。"""
        settings.RunConfig.WRITE_BACK = True
        client = FakeApiClient()

        sql_driver.TestSqlDriver._run_one(CASE, repo, "http://192.0.2.10", client)

        assert client.requests[0]["path"] == \
            "http://192.0.2.10:9050/admin/resource/authority"
        assert client.requests[0]["method"] == "get"
        assert client.relations == ["None"]

        kind, sql, args = repo.mysql.sql_log[-1]
        assert kind == "execute"
        assert args[0] == "12" and args[3] == "True"

    def test_failure_still_writes_result(self, repo):
        settings.RunConfig.WRITE_BACK = True
        client = FakeApiClient(payload={"status": 500})

        with pytest.raises(AssertionError):
            sql_driver.TestSqlDriver._run_one(CASE, repo, "http://h", client)

        assert repo.mysql.sql_log[-1][2][3] == "False"      # 失败也要落库

    def test_write_back_disabled(self, repo):
        settings.RunConfig.WRITE_BACK = False
        client = FakeApiClient()
        sql_driver.TestSqlDriver._run_one(CASE, repo, "http://h", client)
        assert all(item[0] != "execute" for item in repo.mysql.sql_log)

    def test_absolute_url_not_prefix(self, repo):
        settings.RunConfig.WRITE_BACK = False
        case = dict(CASE, url="http://other:80/v1/x")
        client = FakeApiClient()
        sql_driver.TestSqlDriver._run_one(case, repo, "http://h", client)
        assert client.requests[0]["path"] == "http://other:80/v1/x"
