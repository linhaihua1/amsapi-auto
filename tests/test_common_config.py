# -*- coding: utf-8 -*-
"""
单元测试：配置层（config/settings.py、common/read_config.py、common/project_path.py）
=====================================================================================
覆盖：
    1. 路径常量与实际目录一致性（避免文档/代码路径漂移）
    2. 运行开关的默认值与类型正确
    3. 环境变量（AMSAPI_*）覆盖优先级的正确性 —— CI/CD 接入的关键
    4. INI 配置读取的错误分支
"""
import importlib.util
import os
import runpy

import pytest

from common.project_path import Path
from common.read_config import ReadConfig
from config import settings


# ======================================================================
# 一、路径常量
# ======================================================================
class TestPaths:
    def test_base_dir_is_project_root(self):
        assert os.path.basename(settings.BASE_DIR) == "amsapi-auto"
        assert os.path.isdir(settings.BASE_DIR)

    @pytest.mark.parametrize("path", [
        settings.CONFIG_DIR, settings.DATA_DIR, settings.LOG_DIR,
        settings.REPORT_DIR, settings.CASES_DIR,
    ])
    def test_runtime_dirs_exist(self, path):
        assert os.path.isdir(path), "目录不存在：{}".format(path)

    def test_excel_and_conf_file_exist(self):
        assert os.path.isfile(settings.EXCEL_FILE)
        assert os.path.isfile(settings.CONF_FILE)

    def test_allure_dirs_under_report(self):
        assert settings.ALLURE_RESULTS_DIR.startswith(settings.REPORT_DIR)
        assert settings.ALLURE_REPORT_DIR.startswith(settings.REPORT_DIR)

    def test_legacy_accessors(self):
        """兼容旧接口的取值函数应返回同一路径。"""
        assert settings.get_log_path() == settings.LOG_DIR
        assert settings.get_report_path() == settings.REPORT_DIR
        assert settings.get_conf_path() == settings.CONFIG_DIR
        assert settings.get_data_path() == settings.DATA_DIR

    def test_project_path_matches_settings(self):
        """project_path 必须与 settings 同源，否则会出现两套路径。"""
        assert Path.project_path == settings.BASE_DIR
        assert Path.test_case_path == settings.EXCEL_FILE
        assert Path.cases_dir == settings.CASES_DIR
        assert Path.conf_path == settings.CONF_FILE
        assert Path.test_config_path == settings.CONF_FILE
        assert Path.test_report_path == settings.REPORT_DIR
        assert Path.test_log_path == settings.LOG_DIR


# ======================================================================
# 二、运行配置
# ======================================================================
class TestRunConfig:
    def test_default_data_source_is_supported(self):
        assert settings.RunConfig.DATA_SOURCE in settings.VALID_DATA_SOURCES

    def test_types(self):
        assert isinstance(settings.RunConfig.TIMEOUT, int)
        assert isinstance(settings.RunConfig.WRITE_BACK, bool)
        assert isinstance(settings.RunConfig.VERIFY, bool)
        assert isinstance(settings.RunConfig.SMOKE_ONLY, bool)
        assert isinstance(settings.RunConfig.BASE_URL, str)

    def test_report_type_lowercase(self):
        assert settings.RunConfig.REPORT_TYPE == str(settings.RunConfig.REPORT_TYPE).lower()

    def test_db_config_keys(self):
        assert set(settings.DB_CONFIG) == {"host", "user", "password",
                                           "database", "port", "charset"}
        assert isinstance(settings.DB_CONFIG["port"], int)

    def test_resolve_db_helpers(self):
        assert settings.resolve_db_web() == settings.RunConfig.DB_WEB
        assert settings.resolve_db_environment() == settings.RunConfig.DB_ENVIRONMENT

    def test_to_bool_helper(self):
        assert settings._to_bool("1") is True
        assert settings._to_bool("TRUE") is True
        assert settings._to_bool("0") is False
        assert settings._to_bool("no") is False

    def test_load_conf_ini_missing_file_is_silent(self, monkeypatch, tmp_path):
        """配置文件缺失时应静默跳过，而不是让整个框架起不来。"""
        monkeypatch.setattr(settings, "CONF_FILE", str(tmp_path / "not-exist.ini"))
        assert settings._load_conf_ini() is None


