# -*- coding: utf-8 -*-
"""
单元测试：tools/generate_report.py（Allure 报告渲染）
====================================================
不真正调用 allure 命令（慢且依赖外部环境），而是用替身验证：
分支判断（缺 allure / 缺结果 / 缺 index）、命令行拼装、清理逻辑与返回码。
"""
import os

import pytest

import generate_report
from config import settings


@pytest.fixture
def allure_dirs(tmp_path, monkeypatch):
    """把 Allure 结果/报告目录指向临时目录。"""
    results = tmp_path / "allure-results"
    report = tmp_path / "allure-report"
    results.mkdir()
    monkeypatch.setattr(settings, "ALLURE_RESULTS_DIR", str(results))
    monkeypatch.setattr(settings, "ALLURE_REPORT_DIR", str(report))
    return results, report


class TestFindAllure:
    def test_returns_path_or_none(self):
        found = generate_report._find_allure()
        assert found is None or isinstance(found, str)


class TestGenerate:
    def test_missing_allure_returns_one(self, allure_dirs, monkeypatch):
        monkeypatch.setattr(generate_report, "_find_allure", lambda: None)
        assert generate_report.generate() == 1

    def test_missing_results_dir_returns_one(self, tmp_path, monkeypatch):
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure")
        monkeypatch.setattr(settings, "ALLURE_RESULTS_DIR", str(tmp_path / "not-exist"))
        monkeypatch.setattr(settings, "ALLURE_REPORT_DIR", str(tmp_path / "out"))
        assert generate_report.generate() == 1

    def test_empty_results_dir_returns_one(self, allure_dirs, monkeypatch):
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure")
        assert generate_report.generate() == 1            # 目录存在但没有任何结果文件

    def test_success_builds_command(self, allure_dirs, monkeypatch):
        results, report = allure_dirs
        (results / "abc-result.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure-bin")

        commands = []

        def fake_run(cmd):
            commands.append(cmd)
            os.makedirs(report, exist_ok=True)
            (report / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(generate_report, "_run", fake_run)
        assert generate_report.generate() == 0
        assert commands == [["allure-bin", "generate", str(results),
                             "-o", str(report), "--clean"]]

    def test_clean_removes_old_report(self, allure_dirs, monkeypatch):
        results, report = allure_dirs
        (results / "abc-result.json").write_text("{}", encoding="utf-8")
        report.mkdir()
        (report / "old.txt").write_text("old", encoding="utf-8")
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure-bin")
        monkeypatch.setattr(generate_report, "_run", lambda cmd: None)

        generate_report.generate(clean=True)
        assert not (report / "old.txt").exists()

    def test_keep_old_report_without_clean_flag(self, allure_dirs, monkeypatch):
        results, report = allure_dirs
        (results / "abc-result.json").write_text("{}", encoding="utf-8")
        report.mkdir()
        (report / "old.txt").write_text("old", encoding="utf-8")
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure-bin")
        monkeypatch.setattr(generate_report, "_run", lambda cmd: None)

        generate_report.generate(clean=False)
        assert (report / "old.txt").exists()

    def test_open_browser_starts_local_server(self, allure_dirs, monkeypatch):
        """--open 应在生成后调用 allure open（用本地服务避免 file:// 限制）。"""
        results, report = allure_dirs
        (results / "abc-result.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure-bin")

        commands = []

        def fake_run(cmd):
            commands.append(cmd)
            os.makedirs(report, exist_ok=True)
            (report / "index.html").write_text("<html></html>", encoding="utf-8")

        monkeypatch.setattr(generate_report, "_run", fake_run)
        assert generate_report.generate(open_browser=True) == 0
        assert commands[-1] == ["allure-bin", "open", str(report)]

    def test_command_failure_returns_nonzero(self, allure_dirs, monkeypatch):
        import subprocess
        results, _ = allure_dirs
        (results / "abc-result.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(generate_report, "_find_allure", lambda: "allure-bin")

        def boom(cmd):
            raise subprocess.CalledProcessError(3, cmd)

        monkeypatch.setattr(generate_report, "_run", boom)
        assert generate_report.generate() != 0
