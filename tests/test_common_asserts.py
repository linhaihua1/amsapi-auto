# -*- coding: utf-8 -*-
"""
单元测试：common/asserts.py（断言增强层）
=========================================
断言是「用例判对判错」的最后一道关口：漏检会放过缺陷，误检会让团队不信任框架。
因此这里对每个算子都同时验证「该通过的通过」与「该失败的失败，且报错信息可读」。
"""
import pytest

from common import asserts
from common.asserts import (OPS, OP_DOC, base_equals, contains, db_count, db_equals, elapsed,
                            empty, endswith, equals, exists, gt, in_, length, not_contains,
                            not_equals, not_empty, not_exists, not_in, regex, run_op,
                            startswith, type_is, value_of)


def res(body=None, code=200, elapsed_ms=100):
    """构造统一响应字典。"""
    return {"code": code, "body": body if body is not None else {}, "elapsed": elapsed_ms}


# ======================================================================
# 一、取值
# ======================================================================
class TestValueOf:
    def test_nested_path(self):
        assert value_of(res({"data": {"id": 7}}), "body.data.id") == 7

    def test_list_index(self):
        assert value_of(res({"rows": [{"n": "a"}, {"n": "b"}]}), "body.rows.1.n") == "b"

    def test_http_code_path(self):
        assert value_of(res({}, code=404), "code") == 404

    def test_empty_path_returns_body(self):
        assert value_of(res({"a": 1}), "") == {"a": 1}

    def test_none_response(self):
        assert value_of(None, "body.a") is None

    def test_missing_path_returns_default(self):
        assert value_of(res({}), "body.nope", "d") == "d"


# ======================================================================
# 二、宽松比较
# ======================================================================
class TestBaseEquals:
    @pytest.mark.parametrize("a,b", [(200, "200"), ("True", True), ("ok", "OK"), (1.0, 1)])
    def test_equal(self, a, b):
        assert base_equals(a, b) is True

    def test_both_none(self):
        assert base_equals(None, None) is True

    def test_one_none(self):
        assert base_equals(None, 1) is False

    def test_not_equal_strings(self):
        assert base_equals("a", "b") is False


# ======================================================================
# 三、相等 / 包含 / 正则
# ======================================================================
class TestEquals:
    def test_pass(self):
        assert equals(res({"status": 200}), "body.status", 200) is True

    def test_pass_across_types(self):
        assert equals(res({"status": "200"}), "body.status", 200) is True

    def test_fail_message_contains_path_and_values(self):
        with pytest.raises(AssertionError) as exc:
            equals(res({"status": 500}), "body.status", 200)
        text = str(exc.value)
        assert "body.status" in text and "500" in text and "200" in text

    def test_fail_message_contains_response_summary(self):
        with pytest.raises(AssertionError, match="响应摘要"):
            equals(res({"status": 500}), "body.status", 200)

    def test_not_equals_pass(self):
        assert not_equals(res({"status": 500}), "body.status", 200) is True

    def test_not_equals_fail(self):
        with pytest.raises(AssertionError, match="不相等断言失败"):
            not_equals(res({"status": 200}), "body.status", 200)


class TestContains:
    def test_substring(self):
        assert contains(res({"msg": "操作成功完成"}), "body.msg", "成功") is True

    def test_list_element(self):
        assert contains(res({"roles": ["admin", "user"]}), "body.roles", "admin") is True

    def test_dict_key(self):
        assert contains(res({"data": {"id": 1}}), "body.data", "id") is True

    def test_fail(self):
        with pytest.raises(AssertionError, match="包含断言失败"):
            contains(res({"msg": "失败"}), "body.msg", "成功")

    def test_fail_on_missing_field(self):
        with pytest.raises(AssertionError, match="字段不存在"):
            contains(res({}), "body.msg", "x")

    def test_not_contains(self):
        assert not_contains(res({"msg": "失败"}), "body.msg", "成功") is True
        with pytest.raises(AssertionError):
            not_contains(res({"msg": "成功"}), "body.msg", "成功")


class TestPrefixSuffixRegex:
    def test_startswith(self):
        assert startswith(res({"u": "http://x"}), "body.u", "http") is True

    def test_startswith_fail(self):
        with pytest.raises(AssertionError, match="前缀断言失败"):
            startswith(res({"u": "ftp://x"}), "body.u", "http")

    def test_endswith(self):
        assert endswith(res({"f": "a.png"}), "body.f", ".png") is True

    def test_regex(self):
        assert regex(res({"phone": "13800138000"}), "body.phone", r"^1\d{10}$") is True

    def test_regex_fail(self):
        with pytest.raises(AssertionError, match="正则断言失败"):
            regex(res({"phone": "abc"}), "body.phone", r"^1\d{10}$")


