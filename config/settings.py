# -*- coding: utf-8 -*-
"""
配置中心
========
统一管理：项目路径、运行开关、环境信息、数据库、日志、报告、认证、CI 判定。

**本文件是「可配置」的落点：框架内不允许再出现硬编码的业务数据**
（地址、账号、密码、密钥、超时、格式、文件名等一律走这里或 conf.ini / 环境变量）。

优先级：环境变量（AMSAPI_*） > config/conf.ini > 本文件默认值
其它模块统一 `from config import settings` 使用，禁止再散落硬编码路径。

配置分组（与 conf.ini 的段一一对应）：
    RunConfig     运行开关         [env] [run]
    DB_CONFIG     MySQL 连接       [db]
    ReportConfig  报告标题/文件名  [report]
    LogConfig     日志级别/格式    [log]
    AuthConfig    OAuth2 取令牌    [auth]
    CIConfig      CI 环境判定      [ci]

CI/CD 说明：
    流水线中无需改动仓库内的配置文件，直接用 AMSAPI_* 环境变量覆盖即可，例如：
        AMSAPI_BASE_URL=https://api.example.com
        AMSAPI_SYSTEM=mall               选择系统适配档案（config/systems/mall.ini）
        AMSAPI_SMOKE=1
        AMSAPI_WRITE_BACK=false
    也可用 AMSAPI_CONF_FILE 指定另一份配置文件（如 config/conf.ci.ini）。

    如需在 CI 中使用另一套用例数据 / 另一批系统档案（不改动仓库文件）：
        AMSAPI_DATA_DIR / AMSAPI_CASES_DIR / AMSAPI_EXCEL_FILE / AMSAPI_SYSTEMS_DIR
        AMSAPI_LOG_DIR / AMSAPI_REPORT_DIR
    这些目录类配置在进程启动时读取，属于「启动前就要定好」的参数。
"""
import os
import configparser

# 环境变量前缀：所有可被覆盖的配置项均以该前缀暴露给 CI/CD
ENV_PREFIX = "AMSAPI_"

# 被 AMSAPI_* 环境变量显式覆盖过的配置项名（大写）。
# 用途：系统适配档案（config/systems/*.ini）里的超时、证书校验等是「系统默认值」，
# 但流水线上用环境变量临时注入的值应当优先级最高，故档案会查这个集合来让路。
ENV_OVERRIDES = set()

# --------------------------------------------------------------------------
# 一、目录 / 文件路径（唯一来源）
# --------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_DIR = os.path.join(BASE_DIR, "config")

# 运行期目录允许用 AMSAPI_* 环境变量整体重定向。
# 场景：CI 想用另一套用例数据/另一批系统档案跑，而不改动仓库内的文件；
# 或本地验证时把数据落到临时目录，避免污染 data/ 下的真实用例。
# 注意：这几项在模块导入时即读取（与 CONF_FILE 同理），因此必须在启动进程前设好。
_ENV = os.environ.get

DATA_DIR = _ENV(ENV_PREFIX + "DATA_DIR") or os.path.join(BASE_DIR, "data")
LOG_DIR = _ENV(ENV_PREFIX + "LOG_DIR") or os.path.join(BASE_DIR, "log")
REPORT_DIR = _ENV(ENV_PREFIX + "REPORT_DIR") or os.path.join(BASE_DIR, "report")

# 系统适配档案目录（一套框架适配多系统）
SYSTEMS_DIR = _ENV(ENV_PREFIX + "SYSTEMS_DIR") or os.path.join(CONFIG_DIR, "systems")
# YAML 用例目录
CASES_DIR = _ENV(ENV_PREFIX + "CASES_DIR") or os.path.join(DATA_DIR, "cases")
# Excel 用例文件
EXCEL_FILE = _ENV(ENV_PREFIX + "EXCEL_FILE") or os.path.join(DATA_DIR, "api_tables.xlsx")

