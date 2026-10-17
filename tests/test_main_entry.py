# -*- coding: utf-8 -*-
"""
单元测试：main.py 的 main() 入口行为
====================================
入口决定「跑什么、产出什么报告、以什么退出码结束」，直接影响 CI/CD 能否正确
拦截问题版本。这里通过替换 pytest.main 来验证参数拼装与报告决策，
不真正执行任何用例。

覆盖的关键约定：
    1. --collect-only 强制不产出报告（避免用空结果覆盖历史报告）
    2. CI 环境下默认跳过本地 HTML 渲染（由流水线 Allure 插件渲染）
    3. 退出码原样透传（0 = 通过，非 0 = 失败）
"""
import os
import sys

import pytest

import main


@pytest.fixture
def entry(monkeypatch):
    """构造可控的入口运行环境，并记录调用痕迹。"""
    cwd = os.getcwd()
    records = {"pytest_args": None, "render": 0, "exit_code": 0}

    def fake_pytest_main(args):
        records["pytest_args"] = list(args)
        return records["exit_code"]

    monkeypatch.setattr(main.pytest, "main", fake_pytest_main)
    monkeypatch.setattr(main, "_render_allure_report",
                        lambda: records.__setitem__("render", records["render"] + 1))

    # 默认视为「非 CI 环境」，需要时由用例自行设置
    for key in main.CI_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv("AMSAPI_RENDER_ALLURE", raising=False)

    yield records
    os.chdir(cwd)


def _run(monkeypatch, argv):
    """执行 main() 并返回退出码。"""
    monkeypatch.setattr(sys, "argv", ["main.py"] + argv)
    with pytest.raises(SystemExit) as exc:
        main.main()
    return exc.value.code


def _html_arg(pytest_args):
    """取出 --html 参数（等号连写形式），返回完整 token 与路径。"""
    token = next(a for a in pytest_args if a.startswith("--html="))
    return token, token.split("=", 1)[1]


# ======================================================================
# 一、报告类型决策
# ======================================================================
class TestReportDecision:
    @pytest.fixture(autouse=True)
    def _disable_smoke(self):
        """固定为非冒烟模式，避免 CI 注入的 AMSAPI_SMOKE 影响参数断言。"""
        main.settings.RunConfig.SMOKE_ONLY = False

    def test_default_report_from_settings(self, monkeypatch, entry, capsys):
        settings_report = main.settings.RunConfig.REPORT_TYPE
        assert _run(monkeypatch, []) == 0
        assert "报告类型   : {}".format(settings_report) in capsys.readouterr().out
        assert entry["render"] == (1 if settings_report in ("allure", "both") else 0)

    def test_allure_renders_after_run(self, monkeypatch, entry):
        assert _run(monkeypatch, ["--report", "allure"]) == 0
        assert entry["render"] == 1
        assert not any(a.startswith("--html") for a in entry["pytest_args"])

    def test_html_report_adds_pytest_html_args(self, monkeypatch, entry):
        assert _run(monkeypatch, ["--report", "html"]) == 0
        assert any(a.startswith("--html=") for a in entry["pytest_args"])
        assert "--self-contained-html" in entry["pytest_args"]
        assert entry["render"] == 0

    def test_both_renders_and_adds_html(self, monkeypatch, entry):
        assert _run(monkeypatch, ["--report", "both"]) == 0
        assert any(a.startswith("--html=") for a in entry["pytest_args"])
        assert entry["render"] == 1

    def test_none_produces_nothing(self, monkeypatch, entry, capsys):
        assert _run(monkeypatch, ["--report", "none"]) == 0
        assert entry["render"] == 0
        assert not any(a.startswith("--html") for a in entry["pytest_args"])

    def test_html_path_inside_report_dir(self, monkeypatch, entry):
        _run(monkeypatch, ["--report", "html"])
        _token, html_path = _html_arg(entry["pytest_args"])
        assert os.path.dirname(html_path) == main.settings.REPORT_DIR

    def test_collect_only_forces_no_report(self, monkeypatch, entry, capsys):
        """--collect-only 是排查命令，不得产出/覆盖任何报告。"""
        assert _run(monkeypatch, ["--collect-only", "--report", "allure"]) == 0
        assert entry["render"] == 0
        assert "仅收集用例，不产出报告" in capsys.readouterr().out
        assert entry["pytest_args"] == ["--collect-only"]