# ======================================================================
# 四、存在与类型
# ======================================================================
class TestExists:
    def test_exists_pass(self):
        assert exists(res({"a": 0}), "body.a") is True

    def test_exists_fail_on_none(self):
        with pytest.raises(AssertionError, match="存在性断言失败"):
            exists(res({"a": None}), "body.a")

    def test_not_exists_pass(self):
        assert not_exists(res({}), "body.a") is True

    def test_not_exists_fail(self):
        with pytest.raises(AssertionError):
            not_exists(res({"a": 1}), "body.a")


class TestTypeIs:
    @pytest.mark.parametrize("value,expected", [
        ("s", "str"), (1, "int"), (1.5, "float"), (True, "bool"),
        ([1], "list"), ({"a": 1}, "dict"), (None, "none"), (1, "number"),
    ])
    def test_pass(self, value, expected):
        assert type_is(res({"v": value}), "body.v", expected) is True

    def test_numeric_string_accepted_for_number(self):
        """服务端把数字序列化成字符串是常见现象，不该因此判失败。"""
        assert type_is(res({"v": "18"}), "body.v", "number") is True

    def test_numeric_string_accepted_for_int(self):
        assert type_is(res({"v": "18"}), "body.v", "int") is True

    def test_non_numeric_string_is_not_number(self):
        with pytest.raises(AssertionError):
            type_is(res({"v": "abc"}), "body.v", "number")

    def test_bool_is_not_number(self):
        """Python 里 bool 是 int 子类，但业务上不该把 true 当数字。"""
        with pytest.raises(AssertionError):
            type_is(res({"v": True}), "body.v", "number")

    def test_unknown_type_name_lists_options(self):
        with pytest.raises(AssertionError, match="不支持的类型名"):
            type_is(res({"v": 1}), "body.v", "int64")

    def test_fail_message_has_actual_type(self):
        with pytest.raises(AssertionError, match="str"):
            type_is(res({"v": "abc"}), "body.v", "int")


# ======================================================================
# 五、集合与数值
# ======================================================================
class TestIn:
    def test_pass_with_comma_string(self):
        assert in_(res({"s": "on"}), "body.s", "on,off") is True

    def test_pass_with_list(self):
        assert in_(res({"s": "on"}), "body.s", ["on", "off"]) is True

    def test_fail(self):
        with pytest.raises(AssertionError, match="集合断言失败"):
            in_(res({"s": "x"}), "body.s", "on,off")

    def test_not_in(self):
        assert not_in(res({"s": "x"}), "body.s", "on,off") is True
        with pytest.raises(AssertionError):
            not_in(res({"s": "on"}), "body.s", "on,off")


class TestNumeric:
    def test_gt(self):
        assert gt(res({"n": 5}), "body.n", 3) is True

    def test_gt_accepts_string_numbers(self):
        assert gt(res({"n": "5"}), "body.n", "3") is True

    def test_gt_fail(self):
        with pytest.raises(AssertionError, match="大于断言失败"):
            gt(res({"n": 1}), "body.n", 3)

    def test_non_numeric_gives_clear_error(self):
        with pytest.raises(AssertionError, match="需要数值"):
            gt(res({"n": "abc"}), "body.n", 3)

    def test_bounds(self):
        data = res({"n": 5})
        assert asserts.ge(data, "body.n", 5) is True
        assert asserts.lt(data, "body.n", 6) is True
        assert asserts.le(data, "body.n", 5) is True

    def test_ge_fail(self):
        with pytest.raises(AssertionError, match="大于等于断言失败"):
            asserts.ge(res({"n": 4}), "body.n", 5)

    def test_lt_fail(self):
        with pytest.raises(AssertionError, match="小于断言失败"):
            asserts.lt(res({"n": 6}), "body.n", 5)

    def test_le_fail(self):
        with pytest.raises(AssertionError, match="小于等于断言失败"):
            asserts.le(res({"n": 6}), "body.n", 5)


class TestLength:
    def test_string_length(self):
        assert length(res({"s": "abc"}), "body.s", 3) is True

    def test_list_length(self):
        assert length(res({"l": [1, 2]}), "body.l", 2) is True

    def test_fail(self):
        with pytest.raises(AssertionError, match="长度断言失败"):
            length(res({"l": [1]}), "body.l", 2)

    def test_non_sized_value(self):
        with pytest.raises(AssertionError, match="可求长度"):
            length(res({"n": 1}), "body.n", 1)