# 主配置文件：可用 AMSAPI_CONF_FILE 指向另一份配置（CI/CD 常用）
CONF_FILE = os.environ.get(ENV_PREFIX + "CONF_FILE") or os.path.join(CONFIG_DIR, "conf.ini")

# Allure 报告目录：results 为原始数据，allure-report 为生成的 HTML
ALLURE_RESULTS_DIR = os.path.join(REPORT_DIR, "allure-results")
ALLURE_REPORT_DIR = os.path.join(REPORT_DIR, "allure-report")

# 确保运行期目录存在（Allure 目录按需创建，避免只读运行时产生空目录）
for _d in (LOG_DIR, REPORT_DIR, CASES_DIR, SYSTEMS_DIR):
    os.makedirs(_d, exist_ok=True)


# --------------------------------------------------------------------------
# 二、运行开关
# --------------------------------------------------------------------------
class RunConfig:
    """运行期开关。可被 conf.ini 的 [run] 段覆盖。"""

    # 数据源：excel | yaml | mysql | all
    #   excel / yaml / mysql  只运行该数据源的用例
    #   all                   同时运行 Excel 与 YAML 驱动（兼容早期行为）
    DATA_SOURCE = "excel"
    # Excel 用例所在 sheet
    SHEET_NAME = "test_case_list"
    # 是否把执行结果回写数据源（Excel 回写 / MySQL 插表）
    WRITE_BACK = True
    # 接口请求超时（秒）
    TIMEOUT = 10
    # 是否校验 https 证书
    VERIFY = False
    # 全局默认域名：用例 url 为相对路径（如 /v1/users/login）时自动拼接
    BASE_URL = ""
    # 执行环境标识，仅用于日志/报告展示
    ENV = "test"

    # 系统适配档案名（config/systems/<名>.ini）：一套框架适配多种 web 系统
    # default = 内置默认档案，行为与框架原始版本一致
    SYSTEM = "default"

    # MySQL 数据源：业务标识（对应 test_case_list.web）与配置环境（对应 test_config.environment）
    # 留空表示未配置；开源版本刻意不预置任何真实业务标识
    DB_WEB = ""
    DB_ENVIRONMENT = ""

    # 报告类型：allure | html | both | none
    REPORT_TYPE = "allure"

    # 冒烟模式：为 True 时只执行带指定标签的用例（CI/CD 构建后快速验证）
    SMOKE_ONLY = False
    # 冒烟标签：用例 tags 字段命中任意一个即参与冒烟执行
    TAGS = "smoke"


def resolve_db_web():
    """MySQL 数据源的 web 标识：优先取 conf.ini，缺省回退 RunConfig.DB_WEB。"""
    return RunConfig.DB_WEB


def resolve_db_environment():
    """MySQL 数据源的环境标识：优先取 conf.ini，缺省回退 RunConfig.DB_ENVIRONMENT。"""
    return RunConfig.DB_ENVIRONMENT


# --------------------------------------------------------------------------
# 数据源 -> 用例驱动 marker 的映射
# --------------------------------------------------------------------------
# 三个数据驱动各自打了 marker（见 testcase/test_*.py），用例层据此决定
# 按当前 data_source 加载哪一个：这样 `data_source = excel` 就真的只跑 Excel，
# 不会因为 data/ 下同时存在 YAML 示例而"顺手跑了一堆不该跑的用例"。
DATA_SOURCE_MARKERS = {"excel": "excel", "yaml": "yaml", "mysql": "mysql"}
# 「不限数据源」的特殊取值：Excel 与 YAML 都跑（对应框架早期行为）
DATA_SOURCE_ALL = "all"
VALID_DATA_SOURCES = ("excel", "yaml", "mysql", DATA_SOURCE_ALL)


def resolve_data_source():
    """规范化 data_source 取值（去空白 + 小写）。非法值原样返回，由调用方报错提示。"""
    return str(RunConfig.DATA_SOURCE or "").strip().lower()


