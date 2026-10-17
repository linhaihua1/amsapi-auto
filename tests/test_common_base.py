# -*- coding: utf-8 -*-
"""
单元测试：common/base.py（基础解析层）
======================================
覆盖参数化的三件核心事：占位符查找、变量替换、关联路径提取，
以及安全解析（safe_loads）、布尔转换、标签解析与匹配。

这些函数是框架最底层、被调用最频繁的部分，任何回归都会影响全部用例。
"""
import pytest

from common import base
from common.variable import GlobalVar


# ======================================================================
# find：找 ${var} 占位符
# ======================================================================
class TestFind:
    def test_find_from_string(self):
        assert base.find("${ticket}") == ["ticket"]

    def test_find_multiple(self):
        assert base.find("a=${a}&${b}") == ["a", "b"]

    def test_find_from_dict(self):
        """dict 会先被序列化，再从 JSON 文本中提取。"""
        assert base.find({"access-ticket": "${ticket}"}) == ["ticket"]

    def test_find_from_list(self):
        assert base.find(["${a}", "${b}"]) == ["a", "b"]

    def test_find_no_match_returns_none(self):
        """兼容旧逻辑：无匹配返回 None 而不是空列表。"""
        assert base.find("no placeholder") is None

    def test_find_non_string_returns_none(self):
        assert base.find(123) is None
        assert base.find(None) is None


# ======================================================================
# relace：变量替换
# ======================================================================
class TestRelace:
    def test_relace_with_explicit_map(self):
        assert base.relace("${ticket}", {"ticket": "abc"}) == "abc"

    def test_relace_from_global_var(self):
        GlobalVar.set("ticket", "T-001")
        assert base.relace("access=${ticket}") == "access=T-001"

    def test_missing_variable_replaced_by_empty(self):
        """变量池中没有的占位符替换为空串，而不是保留原样（避免脏数据透传到服务端）。"""
        assert base.relace("${not_exist}") == ""

    def test_none_value_becomes_empty(self):
        GlobalVar.set("ticket", None)
        assert base.relace("${ticket}") == ""

    def test_dict_input_returns_json_string(self):
        GlobalVar.set("ticket", "T-002")
        result = base.relace({"h": "${ticket}"})
        assert result == '{"h": "T-002"}'

    def test_no_placeholder_kept_as_is(self):
        assert base.relace("plain text") == "plain text"

    def test_dollar_sign_not_followed_by_brace_is_safe(self):
        """safe_substitute 对非占位符的 $ 不应抛异常。"""
        assert base.relace("价格 $100") == "价格 $100"

    def test_value_converted_to_string(self):
        """非字符串值需被转成字符串，否则 Template 处理会出错。"""
        assert base.relace("n=${n}", {"n": 123}) == "n=123"


# ======================================================================
# relace_obj：替换后还原为 Python 对象
# ======================================================================
class TestRelaceObj:
    def test_returns_dict(self):
        obj = base.relace_obj('{"access-ticket": "${ticket}"}', {"ticket": "T"})
        assert obj == {"access-ticket": "T"}

    def test_returns_text_when_not_json(self):
        assert base.relace_obj("${a}", {"a": "plain"}) == "plain"


# ======================================================================
# parse_relation：按路径取嵌套值
# ======================================================================
class TestParseRelation:
    def test_nested_dict(self):
        data = {"data": {"ticket": "abc"}}
        assert base.parse_relation(["data", "ticket"], data) == "abc"

    def test_list_index(self):
        data = {"rows": [{"name": "第一"}, {"name": "第二"}]}
        assert base.parse_relation(["rows", 1, "name"], data) == "第二"

    def test_empty_path_returns_root(self):
        data = {"a": 1}
        assert base.parse_relation([], data) == data

    def test_missing_key_returns_none(self):
        assert base.parse_relation(["data", "nope"], {"data": {}}) is None

    def test_index_out_of_range_returns_none(self):
        assert base.parse_relation(["rows", 5], {"rows": []}) is None

    def test_non_container_returns_none(self):
        assert base.parse_relation(["a", "b"], {"a": 1}) is None

    def test_does_not_mutate_input(self):
        """原实现用 del var[0]，会污染调用方的列表；此处必须不变。"""
        path = ["data", "ticket"]
        base.parse_relation(path, {"data": {"ticket": "x"}})
        assert path == ["data", "ticket"]

    def test_none_data_returns_none(self):
        assert base.parse_relation(["a"], None) is None