class TestDataSourceMarker:
    """
    数据源 -> 驱动 marker 的映射。

    这是「data_source 真正生效」的关键：用例层据此只加载选中的那个数据驱动，
    避免「配了 excel 却把 YAML 用例也跑了一遍」。
    """

    def test_excel(self, monkeypatch):
        monkeypatch.setattr(settings.RunConfig, "DATA_SOURCE", "excel")
        assert settings.resolve_data_source() == "excel"
        assert settings.data_source_marker() == "excel"

    def test_yaml(self, monkeypatch):
        monkeypatch.setattr(settings.RunConfig, "DATA_SOURCE", "yaml")
        assert settings.data_source_marker() == "yaml"

    def test_mysql(self, monkeypatch):
        monkeypatch.setattr(settings.RunConfig, "DATA_SOURCE", "mysql")
        assert settings.data_source_marker() == "mysql"

    def test_all_and_blank_mean_no_limit(self, monkeypatch):
        """all / 空 / 大小写与空白差异都表示「不做限制」。"""
        for value in ("all", "ALL", " all ", ""):
            monkeypatch.setattr(settings.RunConfig, "DATA_SOURCE", value)
            assert settings.resolve_data_source() == value.strip().lower()
            assert settings.data_source_marker() is None

    def test_unknown_value(self, monkeypatch):
        """未知取值不猜：原样返回，由用例层报错提示，且不在合法值集合内。"""
        monkeypatch.setattr(settings.RunConfig, "DATA_SOURCE", "oracle")
        assert settings.resolve_data_source() == "oracle"
        assert settings.data_source_marker() is None
        assert "oracle" not in settings.VALID_DATA_SOURCES

    def test_valid_sources(self):
        assert set(settings.VALID_DATA_SOURCES) == {"excel", "yaml", "mysql", "all"}
        assert set(settings.DATA_SOURCE_MARKERS) == {"excel", "yaml", "mysql"}