def data_source_marker():
    """
    当前 data_source 对应的驱动 marker 名。

    :return: "excel" / "yaml" / "mysql"；取值为 all（或空）时返回 None，表示不做限制
    """
    source = resolve_data_source()
    if source in ("", DATA_SOURCE_ALL):
        return None
    return DATA_SOURCE_MARKERS.get(source)


# --------------------------------------------------------------------------
# 三、数据库配置（可选数据源，默认不启用）
# --------------------------------------------------------------------------
# 注意：这里**不预置任何真实账号密码**。默认值为空即代表「未配置 MySQL」，
# 框架不会去连库；使用 mysql 数据源时请在 conf.ini 的 [db] 段填写，
# 或用 AMSAPI_DB_* 环境变量注入（CI 推荐，避免把密码写进仓库）。
DB_CONFIG = {
    "host": "",
    "user": "",
    "password": "",
    "database": "",
    "port": 3306,          # MySQL 标准端口，非敏感默认值
    "charset": "utf8",
}

# 使用 mysql 数据源时必须配置的项（密码允许为空：部分内网库免密）
DB_REQUIRED_KEYS = ("host", "user", "database")


def missing_db_keys():
    """
    返回 DB_CONFIG 中尚未配置的必填项。

    用途：mysql 数据源在「没填连接信息」时应给出明确提示（甚至直接跳过），
    而不是让 pymysql 抛一串 "Can't connect to MySQL server on 'localhost'" 的栈 ——
    后者会让新人以为是框架出错了，实际只是没填配置。
    """
    return [key for key in DB_REQUIRED_KEYS
            if not str(DB_CONFIG.get(key) or "").strip()]


# --------------------------------------------------------------------------
# 四、日志 / 报告 / 认证 / CI 可配置项
# --------------------------------------------------------------------------
# 这些值原先硬编码在各自模块里（日志格式、附件截断长度、OAuth2 续期提前量、
# CI 环境变量清单……），改成集中配置后，调整行为无需再改源码。
# 对应 conf.ini 的 [log] / [report] / [auth] / [ci] 段，均可用 AMSAPI_* 覆盖。
class LogConfig:
    """日志相关配置（对应 conf.ini 的 [log] 段）。"""

    # 日志级别：DEBUG | INFO | WARNING | ERROR
    LEVEL = "DEBUG"
    # 控制台输出级别（CI 里通常调成 INFO 少刷屏）
    CONSOLE_LEVEL = "DEBUG"
    # 日志文件名（strftime 格式，按天滚动）
    FILE_NAME_FORMAT = "%Y_%m_%d"
    # 日志行格式与时间格式
    FORMAT = "%(asctime)s | %(levelname)-7s | %(filename)s:%(lineno)d | %(message)s"
    DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
    # logger 根名称
    ROOT_NAME = "amsapi"

    @classmethod
    def file_name(cls, when=None):
        """
        按文件名格式生成当天的日志文件名。

        :param when: 时间戳（time.struct_time 或 datetime），缺省取当前时间
        :return: 形如 2026_09_27.log 的文件名
        """
        import time as _time
        return "{}.log".format(_time.strftime(cls.FILE_NAME_FORMAT, when) if when
                               else _time.strftime(cls.FILE_NAME_FORMAT))


class ReportConfig:
    """报告相关配置（对应 conf.ini 的 [report] 段）。"""

    # 报告标题（Allure「环境」页 + pytest-html 标题）
    TITLE = "接口自动化测试"
    # 项目名（Allure「环境」页）
    PROJECT = "amsapi-auto"
    # pytest-html 报告文件名（生成在 REPORT_DIR 下）
    HTML_NAME = "report.html"
    # Allure 单条附件最大字符数（超出截断）
    MAX_ATTACH_LEN = 20000

    @classmethod
    def html_path(cls):
        """pytest-html 报告的完整路径。"""
        return os.path.join(REPORT_DIR, cls.HTML_NAME)


