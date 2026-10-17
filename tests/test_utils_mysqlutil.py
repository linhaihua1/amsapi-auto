# -*- coding: utf-8 -*-
"""
单元测试：utils/mysqlutil.py（MySQL 连接与执行封装）
===================================================
本机没有 MySQL 实例，因此用 pymysql 模块替身离线验证：
惰性连接、连接幂等、参数化查询、事务提交/回滚、资源释放、with 语法。
"""
import pytest

from common.exceptions import ConfigError
from tests.conftest import FakePymysql
from utils import mysqlutil
from utils.mysqlutil import MysqlUtil


@pytest.fixture
def fake_pymysql(monkeypatch):
    """把模块内的 pymysql 换成替身，返回替身以便断言。"""
    fake = FakePymysql(fetchone={"id": 1}, fetchall=[{"id": 1}, {"id": 2}],
                       execute_result=3)
    monkeypatch.setattr(mysqlutil, "pymysql", fake)
    return fake


class TestValidateDbConfig:
    """配置完整性校验：真实使用方连接前调用，缺项时给出可操作指引。"""

    def test_complete_config_passes(self):
        assert mysqlutil.validate_db_config(
            {"host": "h", "user": "u", "database": "d"}) is True

    def test_missing_keys_are_listed(self):
        with pytest.raises(ConfigError) as exc:
            mysqlutil.validate_db_config({"host": "h"})
        assert "user" in str(exc.value) and "database" in str(exc.value)

    def test_blank_value_counts_as_missing(self):
        """空白字符串等同于未配置（避免 conf.ini 留空却看似已填）。"""
        with pytest.raises(ConfigError) as exc:
            mysqlutil.validate_db_config({"host": "   ", "user": "u", "database": "d"})
        assert "host" in str(exc.value)

    def test_error_message_gives_actionable_hints(self):
        """错误信息需含 conf.ini 段名与环境变量名，便于按图索骥。"""
        with pytest.raises(ConfigError) as exc:
            mysqlutil.validate_db_config({})
        text = str(exc.value)
        assert "[db]" in text and "AMSAPI_DB_HOST" in text

    def test_defaults_to_settings(self, monkeypatch):
        """不传 config 时取 settings.DB_CONFIG（此处替换为空配置验证分支）。"""
        monkeypatch.setattr(mysqlutil.settings, "DB_CONFIG",
                            {"host": "", "user": "", "database": ""})
        with pytest.raises(ConfigError):
            mysqlutil.validate_db_config()

    def test_password_may_be_empty(self):
        """password 允许为空（本地免密实例），不应被判为缺项。"""
        assert mysqlutil.validate_db_config(
            {"host": "h", "user": "u", "database": "d", "password": ""}) is True


class TestConnect:
    def test_lazy_connect(self, fake_pymysql):
        """构造时不应建立连接（原实现导入即连库会直接崩）。"""
        util = MysqlUtil()
        assert fake_pymysql.connect_args is None
        assert util.is_connected is False

    def test_connect_uses_dict_cursor(self, fake_pymysql):
        """需以 cursorclass 传 DictCursor（原实现参数名写错为 cursor）。"""
        MysqlUtil(config={"host": "h", "port": 3306}).connect()
        assert fake_pymysql.connect_args["cursorclass"] == "DictCursor"

    def test_connect_is_idempotent(self, fake_pymysql):
        util = MysqlUtil()
        first = util.connect()
        second = util.connect()
        assert first is second
        assert util.is_connected is True

    def test_connect_without_pymysql_raises(self, monkeypatch):
        monkeypatch.setattr(mysqlutil, "pymysql", None)
        with pytest.raises(RuntimeError) as exc:
            MysqlUtil().connect()
        assert "pymysql" in str(exc.value)

    def test_config_defaults_to_settings(self, fake_pymysql):
        assert MysqlUtil().config["host"] == mysqlutil.settings.DB_CONFIG["host"]

    def test_config_is_copied(self, fake_pymysql):
        """外部 dict 不应被连接过程改动。"""
        raw = {"host": "h", "port": 1}
        util = MysqlUtil(config=raw)
        util.connect()
        assert raw == {"host": "h", "port": 1}
        assert util.config is not raw


class TestQuery:
    def test_fetchone(self, fake_pymysql):
        assert MysqlUtil().get_fetchone("SELECT 1") == {"id": 1}

    def test_fetchall(self, fake_pymysql):
        assert len(MysqlUtil().get_fetchall("SELECT * FROM t")) == 2

    def test_query_is_parameterized(self, fake_pymysql):
        """SQL 必须原样带 %s 占位符并把参数单独传入（防注入、防引号转义问题）。"""
        util = MysqlUtil()
        util.get_fetchall("SELECT * FROM t WHERE id = %s", (5,))
        assert util.cursor.executed == [("SELECT * FROM t WHERE id = %s", (5,))]

    def test_auto_connect_on_query(self, fake_pymysql):
        MysqlUtil().get_fetchall("SELECT 1")
        assert fake_pymysql.connect_args is not None


class TestExecute:
    def test_execute_commits_and_returns_rows(self, fake_pymysql):
        util = MysqlUtil()
        assert util.sql_execute("UPDATE t SET a = %s", (1,)) == 3
        assert fake_pymysql.conn.committed == 1

    def test_execute_rollback_on_error(self, monkeypatch):
        fake = FakePymysql(execute_error=RuntimeError("duplicate key"))
        monkeypatch.setattr(mysqlutil, "pymysql", fake)
        util = MysqlUtil()
        assert util.sql_execute("INSERT INTO t VALUES (1)") is False
        assert fake.conn.rolled_back == 1
        assert fake.conn.committed == 0


class TestCloseAndContext:
    def test_close_releases_resources(self, fake_pymysql):
        util = MysqlUtil()
        util.connect()
        cursor = util.cursor
        util.close()
        assert cursor.closed is True
        assert fake_pymysql.conn.closed is True
        assert util.db is None and util.cursor is None

    def test_close_when_never_connected(self, fake_pymysql):
        MysqlUtil().close()                                # 不应抛异常

    def test_context_manager(self, fake_pymysql):
        with MysqlUtil() as util:
            assert util.is_connected is True
            assert util.get_fetchone("SELECT 1") == {"id": 1}
        assert util.db is None                             # 退出时自动关闭
