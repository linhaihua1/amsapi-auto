# -*- coding: utf-8 -*-
"""
单元测试：common/response.py（响应判定层）
==========================================
这一层决定「业务算不算成功」，是整个适配能力里最容易被写错的部分：
多一种响应风格、少配一个成功值，结果就是整套用例全红或全绿地错。
因此这里把六种内置风格、自定义路径、成功值集合、HTTP 门槛全部固定下来。
"""
import pytest

from common import response as response_module
from common.exceptions import CaseDataError
from common.response import ResponseSpec


def resp(body=None, code=200):
    """构造统一响应字典。"""
    return {"code": code, "body": {} if body is None else body}


# ======================================================================
# 一、构造与配置归一化
# ======================================================================
class TestInit:
    def test_default_style_is_status(self):
        """默认必须是 status —— 与改造前行为一致，保证存量用例零影响。"""
        spec = ResponseSpec()
        assert spec.style == "status"
        assert spec.code_paths == ("body.status",)

    def test_unknown_style_falls_back_to_status(self):
        assert ResponseSpec(style="不存在的风格").style == "status"

    @pytest.mark.parametrize("style", ["status", "code", "success", "errno", "retcode", "raw"])
    def test_all_builtin_styles_constructible(self, style):
        assert ResponseSpec(style=style).style == style

    def test_success_path_overrides_style_candidates(self):
        spec = ResponseSpec(style="code", success_path="body.returnCode")
        assert spec.code_paths == ("body.returnCode",)

    def test_http_ok_parsed_from_comma_string(self):
        """档案里写的是 '200,201' 这样的字符串，必须转成 int 集合才能与状态码比较。"""
        assert ResponseSpec(http_ok="200,201").http_ok == {200, 201}

    def test_http_ok_invalid_entries_ignored(self):
        assert ResponseSpec(http_ok="abc,200").http_ok == {200}

    def test_http_ok_all_invalid_falls_back_to_default(self):
        assert ResponseSpec(http_ok="abc").http_ok == {200, 201, 202, 204}

    def test_http_ok_default(self):
        assert ResponseSpec().http_ok == {200, 201, 202, 204}

    def test_success_values_from_string(self):
        assert ResponseSpec(success_values="0,200").success_values == ["0", "200"]

    def test_success_values_from_list(self):
        assert ResponseSpec(success_values=["0", "ok"]).success_values == ["0", "ok"]

    def test_success_values_chinese_comma(self):
        assert ResponseSpec(success_values="0，1").success_values == ["0", "1"]


# ======================================================================
# 二、业务码路径的候选与回退
# ======================================================================
class TestActualCode:
    def test_status_style(self):
        assert ResponseSpec("status").actual_code(resp({"status": 200})) == 200

    def test_code_style(self):
        assert ResponseSpec("code").actual_code(resp({"code": 0})) == 0

    def test_code_style_falls_back_to_ret_code(self):
        """字段名不统一时按候选顺序回退：body.code 取不到就试 body.retCode。"""
        assert ResponseSpec("code").actual_code(resp({"retCode": 7})) == 7

    def test_code_style_falls_back_to_result_code(self):
        assert ResponseSpec("code").actual_code(resp({"resultCode": 9})) == 9

    def test_success_style(self):
        assert ResponseSpec("success").actual_code(resp({"success": True})) is True

    def test_errno_style(self):
        assert ResponseSpec("errno").actual_code(resp({"errno": 0})) == 0

    def test_retcode_style_falls_back_to_lowercase(self):
        assert ResponseSpec("retcode").actual_code(resp({"retcode": "0000"})) == "0000"

    def test_raw_style_uses_http_code(self):
        """raw 风格不看业务码，直接拿 HTTP 状态码。"""
        assert ResponseSpec("raw").actual_code(resp({"x": 1}, code=201)) == 201

    def test_all_paths_missing_returns_none(self):
        assert ResponseSpec("code").actual_code(resp({"other": 1})) is None

    def test_empty_response_returns_none(self):
        assert ResponseSpec("status").actual_code({}) is None


