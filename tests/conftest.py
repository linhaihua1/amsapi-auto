# -*- coding: utf-8 -*-
"""
单元测试公共配置（tests/）
=========================
本目录是「框架自身的单元测试」，与 testcase/（业务接口用例）职责完全不同：

    testcase/   被测对象是**本框架所测的业务系统**，需要真实环境（内网服务）
    tests/      被测对象是**本框架自身的代码**，全部离线运行，不依赖任何外部服务

三条铁律：
    1. 绝不改动 data/ 下的真实数据文件——Excel 相关用例一律在 tmp_path 中生成副本
    2. 每个用例前后清空全局变量池、Excel 工作簿缓存，并恢复运行配置快照
    3. 网络请求全部用替身（FakeSession）拦截，不发起任何真实 HTTP

运行方式：
    pytest tests                # 只跑框架单元测试
    pytest tests -q             # 简洁输出
    pytest tests --cov --cov-report=term-missing   # 带覆盖率
"""
import os
import sys
import tempfile

import openpyxl
import pytest

# 让测试可以直接 import 项目模块（不依赖 pytest 的 rootdir 推断）
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS_DIR = os.path.join(ROOT_DIR, "tools")
for _path in (TOOLS_DIR, ROOT_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

# ----------------------------------------------------------------------
# 单测必须「可复现」且「零污染」：摘除外部注入的 AMSAPI_* 环境变量
# ----------------------------------------------------------------------
# 背景：CI/CD 流水线按框架约定会注入 AMSAPI_BASE_URL / AMSAPI_SYSTEM / AMSAPI_DATA_DIR 等
# 变量（见 docs/06-CICD集成.md）。但 tests/ 断言的是**框架自身行为**，
# 若被这些变量串掉就会出现「本地全绿、流水线红一片」：
#     AMSAPI_BASE_URL=...  -> 串掉域名解析与档案 describe 的断言
#     AMSAPI_DATA_DIR=...  -> 串掉「默认用例目录」断言
# 因此这里在导入 config.settings 之前把它们全部摘掉（settings 的路径常量在导入时即定型，
# 晚于此处的清理不会有任何效果），会话结束后再原样恢复。
#
# 例外：日志与报告目录**主动改到临时目录**，让单测产物不落进仓库的 log/ 与 report/。
# 这两项只影响「文件写到哪」，不参与任何业务断言，因此不会破坏可复现性。
_ENV_BACKUP = {key: value for key, value in os.environ.items()
               if key.startswith("AMSAPI_")}
for _key in list(_ENV_BACKUP):
    os.environ.pop(_key)

_ARTIFACT_SANDBOX = os.path.join(tempfile.gettempdir(), "amsapi-unittest-artifacts")
os.environ["AMSAPI_LOG_DIR"] = os.path.join(_ARTIFACT_SANDBOX, "log")
os.environ["AMSAPI_REPORT_DIR"] = os.path.join(_ARTIFACT_SANDBOX, "report")

from config import settings                          # noqa: E402
from common import profile                           # noqa: E402
from common.variable import GlobalVar                # noqa: E402
from utils.excelutil import ExcelUtil                # noqa: E402


# ======================================================================
# 一、替身对象（在测试文件里按需 import 使用）
# ======================================================================
class FakeCookieJar:
    """requests 的 cookie 容器替身。"""

    def __init__(self, data=None):
        self._data = dict(data or {})

    def get_dict(self):
        return dict(self._data)


class FakeResponse:
    """
    requests.Response 的最小替身，只保留框架真正会用到的属性。

    :param payload:  json() 的返回值
    :param json_error: 为 True 时 json() 抛 ValueError（模拟非 JSON 响应）
    """

    def __init__(self, status_code=200, payload=None, text=None, headers=None,
                 cookies=None, url="http://127.0.0.1/mock", reason="OK",
                 json_error=False):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else ("" if payload is None else str(payload))
        self.headers = headers if headers is not None else {"Content-Type": "application/json"}
        self._cookies = dict(cookies or {})
        self.url = url
        self.reason = reason
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("Expecting value: line 1 column 1 (char 0)")
        return self._payload

    @property
    def cookies(self):
        return FakeCookieJar(self._cookies)


class FakeSession:
    """
    requests.Session 的替身：记录每次调用，返回预设响应（或抛出预设异常）。

    用法：
        session = FakeSession(FakeResponse(payload={"status": 200}))
        api = BaseApi(base_url="http://x", session=session)
    """

    def __init__(self, response=None, responses=None):
        self.calls = []
        self._default = response
        self._queue = list(responses or [])

    def request(self, method=None, url=None, **kwargs):
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        item = self._queue.pop(0) if self._queue else self._default
        if isinstance(item, Exception):
            raise item
        return item if item is not None else FakeResponse()

    # ---- 便捷访问 ----
    @property
    def last_call(self):
        return self.calls[-1]

    @property
    def call_count(self):
        return len(self.calls)


class FakePymysql:
    """pymysql 模块替身（用于 MySQL 工具层离线测试）。"""

    class cursors:
        DictCursor = "DictCursor"

    def __init__(self, fetchone=None, fetchall=None, execute_result=1,
                 execute_error=None, open_state=True):
        self.conn = FakeConnection(self, fetchone, fetchall, execute_result,
                                   execute_error, open_state)
        self.connect_args = None

    def connect(self, **kwargs):
        self.connect_args = kwargs
        return self.conn


class FakeConnection:
    def __init__(self, owner, fetchone, fetchall, execute_result, execute_error, open_state):
        self.owner = owner
        self._fetchone = fetchone
        self._fetchall = fetchall
        self._execute_result = execute_result
        self._execute_error = execute_error
        self.open = open_state
        self.committed = 0
        self.rolled_back = 0
        self.closed = False

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.committed += 1

    def rollback(self):
        self.rolled_back += 1

    def close(self):
        self.closed = True
        self.open = False


class FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.executed = []
        self.closed = False

    def execute(self, sql, args=None):
        self.executed.append((sql, args))
        if self._conn._execute_error is not None:
            raise self._conn._execute_error
        return self._conn._execute_result

    def fetchone(self):
        return self._conn._fetchone

    def fetchall(self):
        return self._conn._fetchall or []

    def close(self):
        self.closed = True


class FakeDbMysql:
    """
    数据访问层（RdTestcase）用的 MySQL 替身：只记录 SQL 与参数，返回预设结果。
    """

    def __init__(self, fetchall_result=None, fetchone_result=None, execute_result=1):
        self.sql_log = []
        self.fetchall_result = fetchall_result if fetchall_result is not None else []
        self.fetchone_result = fetchone_result
        self.execute_result = execute_result

    def get_fetchall(self, sql, args=None):
        self.sql_log.append(("fetchall", sql, args))
        return self.fetchall_result

    def get_fetchone(self, sql, args=None):
        self.sql_log.append(("fetchone", sql, args))
        return self.fetchone_result

    def sql_execute(self, sql, args=None):
        self.sql_log.append(("execute", sql, args))
        return self.execute_result


# ======================================================================
# 二、pytest 会话钩子
# ======================================================================
def pytest_unconfigure(config):
    """
    会话结束后恢复环境：把临时摘除 / 改写的 AMSAPI_* 变量还原回去。

    同一进程内往往还会做别的事（例如测试内联启动 mock 服务后复用配置），
    若不复原，会让「单测结束后的环境」与「单测开始前」不一致，难以排查。
    """
    os.environ.pop("AMSAPI_LOG_DIR", None)
    os.environ.pop("AMSAPI_REPORT_DIR", None)
    os.environ.update(_ENV_BACKUP)


def pytest_configure(config):
    """
    注册业务用例使用的自定义 marker。

    单元测试会话不会加载 testcase/conftest.py，若不在此注册，
    导入用例层模块时会刷出 PytestUnknownMarkWarning。
    """
    for line in ("excel: Excel 数据驱动用例",
                 "yaml: YAML 数据驱动用例",
                 "mysql: MySQL 数据驱动用例",
                 "network: 依赖真实服务环境的用例",
                 "smoke: 冒烟用例（CI/CD 构建后快速验证）"):
        config.addinivalue_line("markers", line)


# 单元测试层必须完全离线，这两个标记代表「依赖真实服务 / 真实数据库」。
# 它们属于 testcase/ 的业务用例，一旦出现在 tests/ 下即视为误放。
FORBIDDEN_MARKS = ("network", "mysql")


def pytest_collection_modifyitems(config, items):
    """
    守住「tests/ 必须全离线」这条底线。

    背景：testcase/ 的用例可以打 network / mysql 标记（它们本来就要连内网），
    但 tests/ 是框架自测层，必须能在**无网络、无数据库**的机器上全绿——
    否则 CI 流水线里「框架单元测试」这道最早的门就会莫名红一片。

    若有人把依赖真实环境的用例误放进 tests/，这里在**收集阶段**直接失败，
    并给出明确的迁移提示，而不是等到跑起来才报一连串 ConnectionError。

    作用域：本钩子定义在 tests/conftest.py，仅对 tests/ 目录下的用例生效，
    不会干扰 testcase/ 业务用例的正常标记与筛选。
    """
    misplaced = []
    for item in items:
        for mark in FORBIDDEN_MARKS:
            if item.get_closest_marker(mark) is not None:
                misplaced.append((item.nodeid, mark))
                break

    if misplaced:
        lines = ["tests/ 目录下不允许出现依赖真实环境的用例（tests/ 必须能离线全绿）："]
        lines.extend("    [x] {}   -> 标记 '{}'".format(nodeid, mark)
                     for nodeid, mark in misplaced)
        lines.append("")
        lines.append("请把这类用例移到 testcase/ 目录，或去掉该标记。")
        lines.append("理由与分工说明见 docs/07-单元测试.md 第一节。")
        raise pytest.UsageError("\n".join(lines))


# ======================================================================
# 三、状态隔离（自动生效）
# ======================================================================
@pytest.fixture(autouse=True)
def isolate_state():
    """
    每个用例前后清理全局状态：

        GlobalVar         接口间的参数关联变量
        ExcelUtil         工作簿缓存与脏标记
        SystemProfile     系统适配档案缓存（档案名受 RunConfig.SYSTEM 影响，必须隔离）
        RunConfig / DB_CONFIG   运行配置快照，避免用例改配置后互相影响
        LogConfig / ReportConfig / AuthConfig / CIConfig / MaskConfig / NetworkConfig
                          其余可配分组，同样需要快照
        ENV_OVERRIDES     被 AMSAPI_* 环境变量显式覆盖的项集合

    关于 ENV_OVERRIDES：它由 settings._load_env() 写入，语义是「哪些项被环境变量覆盖过」，
    直接决定档案取超时/证书校验时的优先级。测试里 monkeypatch.setenv + _load_env()
    能撤销环境变量，却撤不掉这个集合里的记录 —— 于是「超时被环境变量覆盖」的状态会
    泄漏给后续用例，表现为档案里明明写了 timeout = 25，读出来却是 conf.ini 的默认值。
    因此这里必须连它一起快照还原。
    """
    config_holders = (settings.RunConfig, settings.LogConfig,
                      settings.ReportConfig, settings.AuthConfig, settings.CIConfig,
                      settings.MaskConfig, settings.NetworkConfig)
    config_snapshots = [
        (holder, {key: value for key, value in vars(holder).items()
                  if not key.startswith("__") and not callable(value)})
        for holder in config_holders
    ]
    db_snapshot = dict(settings.DB_CONFIG)
    env_overrides_snapshot = set(settings.ENV_OVERRIDES)

    GlobalVar.clear()
    ExcelUtil._cache.clear()
    ExcelUtil._dirty.clear()
    profile.clear_cache()

    yield

    GlobalVar.clear()
    ExcelUtil._cache.clear()
    ExcelUtil._dirty.clear()
    profile.clear_cache()

    for holder, snapshot in config_snapshots:
        for key, value in snapshot.items():
            setattr(holder, key, value)
    settings.DB_CONFIG.clear()
    settings.DB_CONFIG.update(db_snapshot)
    settings.ENV_OVERRIDES.clear()
    settings.ENV_OVERRIDES.update(env_overrides_snapshot)


# ======================================================================
# 四、公共 fixture
# ======================================================================
@pytest.fixture
def fake_session():
    """默认返回一个 200 + {"status": 200} 的会话替身。"""
    return FakeSession(FakeResponse(payload={"status": 200}))


@pytest.fixture
def excel_file(tmp_path):
    """
    在临时目录生成一份结构完整的 Excel 用例表（含 3 个 sheet），返回文件路径。

    数据设计（行号为物理行号，用于验证结果回写）：
        行2  id=1 isdel=1 tags=smoke              -> 可执行，命中毒冒烟标签
        行3  id=2 isdel=0 tags=（空）              -> 不可执行
        行4  全空行                                 -> 应被跳过
        行5  id=3 isdel=1 tags=smoke,core          -> 可执行，多标签
        行6  id=4 isdel=1 tags=regression          -> 可执行，非冒烟
    """
    path = tmp_path / "cases_sample.xlsx"
    wb = openpyxl.Workbook()

    ws = wb.active
    ws.title = "test_case_list"
    ws.append(["id", "time", "title", "url", "method", "headers", "cookies",
               "request_body", "request_type", "relation", "expected_code",
               "response", "ispass", "isdel", "tags"])
    ws.append([1, None, "登录系统", "/v1/users/login", "get",
               '{"Content-Type": "application/json"}', "{}",
               '{"username": "demo_user"}', None, "ticket=body.data.ticket",
               200, None, None, 1, "smoke"])
    ws.append([2, None, "已停用的用例", "/v1/old", "get", "{}", "{}", "{}",
               None, "None", 200, None, None, 0, None])
    ws.append([None] * 15)                                    # 全空行
    ws.append([3, None, "权限查询", "/admin/resource/authority", "get",
               '{"access-ticket": "${ticket}"}', "{}",
               '{"appCode": "demo-app"}', None, "None", 200, None, None, 1,
               "smoke,core"])
    ws.append([4, None, "字典查询", "/dicts", "get", "{}", "{}",
               '{"id": "demo-type"}', None, "None", 200, None, None, 1,
               "regression"])

    config = wb.create_sheet("test_config")
    config.append(["id", "web", "key", "value"])
    config.append([1, "gov", "domain", "http://192.0.2.10"])
    config.append([2, "other", "domain", "http://10.0.0.1"])

    record = wb.create_sheet("test_result_record")
    record.append(["id", "case_id", "times", "response", "result"])
    record.append([1, "1", "2026-01-01 00:00:00", "{}", "True"])

    wb.save(str(path))
    return str(path)


@pytest.fixture
def yaml_dir(tmp_path):
    """生成一个 YAML 用例目录，覆盖「cases 键 / 裸列表 / 非法项 / 非 yaml 文件」。"""
    (tmp_path / "a-login.yaml").write_text(
        "cases:\n"
        "  - title: 登录系统\n"
        "    url: /v1/users/login\n"
        "    method: get\n"
        "    tags: [smoke]\n"
        "    relation: ticket=body.data.ticket\n"
        "    expected_code: 200\n",
        encoding="utf-8")
    (tmp_path / "b-other.yml").write_text(
        "- title: 字典查询\n"
        "  url: /dicts\n"
        "  method: get\n"
        "  tags: [regression]\n"
        "  isdel: 0\n"
        "  expected_code: 200\n"
        "- 这不是字典\n",
        encoding="utf-8")
    (tmp_path / "ignore.txt").write_text("not a yaml", encoding="utf-8")
    (tmp_path / "empty.yaml").write_text("", encoding="utf-8")
    return str(tmp_path)