class TestEmpty:
    @pytest.mark.parametrize("value", [None, "", [], {}])
    def test_empty_pass(self, value):
        assert empty(res({"v": value}), "body.v") is True

    def test_empty_fail(self):
        with pytest.raises(AssertionError, match="空值断言失败"):
            empty(res({"v": [1]}), "body.v")

    def test_not_empty(self):
        assert not_empty(res({"v": [1]}), "body.v") is True

    def test_not_empty_fail(self):
        with pytest.raises(AssertionError, match="非空断言失败"):
            not_empty(res({"v": []}), "body.v")


# ======================================================================
# 六、耗时与 Schema
# ======================================================================
class TestElapsed:
    def test_pass(self):
        assert elapsed(res(elapsed_ms=100), None, 200) is True

    def test_fail(self):
        with pytest.raises(AssertionError, match="耗时断言失败"):
            elapsed(res(elapsed_ms=500), None, 200)

    def test_missing_elapsed(self):
        with pytest.raises(AssertionError, match="没有 elapsed 字段"):
            elapsed({"code": 200, "body": {}}, None, 200)


class TestSchema:
    def test_validation_pass(self):
        pytest.importorskip("jsonschema")
        schema = {"type": "object", "required": ["status"]}
        assert asserts.schema(res({"status": 200}), "body", schema) is True

    def test_validation_fail_reports_path(self):
        pytest.importorskip("jsonschema")
        with pytest.raises(AssertionError, match="JSON Schema 校验失败"):
            asserts.schema(res({"x": 1}), "body",
                           {"type": "object", "required": ["status"]})

    def test_schema_from_json_string(self):
        pytest.importorskip("jsonschema")
        assert asserts.schema(res({"status": 1}), "body", '{"required": ["status"]}') is True

    def test_invalid_schema_json(self):
        pytest.importorskip("jsonschema")
        with pytest.raises(AssertionError, match="不是合法 JSON"):
            asserts.schema(res({"a": 1}), "body", "{bad json}")


# ======================================================================
# 七、数据库断言（可选依赖 pymysql，用替身验证）
# ======================================================================
class TestDbAsserts:
    @pytest.fixture
    def fake_mysql(self, monkeypatch):
        from tests.conftest import FakePymysql
        fake = FakePymysql(fetchone={"cnt": 3}, fetchall=[{"a": 1}, {"a": 2}])
        monkeypatch.setattr("utils.mysqlutil.pymysql", fake)
        return fake

    def test_db_equals_single_column(self, fake_mysql):
        assert db_equals("select cnt from t", 3, column="cnt") is True

    def test_db_equals_single_column_auto(self, fake_mysql):
        """单列结果不必显式指列名，自动取唯一那一列。"""
        assert db_equals("select cnt from t", 3) is True

    def test_db_equals_fail(self, fake_mysql):
        with pytest.raises(AssertionError, match="数据库断言失败"):
            db_equals("select cnt from t", 99, column="cnt")

    def test_db_count(self, fake_mysql):
        assert db_count("select * from t", 2) is True

    def test_db_count_fail(self, fake_mysql):
        with pytest.raises(AssertionError, match="数据库行数断言失败"):
            db_count("select * from t", 5)


# ======================================================================
# 八、算子调度
# ======================================================================
class TestRunOp:
    def test_dispatch_value_op(self):
        assert run_op("equals", res({"a": 1}), "body.a", 1) is True

    def test_dispatch_no_value_op(self):
        """exists / empty 这类算子不需要期望值，调度时不能多传参。"""
        assert run_op("exists", res({"a": 1}), "body.a") is True
        assert run_op("empty", res({}), "body.a") is True

    def test_alias_dispatch(self):
        assert run_op("eq", res({"a": 1}), "body.a", 1) is True

    def test_case_insensitive_name(self):
        assert run_op("EQUALS", res({"a": 1}), "body.a", 1) is True

    def test_unknown_op_lists_available(self):
        with pytest.raises(AssertionError) as exc:
            run_op("nope", res({}), "body.a", 1)
        assert "可用算子" in str(exc.value)

    def test_elapsed_via_dispatch(self):
        assert run_op("elapsed", res(elapsed_ms=50), None, 100) is True

    def test_all_documented_ops_are_registered(self):
        """文档里写的算子必须都能真正调度到，否则文档就是骗人的。"""
        for name in OP_DOC:
            assert name in OPS, "算子 {} 未注册".format(name)

    def test_op_names_sorted(self):
        assert asserts.op_names() == sorted(OP_DOC)

    def test_summary_handles_none(self):
        assert asserts.summary(None) == "(无响应)"

    def test_summary_truncates(self):
        long_res = res({"a": "x" * 1000})
        assert "已截断" in asserts.summary(long_res, limit=50)
