# -*- coding: utf-8 -*-
"""
单元测试：main.py（统一入口的参数解析与 CI 判定）
================================================
入口脚本决定「跑什么、生成什么报告、以什么退出码结束」，直接关系到 CI/CD 能否
正确拦截问题版本，因此把参数解析逻辑逐分支固定下来。

注意：只测试纯函数，不触发 pytest.main（避免递归执行测试）。
"""
import pytest

import main
from config import settings


# ======================================================================
# 一、报告类型与冒烟开关解析
# ======================================================================
class TestParseArgs:
    def test_defaults_from_settings(self):
        report, smoke, args = main._parse_args([])
        assert report == settings.RunConfig.REPORT_TYPE
        assert smoke == settings.RunConfig.SMOKE_ONLY
        assert args == []

    def test_report_space_form(self):
        report, _, args = main._parse_args(["--report", "html"])
        assert report == "html"
        assert args == []

    def test_report_equal_form(self):
        report, _, _ = main._parse_args(["--report=both"])
        assert report == "both"

    def test_report_type_case_insensitive(self):
        report, _, _ = main._parse_args(["--report", "ALLURE"])
        assert report == "allure"

    def test_smoke_flag(self):
        _, smoke, _ = main._parse_args(["--smoke"])
        assert smoke is True

    def test_unknown_args_passed_to_pytest(self):
        _, _, args = main._parse_args(["-m", "excel", "-k", "login", "--collect-only"])
        assert args == ["-m", "excel", "-k", "login", "--collect-only"]

    def test_mixed_custom_and_pytest_args(self):
        report, smoke, args = main._parse_args(["--smoke", "-m", "excel", "--report", "none"])
        assert report == "none"
        assert smoke is True
        assert args == ["-m", "excel"]

    def test_report_without_value_exits(self):
        with pytest.raises(SystemExit) as exc:
            main._parse_args(["--report"])
        assert exc.value.code == 2

    def test_invalid_report_type_exits(self):
        with pytest.raises(SystemExit) as exc:
            main._parse_args(["--report", "pdf"])
        assert exc.value.code == 2

    def test_valid_report_types(self):
        assert set(main.VALID_REPORT_TYPES) == {"allure", "html", "both", "none"}


# ======================================================================
# 二、冒烟 marker 合并
# ======================================================================
class TestSmokeMarker:
    def test_append_when_no_marker(self):
        assert main._apply_smoke_marker(["--collect-only"]) == \
            ["--collect-only", "-m", "smoke"]

    def test_merge_with_existing_marker(self):
        """与已有的 -m 做「与」合并，而不是覆盖掉用户的筛选条件。"""
        assert main._apply_smoke_marker(["-m", "excel"]) == ["-m", "(excel) and smoke"]

    def test_merge_with_equal_form(self):
        assert main._apply_smoke_marker(["-m=yaml"]) == ["-m=(yaml) and smoke"]

    def test_merge_with_complex_expression(self):
        result = main._apply_smoke_marker(["-m", "excel or yaml"])
        assert result == ["-m", "(excel or yaml) and smoke"]

    def test_marker_at_end_without_value(self):
        """-m 后无值时补上 smoke，避免产生非法参数。"""
        assert main._apply_smoke_marker(["-m"]) == ["-m", "smoke"]

    def test_does_not_mutate_input(self):
        original = ["-m", "excel"]
        main._apply_smoke_marker(original)
        assert original == ["-m", "excel"]


# ======================================================================
# 三、CI 环境判定
# ======================================================================
class TestIsCi:
    @pytest.mark.parametrize("key", main.CI_ENV_KEYS)
    def test_detects_each_ci_variable(self, monkeypatch, key):
        for item in main.CI_ENV_KEYS:
            monkeypatch.delenv(item, raising=False)
        monkeypatch.setenv(key, "1")
        assert main._is_ci() is True

    def test_false_outside_ci(self, monkeypatch):
        for item in main.CI_ENV_KEYS:
            monkeypatch.delenv(item, raising=False)
        assert main._is_ci() is False

    def test_empty_value_is_not_ci(self, monkeypatch):
        for item in main.CI_ENV_KEYS:
            monkeypatch.delenv(item, raising=False)
        monkeypatch.setenv("JENKINS_URL", "")
        assert main._is_ci() is False


# ======================================================================
# 四、报告渲染入口的容错
# ======================================================================
class TestRenderReport:
    def test_render_failure_returns_nonzero(self, monkeypatch):
        """渲染失败不应抛异常影响测试结论，只返回非 0。"""
        import generate_report
        monkeypatch.setattr(generate_report, "generate",
                            _raise(RuntimeError("allure missing")))
        assert main._render_allure_report() == 1

    def test_render_success_returns_zero(self, monkeypatch):
        import generate_report
        monkeypatch.setattr(generate_report, "generate", lambda **kwargs: 0)
        assert main._render_allure_report() == 0


def _raise(exc):
    def _inner(*args, **kwargs):
        raise exc
    return _inner