# ======================================================================
# parse_expression：关联表达式 name=path
# ======================================================================
class TestParseExpression:
    def test_normal(self):
        res = {"body": {"data": {"ticket": "TK"}}}
        assert base.parse_expression("ticket=body.data.ticket", res) == ("ticket", "TK")

    def test_spaces_are_trimmed(self):
        res = {"body": {"ticket": "TK"}}
        assert base.parse_expression(" ticket = body.ticket ", res) == ("ticket", "TK")

    def test_value_containing_equal_sign(self):
        """只按第一个 = 切分，值里的 = 属于路径。"""
        res = {"body": {"a=b": 1}}
        assert base.parse_expression("k=body.a=b", res) == ("k", 1)

    def test_missing_equal_sign_raises(self):
        with pytest.raises(ValueError):
            base.parse_expression("ticket", {})


# ======================================================================
# safe_loads：安全解析（替代 eval）
# ======================================================================
class TestSafeLoads:
    def test_json_string(self):
        assert base.safe_loads('{"a": 1}') == {"a": 1}

    def test_single_quote_literal(self):
        """兼容 Excel 里手写的单引号字典。"""
        assert base.safe_loads("{'a': 1}") == {"a": 1}

    def test_passthrough_for_container(self):
        obj = {"a": 1}
        assert base.safe_loads(obj) is obj

    def test_passthrough_for_number_and_bool(self):
        assert base.safe_loads(5) == 5
        assert base.safe_loads(True) is True

    def test_none_returns_default(self):
        assert base.safe_loads(None, default={}) == {}

    def test_empty_string_returns_default(self):
        assert base.safe_loads("   ", default="D") == "D"

    def test_invalid_returns_default(self):
        assert base.safe_loads("{不是合法内容", default=None) is None

    def test_does_not_execute_code(self):
        """注入的表达式不能被求值，只应返回默认值。"""
        assert base.safe_loads("__import__('os').getcwd()", default=None) is None


# ======================================================================
# to_bool
# ======================================================================
class TestToBool:
    @pytest.mark.parametrize("value", ["1", "true", "True", "yes", "on", "y", " TRUE "])
    def test_true_values(self, value):
        assert base.to_bool(value) is True

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "abc"])
    def test_false_values(self, value):
        assert base.to_bool(value) is False

    def test_none_returns_default(self):
        assert base.to_bool(None) is False                  # 默认 default=False
        assert base.to_bool(None, default=True) is True

    def test_bool_passthrough(self):
        assert base.to_bool(True) is True
        assert base.to_bool(False) is False


# ======================================================================
# 标签：parse_tags / match_tags
# ======================================================================
class TestTags:
    def test_parse_tags_str(self):
        assert base.parse_tags("smoke") == ["smoke"]

    def test_parse_tags_comma(self):
        assert base.parse_tags("smoke, core") == ["smoke", "core"]

    def test_parse_tags_chinese_comma(self):
        assert base.parse_tags("冒烟，核心") == ["冒烟", "核心"]

    def test_parse_tags_list(self):
        assert base.parse_tags(["smoke", " ", "core"]) == ["smoke", "core"]

    def test_parse_tags_empty(self):
        assert base.parse_tags(None) == []
        assert base.parse_tags("") == []
        assert base.parse_tags([]) == []

    def test_match_any(self):
        assert base.match_tags("smoke,core", "core") is True
        assert base.match_tags(["smoke"], ["core", "smoke"]) is True

    def test_not_match(self):
        assert base.match_tags("regression", "smoke") is False

    def test_empty_wanted_passes_all(self):
        """未指定筛选条件时应全部放行，而不是全部过滤掉。"""
        assert base.match_tags("anything", None) is True
        assert base.match_tags(None, "") is True

    def test_case_tag_empty_not_match(self):
        assert base.match_tags(None, "smoke") is False