# ======================================================================
# 三、成功判定
# ======================================================================
class TestIsSuccess:
    def test_none_response_is_failure(self):
        assert ResponseSpec().is_success(None) is False

    def test_http_not_ok_is_failure(self):
        """业务码再对，HTTP 500 也不算成功。"""
        assert ResponseSpec("status").is_success(resp({"status": 200}, code=500)) is False

    def test_expected_matches(self):
        assert ResponseSpec("status").is_success(resp({"status": 200}), 200) is True

    def test_expected_mismatch(self):
        assert ResponseSpec("status").is_success(resp({"status": 500}), 200) is False

    def test_expected_as_string_matches_int_actual(self):
        """Excel 里 expected_code 可能读成字符串 '200'。"""
        assert ResponseSpec("status").is_success(resp({"status": 200}), "200") is True

    def test_success_style_without_expected(self):
        """success 风格自带成功值集合，用例可以不写 expected_code。"""
        assert ResponseSpec("success").is_success(resp({"success": True})) is True
        assert ResponseSpec("success").is_success(resp({"success": False})) is False

    def test_errno_style_zero_means_success(self):
        assert ResponseSpec("errno").is_success(resp({"errno": 0})) is True
        assert ResponseSpec("errno").is_success(resp({"errno": 1})) is False

    def test_retcode_style(self):
        assert ResponseSpec("retcode").is_success(resp({"retCode": "0000"})) is True
        assert ResponseSpec("retcode").is_success(resp({"retCode": "9999"})) is False

    def test_expected_takes_priority_over_success_values(self):
        """用例显式给了期望值时，以用例为准，而不是无条件接受成功值集合。"""
        spec = ResponseSpec("errno", success_values="0")
        assert spec.is_success(resp({"errno": 0}), 999) is False

    def test_raw_style_only_checks_http(self):
        spec = ResponseSpec("raw")
        assert spec.is_success(resp({"whatever": 1}, code=200)) is True
        assert spec.is_success(resp({"whatever": 1}, code=500)) is False

    def test_incomplete_config_fails_closed(self):
        """
        既无 expected_code 也无 success_values 时必须失败。

        旧行为是「HTTP 通过即成功 + 一行 WARNING」，结果是漏填期望值的用例静默变绿：
        业务实际返回 status=999 也照样通过。这类假绿比红色失败危险得多 ——
        它让「断言根本没跑」看起来像「功能正常」。验收时实测复现过这一点。
        """
        with pytest.raises(CaseDataError, match="expected_code"):
            ResponseSpec("status").is_success(resp({"status": 999}))

    def test_incomplete_config_passes_when_explicitly_not_required(self):
        """档案显式 require_expected=false 时退回旧行为，但仍必须留痕（告警一次）。"""
        spec = ResponseSpec("status", require_expected=False)
        assert spec.is_success(resp({"status": 999})) is True
        spec.is_success(resp({"status": 999}))
        assert spec._warned is True

    def test_incomplete_config_does_not_warn_in_raw_style(self):
        """raw 风格本来就是只看 HTTP，不应告警。"""
        spec = ResponseSpec("raw")
        spec.is_success(resp({}))
        assert spec._warned is False


# ======================================================================
# 四、宽松比较
# ======================================================================
class TestEqual:
    @pytest.mark.parametrize("actual,expected", [
        (200, 200),
        ("200", 200),
        (200, "200"),
        ("200.0", 200),
        ("true", "True"),
        ("OK", "ok"),
        (" 200 ", 200),
    ])
    def test_equal_cases(self, actual, expected):
        assert ResponseSpec.equal(actual, expected) is True

    @pytest.mark.parametrize("actual,expected", [
        (200, 500),
        ("abc", 1),
        (None, 1),
        (1, None),
    ])
    def test_not_equal_cases(self, actual, expected):
        assert ResponseSpec.equal(actual, expected) is False

    def test_both_none(self):
        assert ResponseSpec.equal(None, None) is True


# ======================================================================
# 五、消息与数据体提取
# ======================================================================
class TestMessageAndData:
    def test_message_from_msg(self):
        assert ResponseSpec().message(resp({"msg": "操作成功"})) == "操作成功"

    def test_message_from_errmsg(self):
        assert ResponseSpec().message(resp({"errmsg": "参数错误"})) == "参数错误"

    def test_message_from_ret_msg(self):
        assert ResponseSpec().message(resp({"retMsg": "失败"})) == "失败"

    def test_message_custom_path(self):
        spec = ResponseSpec(message_path="body.errorDetail")
        assert spec.message(resp({"errorDetail": "详细信息"})) == "详细信息"

    def test_message_missing_returns_empty(self):
        assert ResponseSpec().message(resp({"x": 1})) == ""

    def test_data_from_data(self):
        assert ResponseSpec().data(resp({"data": {"id": 1}})) == {"id": 1}

    def test_data_from_result(self):
        assert ResponseSpec().data(resp({"result": [1, 2]})) == [1, 2]

    def test_data_from_rows(self):
        assert ResponseSpec().data(resp({"rows": []})) == []

    def test_data_custom_path(self):
        spec = ResponseSpec(data_path="body.pageData")
        assert spec.data(resp({"pageData": {"total": 3}})) == {"total": 3}

    def test_data_missing_returns_none(self):
        assert ResponseSpec().data(resp({"x": 1})) is None


# ======================================================================
# 六、展示信息
# ======================================================================
class TestDescribe:
    def test_describe_contains_expected_keys(self):
        info = ResponseSpec("code", success_values="0").describe()
        assert set(info) == {"判定风格", "业务码路径", "成功值集合"}
        assert info["判定风格"] == "code"
        assert "body.code" in info["业务码路径"]

    def test_describe_raw_style(self):
        assert ResponseSpec("raw").describe()["业务码路径"] == "(用 HTTP 状态码)"

    def test_describe_without_success_values(self):
        assert "expected_code" in ResponseSpec("status").describe()["成功值集合"]

    def test_styles_constant_exported(self):
        assert set(response_module.STYLES) == {
            "status", "code", "success", "errno", "retcode", "raw"}
