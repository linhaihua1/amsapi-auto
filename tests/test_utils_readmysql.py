# -*- coding: utf-8 -*-
"""
单元测试：utils/readmysql.py（MySQL 数据访问层）
===============================================
MySQL 数据源是「可选通道」，其 URL 拼接规则沿用原框架：
    完整地址 = test_config.value + ':' + 用例.port_num + 用例.url
本测试用替身验证该规则与各分支，不需要真实数据库。
"""
import json

from tests.conftest import FakeDbMysql
from utils.readmysql import RdTestcase


# ======================================================================
# 一、用例读取
# ======================================================================
class TestLoadCases:
    def test_load_all_case_sql_and_args(self):
        mysql = FakeDbMysql(fetchall_result=[{"id": 1}])
        RdTestcase(mysql=mysql, web="gov").load_all_case()
        kind, sql, args = mysql.sql_log[0]
        assert kind == "fetchall"
        assert "FROM test_case_list" in sql
        assert "web = %s" in sql                    # 参数化，而非字符串拼接
        assert args == ("gov",)

    def test_load_all_case_accepts_explicit_web(self):
        mysql = FakeDbMysql(fetchall_result=[])
        RdTestcase(mysql=mysql, web="default").load_all_case(web="override")
        assert mysql.sql_log[0][2] == ("override",)

    def test_is_run_data_filters_by_isdel(self):
        mysql = FakeDbMysql(fetchall_result=[
            {"id": 1, "isdel": 1},
            {"id": 2, "isdel": 0},
            {"id": 3, "isdel": None},
        ])
        cases = RdTestcase(mysql=mysql).is_run_data()
        assert [c["id"] for c in cases] == [1]

    def test_is_run_data_accepts_string_flag(self):
        """MySQL 中 isdel 若为字符串 '1' 也应可执行（与 Excel 侧判断口径一致）。"""
        mysql = FakeDbMysql(fetchall_result=[{"id": 1, "isdel": "1"},
                                             {"id": 2, "isdel": "0"}])
        assert [c["id"] for c in RdTestcase(mysql=mysql).is_run_data()] == [1]


# ======================================================================
# 二、环境配置
# ======================================================================
class TestConfig:
    def test_load_confkey(self):
        mysql = FakeDbMysql(fetchall_result=[{"value": "http://x"}])
        RdTestcase(mysql=mysql).load_confkey("gov", "139")
        kind, sql, args = mysql.sql_log[0]
        assert "FROM test_config" in sql
        assert "web = %s AND environment = %s" in sql
        assert args == ("gov", "139")

    def test_get_conf_value(self):
        mysql = FakeDbMysql(fetchall_result=[{"value": "http://192.0.2.10"}])
        assert RdTestcase(mysql=mysql).get_conf_value("gov", "139") == \
            "http://192.0.2.10"

    def test_get_conf_value_empty_returns_default(self):
        mysql = FakeDbMysql(fetchall_result=[])
        assert RdTestcase(mysql=mysql).get_conf_value("w", "e", default="D") == "D"

    def test_get_conf_value_non_dict_row(self):
        mysql = FakeDbMysql(fetchall_result=["not-a-dict"])
        assert RdTestcase(mysql=mysql).get_conf_value("w", "e", default="D") == "D"

    def test_get_conf_value_missing_key_returns_default(self):
        mysql = FakeDbMysql(fetchall_result=[{"other": 1}])
        assert RdTestcase(mysql=mysql).get_conf_value("w", "e", default="D") == "D"


# ======================================================================
# 三、URL 拼接（原框架业务规则）
# ======================================================================
class TestBuildCaseUrl:
    def test_absolute_url_kept(self):
        case = {"url": "http://other:8080/v1/x"}
        assert RdTestcase(mysql=FakeDbMysql()).build_case_url(case) == \
            "http://other:8080/v1/x"

    def test_base_url_with_port(self):
        """配置域名 + ':' + port_num + 用例 url（原逻辑）。"""
        case = {"url": "/v1/users/login", "port_num": 9050}
        result = RdTestcase(mysql=FakeDbMysql()).build_case_url(
            case, base_url="http://192.0.2.10")
        assert result == "http://192.0.2.10:9050/v1/users/login"

    def test_base_url_without_port(self):
        case = {"url": "/v1/users/login"}
        result = RdTestcase(mysql=FakeDbMysql()).build_case_url(
            case, base_url="http://192.0.2.10")
        assert result == "http://192.0.2.10/v1/users/login"

    def test_base_url_trailing_slash_stripped(self):
        case = {"url": "/v1/x", "port_num": 80}
        result = RdTestcase(mysql=FakeDbMysql()).build_case_url(
            case, base_url="http://host/")
        assert result == "http://host:80/v1/x"

    def test_fetch_base_url_from_db_when_not_given(self):
        mysql = FakeDbMysql(fetchall_result=[{"value": "http://from-db"}])
        case = {"url": "/v1/x", "port_num": 9050}
        result = RdTestcase(mysql=mysql, web="w").build_case_url(case, environment="139")
        assert result == "http://from-db:9050/v1/x"
        assert mysql.sql_log[0][0] == "fetchall"

    def test_no_base_url_and_no_db_value(self):
        mysql = FakeDbMysql(fetchall_result=[])
        assert RdTestcase(mysql=mysql).build_case_url({"url": "/v1/x"}) == "/v1/x"

    def test_missing_url_treated_as_empty(self):
        assert RdTestcase(mysql=FakeDbMysql()).build_case_url({}) == ""


# ======================================================================
# 四、结果落库
# ======================================================================
class TestUpdateResults:
    def test_insert_sql_and_args(self):
        mysql = FakeDbMysql(execute_result=1)
        rows = RdTestcase(mysql=mysql).update_results({"code": 200}, True, 12)

        assert rows == 1
        kind, sql, args = mysql.sql_log[0]
        assert kind == "execute"
        assert "INSERT INTO test_result_record" in sql
        assert "%s" in sql                                  # 参数化
        assert args[0] == "12"                              # case_id 转字符串
        assert args[3] == "True"
        assert json.loads(args[2]) == {"code": 200}         # 响应体序列化为 JSON

    def test_chinese_response_not_escaped(self):
        mysql = FakeDbMysql()
        RdTestcase(mysql=mysql).update_results({"msg": "成功"}, True, 1)
        assert "成功" in mysql.sql_log[0][2][2]              # ensure_ascii=False