# ======================================================================
# XML 互转（系统适配层：XML 报文的老财务 / 政务系统）
# ======================================================================
class TestXmlToDict:
    """
    XML -> dict 的约定必须稳定，因为关系型系统的字段断言
    （expects 里的 body.response.status 之类）全靠它。
    """

    def test_simple(self):
        assert base.xml_to_dict("<r><a>1</a></r>") == {"r": {"a": 1}}

    def test_declaration_and_nested(self):
        xml = ('<?xml version="1.0" encoding="UTF-8"?>'
               "<response><status>200</status><data><total>3</total></data></response>")
        assert base.xml_to_dict(xml) == {
            "response": {"status": 200, "data": {"total": 3}}}

    def test_attribute_uses_at_prefix(self):
        assert base.xml_to_dict('<item id="1">A</item>') == {
            "item": {"@id": "1", "#text": "A"}}

    def test_attribute_without_text(self):
        assert base.xml_to_dict('<item id="1"></item>') == {"item": {"@id": "1"}}

    def test_mixed_text_under_children(self):
        """既有子元素又有文本的混合内容，文本挂到 #text，不丢数据。"""
        assert base.xml_to_dict("<a>前后<b>1</b></a>") == {"a": {"b": 1, "#text": "前后"}}

    def test_repeated_child_becomes_list(self):
        """同名子元素多次出现必须聚合成列表，否则只能读到最后一个。"""
        parsed = base.xml_to_dict("<rows><r>1</r><r>2</r></rows>")
        assert parsed == {"rows": {"r": [1, 2]}}

    @pytest.mark.parametrize("text,expected", [
        ("1", 1), ("-2", -2), ("1.5", 1.5), ("-0.5", -0.5),
    ])
    def test_number_auto_conversion(self, text, expected):
        assert base.xml_to_dict("<a>{}</a>".format(text)) == {"a": expected}

    @pytest.mark.parametrize("text", ["0012", "1.2.3", "", "abc", "2026-09-26"])
    def test_non_number_kept_as_string(self, text):
        """带前导 0 的编号不能被转成数字，否则会丢前导零。"""
        assert base.xml_to_dict("<a>{}</a>".format(text)) == {"a": text}

    def test_namespace_stripped(self):
        """SOAP 报文带命名空间前缀，必须剥离后再建键，否则路径写不出来。"""
        xml = ('<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
               "<soap:Body><code>0</code></soap:Body></soap:Envelope>")
        assert base.xml_to_dict(xml) == {"Envelope": {"Body": {"code": 0}}}

    def test_bytes_input(self):
        assert base.xml_to_dict("<a>1</a>".encode("utf-8")) == {"a": 1}

    def test_invalid_xml_returns_none(self):
        """解析失败返回 None，调用方据此回退为纯文本（不能抛异常打断用例）。"""
        assert base.xml_to_dict("<a><b></a>") is None
        assert base.xml_to_dict("not xml") is None

    def test_none_and_non_string(self):
        assert base.xml_to_dict(None) is None
        assert base.xml_to_dict(123) is None


class TestDictToXml:
    def test_simple(self):
        assert base.dict_to_xml({"a": 1}) == "<a>1</a>"

    def test_single_key_becomes_root(self):
        """单键字典自动以该键为根标签，便于直接塞进 request_body。"""
        assert base.dict_to_xml({"request": {"a": 1}}) == "<request><a>1</a></request>"

    def test_multi_key_uses_root_param(self):
        assert base.dict_to_xml({"a": 1, "b": 2}) == "<root><a>1</a><b>2</b></root>"
        assert base.dict_to_xml({"a": 1, "b": 2}, root="req") == \
            "<req><a>1</a><b>2</b></req>"

    def test_attribute_and_text_conventions(self):
        assert base.dict_to_xml({"item": {"@id": "1", "#text": "A"}}) == \
            '<item id="1">A</item>'

    def test_list_becomes_repeated_elements(self):
        assert base.dict_to_xml({"rows": {"r": [1, 2]}}) == \
            "<rows><r>1</r><r>2</r></rows>"

    def test_declaration(self):
        text = base.dict_to_xml({"a": 1}, declaration=True)
        assert text.startswith('<?xml version="1.0" encoding="utf-8"?>')

    def test_none_value_becomes_empty(self):
        """None 值序列化成空元素，解析回来是空串（不丢字段）。"""
        assert base.xml_to_dict(base.dict_to_xml({"a": None})) == {"a": ""}

    def test_roundtrip(self):
        """往返转换必须稳定：造报文与解析响应用的是同一套约定。"""
        data = {"response": {"status": 200, "data": {"total": 3}}}
        assert base.xml_to_dict(base.dict_to_xml(data)) == data

    def test_roundtrip_with_list(self):
        data = {"rows": {"r": [1, 2]}}
        assert base.xml_to_dict(base.dict_to_xml(data)) == data