# ======================================================================
# 一之二、--html 参数写法回归（对应真实缺陷）
# ======================================================================
class TestHtmlArgForm:
    """
    回归：--html 必须用等号连写，不能拆成 `--html <路径>`。

    背景（真实缺陷）：pytest 在 _initini 阶段解析命令行时 pytest-html 尚未注册，
    分离式写法里的路径会被当成「位置参数」即用例路径。本框架的用例目录靠
    pytest.ini 的 testpaths 定位，命令行本不带位置参数，于是第二次运行
    （report.html 已存在）时会 rootdir 上翻、pytest.ini 失效，收集整棵上层
    目录并以 UsageError 退出（退出码 4）。
    """

    def test_uses_equals_form(self, monkeypatch, entry):
        _run(monkeypatch, ["--report", "both"])
        assert "--html" not in entry["pytest_args"]        # 禁止分离式
        assert any(a.startswith("--html=") for a in entry["pytest_args"])

    def test_no_positional_path_leaks(self, monkeypatch, entry):
        """参数里不得出现「看着像路径」的位置参数（会顶掉 testpaths）。"""
        _run(monkeypatch, ["--report", "html", "-m", "yaml"])
        positionals = [a for a in entry["pytest_args"]
                       if not a.startswith("-") and a != "yaml"]
        assert positionals == []

    def test_build_pytest_args_is_pure(self):
        """纯函数：不得修改传入的参数列表，且能独立断言。"""
        original = ["-m", "yaml"]
        args = main.build_pytest_args("both", True, original)
        assert original == ["-m", "yaml"]                  # 入参未被就地修改
        assert any(a.startswith("--html=") for a in args)
        index = args.index("-m")
        assert args[index + 1] == "(yaml) and smoke"

    def test_build_pytest_args_without_report(self):
        """report=none 时不产生任何报告参数。"""
        assert main.build_pytest_args("none", False, []) == []


# ======================================================================
# 二、冒烟模式
# ======================================================================
class TestSmokeMode:
    def test_smoke_adds_marker(self, monkeypatch, entry):
        _run(monkeypatch, ["--smoke", "--report", "none"])
        assert entry["pytest_args"] == ["-m", "smoke"]

    def test_smoke_merges_existing_marker(self, monkeypatch, entry):
        _run(monkeypatch, ["--smoke", "-m", "excel", "--report", "none"])
        assert entry["pytest_args"] == ["-m", "(excel) and smoke"]

    def test_smoke_mode_printed(self, monkeypatch, entry, capsys):
        _run(monkeypatch, ["--smoke", "--report", "none"])
        assert "执行模式   : 冒烟" in capsys.readouterr().out


# ======================================================================
# 三、CI 环境行为
# ======================================================================
class TestCiBehavior:
    def test_ci_skips_local_rendering(self, monkeypatch, entry, capsys):
        monkeypatch.setenv("JENKINS_URL", "http://jenkins.local:8080")
        assert _run(monkeypatch, ["--report", "allure"]) == 0
        out = capsys.readouterr().out
        assert entry["render"] == 0
        assert "跳过本地 HTML 渲染" in out
        assert "CI 环境    : 是" in out

    def test_ci_renders_when_forced(self, monkeypatch, entry):
        monkeypatch.setenv("JENKINS_URL", "http://jenkins.local:8080")
        monkeypatch.setenv("AMSAPI_RENDER_ALLURE", "1")
        _run(monkeypatch, ["--report", "allure"])
        assert entry["render"] == 1

    def test_local_env_renders(self, monkeypatch, entry):
        _run(monkeypatch, ["--report", "allure"])
        assert entry["render"] == 1

    def test_ci_does_not_affect_html_report(self, monkeypatch, entry):
        """CI 只影响 Allure 本地渲染，pytest-html 报告不受影响。"""
        monkeypatch.setenv("JENKINS_URL", "http://jenkins.local:8080")
        _run(monkeypatch, ["--report", "html"])
        assert any(a.startswith("--html=") for a in entry["pytest_args"])


# ======================================================================
# 四、退出码透传
# ======================================================================
class TestExitCode:
    @pytest.mark.parametrize("code", [0, 1, 2, 5])
    def test_exit_code_forwarded(self, monkeypatch, entry, code):
        """退出码必须原样返回，流水线据此判定构建成败。"""
        entry["exit_code"] = code
        assert _run(monkeypatch, ["--report", "none"]) == code

    def test_banner_printed(self, monkeypatch, entry, capsys):
        _run(monkeypatch, ["--report", "none"])
        out = capsys.readouterr().out
        # 横幅标题取自 conf.ini [report] title（不再硬编码字面量）
        assert "{} 启动".format(main.settings.ReportConfig.TITLE) in out
        assert "测试结束，退出码" in out

    def test_working_directory_switched_to_project_root(self, monkeypatch, entry, tmp_path):
        monkeypatch.chdir(tmp_path)
        _run(monkeypatch, ["--report", "none"])
        assert os.getcwd() == main.settings.BASE_DIR