class AuthConfig:
    """认证相关配置（对应 conf.ini 的 [auth] 段）。用于 OAuth2 取令牌行为。"""

    # 令牌到期前多少秒提前续期
    REFRESH_AHEAD = 60
    # 取令牌请求超时（秒）
    TOKEN_TIMEOUT = 10
    # 取令牌时是否校验 https 证书
    TOKEN_VERIFY = False


class CIConfig:
    """CI 环境判定（对应 conf.ini 的 [ci] 段）。"""

    # 出现下列任一环境变量即认为运行在流水线中
    DETECT_ENV_VARS = ("JENKINS_URL", "JENKINS_HOME", "GITLAB_CI", "BUILD_NUMBER",
                       "GITHUB_ACTIONS", "TF_BUILD", "CI")


def _to_bool(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _load_conf_ini():
    """读取 conf.ini 并覆盖默认配置。文件不存在则静默跳过。"""
    if not os.path.exists(CONF_FILE):
        return
    cf = configparser.ConfigParser(interpolation=None)
    cf.read(CONF_FILE, encoding="utf-8")

    if cf.has_section("run"):
        sec = cf["run"]
        RunConfig.DATA_SOURCE = sec.get("data_source", RunConfig.DATA_SOURCE)
        RunConfig.SHEET_NAME = sec.get("sheet_name", RunConfig.SHEET_NAME)
        RunConfig.WRITE_BACK = _to_bool(sec.get("write_back", RunConfig.WRITE_BACK))
        RunConfig.TIMEOUT = int(sec.get("timeout", RunConfig.TIMEOUT))
        RunConfig.VERIFY = _to_bool(sec.get("verify", RunConfig.VERIFY))
        RunConfig.SMOKE_ONLY = _to_bool(sec.get("smoke", RunConfig.SMOKE_ONLY))
        RunConfig.TAGS = sec.get("tags", RunConfig.TAGS)

    if cf.has_section("env"):
        sec = cf["env"]
        RunConfig.ENV = sec.get("env", RunConfig.ENV)
        RunConfig.BASE_URL = sec.get("base_url", RunConfig.BASE_URL).strip()
        # 系统适配档案名：指定后框架按该档案的域名/认证/响应判定规则运行
        RunConfig.SYSTEM = sec.get("system", RunConfig.SYSTEM).strip() or "default"

    if cf.has_section("report"):
        sec = cf["report"]
        RunConfig.REPORT_TYPE = sec.get("report_type", RunConfig.REPORT_TYPE).strip().lower()
        ReportConfig.TITLE = sec.get("title", ReportConfig.TITLE).strip() or ReportConfig.TITLE
        ReportConfig.PROJECT = sec.get("project", ReportConfig.PROJECT).strip() or ReportConfig.PROJECT
        ReportConfig.HTML_NAME = sec.get("html_name", ReportConfig.HTML_NAME).strip() or ReportConfig.HTML_NAME
        ReportConfig.MAX_ATTACH_LEN = int(sec.get("max_attach_len", ReportConfig.MAX_ATTACH_LEN))

    if cf.has_section("log"):
        sec = cf["log"]
        LogConfig.LEVEL = sec.get("level", LogConfig.LEVEL).strip().upper() or LogConfig.LEVEL
        LogConfig.CONSOLE_LEVEL = sec.get(
            "console_level", LogConfig.CONSOLE_LEVEL).strip().upper() or LogConfig.CONSOLE_LEVEL
        LogConfig.FILE_NAME_FORMAT = sec.get("file_name_format", LogConfig.FILE_NAME_FORMAT)
        LogConfig.FORMAT = sec.get("format", LogConfig.FORMAT)
        LogConfig.DATE_FORMAT = sec.get("date_format", LogConfig.DATE_FORMAT)
        LogConfig.ROOT_NAME = sec.get("root_name", LogConfig.ROOT_NAME).strip() or LogConfig.ROOT_NAME

    if cf.has_section("auth"):
        sec = cf["auth"]
        AuthConfig.REFRESH_AHEAD = int(sec.get("refresh_ahead", AuthConfig.REFRESH_AHEAD))
        AuthConfig.TOKEN_TIMEOUT = int(sec.get("token_timeout", AuthConfig.TOKEN_TIMEOUT))
        AuthConfig.TOKEN_VERIFY = _to_bool(sec.get("token_verify", AuthConfig.TOKEN_VERIFY))

    if cf.has_section("ci"):
        raw_vars = cf["ci"].get("detect_env_vars")
        if raw_vars is not None:
            CIConfig.DETECT_ENV_VARS = tuple(
                item.strip() for item in raw_vars.split(",") if item.strip())

    if cf.has_section("db"):
        sec = cf["db"]
        for key in DB_CONFIG:
            if sec.get(key) is not None:
                DB_CONFIG[key] = int(sec.get(key)) if key == "port" else sec.get(key)
        # MySQL 数据源的业务标识与环境标识
        RunConfig.DB_WEB = sec.get("web", RunConfig.DB_WEB)
        RunConfig.DB_ENVIRONMENT = sec.get("environment", RunConfig.DB_ENVIRONMENT)


def _load_env():
    """
    读取 AMSAPI_* 环境变量并覆盖配置（最高优先级）。

    这是 CI/CD 接入的关键：流水线无需修改仓库里的 conf.ini，
    只需注入环境变量即可切换域名、数据源、是否回写、是否冒烟等。

    支持的变量：
        AMSAPI_ENV              环境标识
        AMSAPI_BASE_URL         全局域名
        AMSAPI_SYSTEM           系统适配档案名（config/systems/<名>.ini）
        AMSAPI_DATA_SOURCE      excel | yaml | mysql
        AMSAPI_SHEET_NAME       Excel sheet 名
        AMSAPI_WRITE_BACK       是否回写结果（true/false）
        AMSAPI_TIMEOUT          请求超时（秒）
        AMSAPI_VERIFY           是否校验 https 证书
        AMSAPI_REPORT_TYPE      allure | html | both | none
        AMSAPI_WEB              MySQL 业务标识
        AMSAPI_DB_ENVIRONMENT   MySQL 配置环境
        AMSAPI_DB_HOST / AMSAPI_DB_PORT / AMSAPI_DB_USER
        AMSAPI_DB_PASSWORD / AMSAPI_DB_NAME / AMSAPI_DB_CHARSET
        AMSAPI_SMOKE            是否只跑冒烟用例（true/false）
        AMSAPI_TAGS             冒烟标签，逗号分隔
        AMSAPI_LOG_LEVEL        日志级别（DEBUG|INFO|WARNING|ERROR）
        AMSAPI_LOG_CONSOLE_LEVEL 控制台日志级别
        AMSAPI_REPORT_TITLE     报告标题
        AMSAPI_REPORT_PROJECT   报告项目名
        AMSAPI_ALLURE_MAX_ATTACH_LEN Allure 单条附件最大字符数
        AMSAPI_OAUTH2_REFRESH_AHEAD  OAuth2 令牌提前续期秒数
        AMSAPI_OAUTH2_TOKEN_TIMEOUT  OAuth2 取令牌超时（秒）
        AMSAPI_RENDER_ALLURE    置 1 时在 CI 中也强制渲染本地 HTML 报告
        AMSAPI_CONF_FILE        指定另一份配置文件（在模块顶部已生效）
    """
    def _raw(name):
        """取环境变量值；未设置或为空串时返回 None（空串不覆盖）。"""
        value = os.environ.get(ENV_PREFIX + name)
        if value is None or str(value).strip() == "":
            return None
        return value

    # (环境变量名, RunConfig 属性, 类型转换)
    run_items = [
        ("ENV", "ENV", None),
        ("BASE_URL", "BASE_URL", None),
        ("SYSTEM", "SYSTEM", None),
        ("DATA_SOURCE", "DATA_SOURCE", None),
        ("SHEET_NAME", "SHEET_NAME", None),
        ("WRITE_BACK", "WRITE_BACK", _to_bool),
        ("TIMEOUT", "TIMEOUT", int),
        ("VERIFY", "VERIFY", _to_bool),
        ("REPORT_TYPE", "REPORT_TYPE", None),
        ("WEB", "DB_WEB", None),
        ("DB_ENVIRONMENT", "DB_ENVIRONMENT", None),
        ("SMOKE", "SMOKE_ONLY", _to_bool),
        ("TAGS", "TAGS", None),
    ]
    for env_name, attr, cast in run_items:
        raw = _raw(env_name)
        if raw is not None:
            setattr(RunConfig, attr, cast(raw) if cast else raw)
            ENV_OVERRIDES.add(env_name)

    # 日志 / 报告 / 认证：同样支持环境变量覆盖（CI 里常用于调级别、改标题）
    # (环境变量名, 目标类, 属性名, 类型转换)
    group_items = [
        ("LOG_LEVEL", LogConfig, "LEVEL", lambda v: v.strip().upper()),
        ("LOG_CONSOLE_LEVEL", LogConfig, "CONSOLE_LEVEL", lambda v: v.strip().upper()),
        ("LOG_ROOT_NAME", LogConfig, "ROOT_NAME", None),
        ("REPORT_TITLE", ReportConfig, "TITLE", None),
        ("REPORT_PROJECT", ReportConfig, "PROJECT", None),
        ("REPORT_HTML_NAME", ReportConfig, "HTML_NAME", None),
        ("ALLURE_MAX_ATTACH_LEN", ReportConfig, "MAX_ATTACH_LEN", int),
        ("OAUTH2_REFRESH_AHEAD", AuthConfig, "REFRESH_AHEAD", int),
        ("OAUTH2_TOKEN_TIMEOUT", AuthConfig, "TOKEN_TIMEOUT", int),
        ("OAUTH2_TOKEN_VERIFY", AuthConfig, "TOKEN_VERIFY", _to_bool),
    ]
    for env_name, holder, attr, cast in group_items:
        raw = _raw(env_name)
        if raw is not None:
            setattr(holder, attr, cast(raw) if cast else raw)

    # 数据库连接参数
    db_items = {
        "DB_HOST": "host",
        "DB_PORT": "port",
        "DB_USER": "user",
        "DB_PASSWORD": "password",
        "DB_NAME": "database",
        "DB_CHARSET": "charset",
    }
    for env_name, key in db_items.items():
        raw = _raw(env_name)
        if raw is not None:
            DB_CONFIG[key] = int(raw) if key == "port" else raw

    # 报告类型统一小写，避免 CI 中大小写不一致
    RunConfig.REPORT_TYPE = str(RunConfig.REPORT_TYPE).strip().lower()


_load_conf_ini()
_load_env()


# --------------------------------------------------------------------------
# 四、兼容旧接口（历史代码使用 get_log_path() 等函数）
# --------------------------------------------------------------------------
def get_log_path():
    return LOG_DIR


def get_report_path():
    return REPORT_DIR


def get_conf_path():
    return CONFIG_DIR


def get_data_path():
    return DATA_DIR


if __name__ == "__main__":
    print("BASE_DIR     =", BASE_DIR)
    print("EXCEL_FILE   =", EXCEL_FILE)
    print("DATA_SOURCE  =", RunConfig.DATA_SOURCE)
    print("BASE_URL     =", RunConfig.BASE_URL or "(未配置)")
    print("SYSTEM       =", RunConfig.SYSTEM)
    print("LOG_LEVEL    =", LogConfig.LEVEL)
    print("REPORT_TITLE =", ReportConfig.TITLE)
    print("HTML_REPORT  =", ReportConfig.html_path())
    print("CI 判定变量  =", ", ".join(CIConfig.DETECT_ENV_VARS))
    print("DB_CONFIG    =", DB_CONFIG)