# ======================================================================
# 三、环境变量覆盖（CI/CD 关键路径）
# ======================================================================
class TestEnvOverride:
    """验证优先级：环境变量 > conf.ini > 默认值。"""

    def test_override_run_items(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_ENV", "uat")
        monkeypatch.setenv("AMSAPI_BASE_URL", "http://10.0.0.1:9050")
        monkeypatch.setenv("AMSAPI_TIMEOUT", "99")
        monkeypatch.setenv("AMSAPI_WRITE_BACK", "false")
        monkeypatch.setenv("AMSAPI_SMOKE", "1")
        monkeypatch.setenv("AMSAPI_TAGS", "core")
        monkeypatch.setenv("AMSAPI_DATA_SOURCE", "yaml")
        monkeypatch.setenv("AMSAPI_SHEET_NAME", "sheet_x")
        settings._load_env()

        assert settings.RunConfig.ENV == "uat"
        assert settings.RunConfig.BASE_URL == "http://10.0.0.1:9050"
        assert settings.RunConfig.TIMEOUT == 99
        assert settings.RunConfig.WRITE_BACK is False
        assert settings.RunConfig.SMOKE_ONLY is True
        assert settings.RunConfig.TAGS == "core"
        assert settings.RunConfig.DATA_SOURCE == "yaml"
        assert settings.RunConfig.SHEET_NAME == "sheet_x"

    def test_override_db_config(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_DB_HOST", "db.internal")
        monkeypatch.setenv("AMSAPI_DB_PORT", "13306")
        monkeypatch.setenv("AMSAPI_DB_PASSWORD", "p@ss")
        settings._load_env()

        assert settings.DB_CONFIG["host"] == "db.internal"
        assert settings.DB_CONFIG["port"] == 13306
        assert isinstance(settings.DB_CONFIG["port"], int)
        assert settings.DB_CONFIG["password"] == "p@ss"

    def test_empty_env_does_not_override(self, monkeypatch):
        """空串不应覆盖配置，否则 CI 里未填写的变量会清空环境配置。"""
        settings.RunConfig.BASE_URL = "http://keep-me"
        monkeypatch.setenv("AMSAPI_BASE_URL", "")
        settings._load_env()
        assert settings.RunConfig.BASE_URL == "http://keep-me"

    def test_report_type_normalized_to_lower(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_REPORT_TYPE", "ALLURE")
        settings._load_env()
        assert settings.RunConfig.REPORT_TYPE == "allure"


# ======================================================================
# 五、可配置分组（日志 / 报告 / 认证 / CI 判定）
# ======================================================================
class TestConfigGroups:
    """
    这些值原先硬编码在各自模块里（日志格式、附件截断长度、OAuth2 续期提前量、
    CI 环境变量清单……），现改为集中配置。本组用例锁定「配置真的能改到行为」。
    """

    def test_report_html_path_under_report_dir(self):
        path = settings.ReportConfig.html_path()
        assert os.path.dirname(path) == settings.REPORT_DIR
        assert os.path.basename(path) == settings.ReportConfig.HTML_NAME

    def test_log_file_name_format_respected(self, monkeypatch):
        """日志文件名格式可配：改成固定串后文件名应随之变化。"""
        monkeypatch.setattr(settings.LogConfig, "FILE_NAME_FORMAT", "fixed-name")
        assert settings.LogConfig.file_name() == "fixed-name.log"

    def test_log_file_name_default_is_dated(self):
        name = settings.LogConfig.file_name()
        assert name.endswith(".log")
        assert len(name) == 14                     # YYYY_MM_DD.log

    def test_auth_defaults_are_sane(self):
        assert isinstance(settings.AuthConfig.REFRESH_AHEAD, int)
        assert isinstance(settings.AuthConfig.TOKEN_TIMEOUT, int)
        assert isinstance(settings.AuthConfig.TOKEN_VERIFY, bool)

    def test_ci_detect_vars_are_tuple_of_names(self):
        assert isinstance(settings.CIConfig.DETECT_ENV_VARS, tuple)
        assert settings.CIConfig.DETECT_ENV_VARS
        assert all(isinstance(item, str) and item for item in settings.CIConfig.DETECT_ENV_VARS)

    def test_db_defaults_contain_no_real_credentials(self):
        """
        开源约束：默认 DB 配置里不允许出现真实账号密码。

        后端场景：仓库开源后，任何人都不应因「默认值」而连上或猜到内部数据库。
        """
        assert settings.DB_CONFIG["host"] == ""
        assert settings.DB_CONFIG["user"] == ""
        assert settings.DB_CONFIG["password"] == ""
        assert settings.DB_CONFIG["database"] == ""

    def test_no_real_endpoint_baked_into_defaults(self):
        """开源约束：默认配置里不得残留真实内网地址。"""
        assert "139.186" not in settings.ReportConfig.TITLE
        assert "139.186" not in settings.RunConfig.BASE_URL


class TestConfigGroupEnvOverride:
    """日志 / 报告 / 认证 分组同样支持 AMSAPI_* 环境变量覆盖。"""

    def test_override_log_and_report(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_LOG_LEVEL", "warning")
        monkeypatch.setenv("AMSAPI_LOG_CONSOLE_LEVEL", "error")
        monkeypatch.setenv("AMSAPI_REPORT_TITLE", "自定义标题")
        monkeypatch.setenv("AMSAPI_REPORT_PROJECT", "自定义项目")
        monkeypatch.setenv("AMSAPI_REPORT_HTML_NAME", "out.html")
        monkeypatch.setenv("AMSAPI_ALLURE_MAX_ATTACH_LEN", "1234")
        settings._load_env()

        assert settings.LogConfig.LEVEL == "WARNING"
        assert settings.LogConfig.CONSOLE_LEVEL == "ERROR"
        assert settings.ReportConfig.TITLE == "自定义标题"
        assert settings.ReportConfig.PROJECT == "自定义项目"
        assert settings.ReportConfig.HTML_NAME == "out.html"
        assert settings.ReportConfig.MAX_ATTACH_LEN == 1234

    def test_override_oauth2(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_OAUTH2_REFRESH_AHEAD", "5")
        monkeypatch.setenv("AMSAPI_OAUTH2_TOKEN_TIMEOUT", "3")
        monkeypatch.setenv("AMSAPI_OAUTH2_TOKEN_VERIFY", "true")
        settings._load_env()

        assert settings.AuthConfig.REFRESH_AHEAD == 5
        assert settings.AuthConfig.TOKEN_TIMEOUT == 3
        assert settings.AuthConfig.TOKEN_VERIFY is True

    def test_empty_env_does_not_override_group_items(self, monkeypatch):
        settings.ReportConfig.TITLE = "保留我"
        monkeypatch.setenv("AMSAPI_REPORT_TITLE", "")
        settings._load_env()
        assert settings.ReportConfig.TITLE == "保留我"

    def test_conf_ini_percent_format_not_interpolated(self):
        """
        conf.ini 里含 % 的日志格式必须原样读出。

        configparser 默认会把 `%` 当插值语法，导致 `%Y_%m_%d` 直接抛
        InterpolationSyntaxError —— 这是「配置化」引入的新坑，必须锁住。
        """
        assert "%(asctime)s" in settings.LogConfig.FORMAT
        assert "%Y_%m_%d" == settings.LogConfig.FILE_NAME_FORMAT


# ======================================================================
# 六、INI 读取
# ======================================================================
class TestReadConfig:
    def test_read_existing_option(self, tmp_path):
        f = tmp_path / "a.ini"
        f.write_text("[run]\ntimeout = 30\n", encoding="utf-8")
        assert ReadConfig.get_config(str(f), "run", "timeout") == "30"

    def test_default_when_option_missing(self, tmp_path):
        f = tmp_path / "a.ini"
        f.write_text("[run]\ntimeout = 30\n", encoding="utf-8")
        assert ReadConfig.get_config(str(f), "run", "nope", default="D") == "D"

    def test_default_none_returns_none(self, tmp_path):
        """显式传 default=None 时应返回 None（原实现会误抛 KeyError）。"""
        f = tmp_path / "a.ini"
        f.write_text("[run]\ntimeout = 30\n", encoding="utf-8")
        assert ReadConfig.get_config(str(f), "run", "nope", default=None) is None

    def test_missing_option_without_default_raises(self, tmp_path):
        f = tmp_path / "a.ini"
        f.write_text("[run]\ntimeout = 30\n", encoding="utf-8")
        with pytest.raises(KeyError):
            ReadConfig.get_config(str(f), "run", "nope")

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ReadConfig.get_config(str(tmp_path / "not_exist.ini"), "run", "x")

    def test_read_section(self, tmp_path):
        f = tmp_path / "a.ini"
        f.write_text("[db]\nhost = 127.0.0.1\nport = 3306\n", encoding="utf-8")
        assert ReadConfig.get_section(str(f), "db") == {"host": "127.0.0.1", "port": "3306"}

    def test_read_missing_section_returns_empty(self, tmp_path):
        f = tmp_path / "a.ini"
        f.write_text("[db]\nhost = 127.0.0.1\n", encoding="utf-8")
        assert ReadConfig.get_section(str(f), "nope") == {}

    def test_read_section_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ReadConfig.get_section(str(tmp_path / "not_exist.ini"), "db")

    def test_read_real_conf_ini(self):
        """真实配置文件必须可读，且关键项存在。"""
        report_type = ReadConfig.get_config(settings.CONF_FILE, "report",
                                            "report_type", default="allure")
        assert report_type in ("allure", "html", "both", "none")
        assert ReadConfig.get_section(settings.CONF_FILE, "run").get("timeout") == "10"


# ======================================================================
# 七、模块自测块
# ======================================================================
class TestModuleEntryBlocks:
    """
    各模块末尾的 `if __name__ == "__main__"` 自测块应当可直接运行。

    新人排查问题时常用 `python -m xxx` 快速验证，这些入口不能是坏的。
    注：requestsutil 的自测块会发起真实 HTTP 请求，故不在此执行。
    """

    @pytest.mark.parametrize("module", [
        "config.settings",
        "common.project_path",
        "common.read_config",
        "common.variable",
        "utils.logutil",
        "utils.yamlutil",
        "utils.excelutil",
    ])
    def test_module_runs_as_main(self, module, capsys):
        # 用 run_path 执行源文件，等价于 `python xxx.py`（避免 run_module 对已导入模块的警告）
        spec = importlib.util.find_spec(module)
        assert spec and spec.origin, "找不到模块源文件：{}".format(module)
        runpy.run_path(spec.origin, run_name="__main__")
        assert isinstance(capsys.readouterr().out, str)
