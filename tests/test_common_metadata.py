# -*- coding: utf-8 -*-
"""
单元测试：common/metadata.py（执行元数据）
==========================================
守护的目标：报告必须能回答「跑的是哪个版本、在哪条流水线上跑的」。

这些信息全部「尽力而为」（无 git、无对应环境变量时降级），
因此测试重点不是「一定能拿到」，而是：
    1. 采集过程绝不抛异常
    2. 有 git / 有 CI 环境变量时必须能识别出来
    3. 结果带缓存，不重复起子进程
"""
import pytest

from common import metadata


@pytest.fixture(autouse=True)
def _clear_cache():
    """每个用例前后清缓存，避免用例之间互相串结果。"""
    metadata.clear_cache()
    yield
    metadata.clear_cache()


class TestCollect:
    def test_returns_dict_with_time_and_location(self):
        info = metadata.collect()
        assert isinstance(info, dict)
        assert info["执行时间"]
        assert info["运行位置"] in ("本地", "CI 流水线")

    def test_runtime_info_always_present(self):
        info = metadata.collect()
        assert info["Python 版本"]
        assert info["操作系统"]
        assert info["机器架构"]

    def test_result_is_cached(self):
        first = metadata.collect()
        second = metadata.collect()
        assert first["执行时间"] == second["执行时间"]

    def test_force_recollect(self):
        first = metadata.collect()
        second = metadata.collect(force=True)
        assert set(first) == set(second)


class TestGitInfo:
    def test_never_raises(self):
        assert isinstance(metadata.git_info(), dict)

    def test_keys_are_meaningful_when_available(self):
        info = metadata.git_info()
        if not info:                       # 未安装 git / 不在仓库 / 尚无提交
            pytest.skip("当前环境无可用 git 版本信息")
        assert info["Git 提交"]
        assert info["工作区"] in ("干净", "有未提交改动")


class TestCiInfo:
    def test_local_when_no_ci_vars(self, monkeypatch):
        for key in ("BUILD_NUMBER", "JENKINS_URL", "JENKINS_HOME", "GITLAB_CI",
                    "GITHUB_ACTIONS", "TF_BUILD", "CI", "JOB_NAME",
                    "CI_PROJECT_PATH", "BUILD_URL"):
            monkeypatch.delenv(key, raising=False)
        info = metadata.ci_info()
        assert info["运行位置"] == "本地"
        assert "构建号" not in info

    def test_jenkins_build_number_detected(self, monkeypatch):
        monkeypatch.setenv("JENKINS_URL", "http://jenkins.example.com")
        monkeypatch.setenv("BUILD_NUMBER", "128")
        monkeypatch.setenv("JOB_NAME", "amsapi-auto")
        monkeypatch.setenv("BUILD_URL", "http://jenkins.example.com/job/amsapi-auto/128/")
        info = metadata.ci_info()
        assert info["运行位置"] == "CI 流水线"
        assert info["构建号"] == "128"
        assert info["流水线任务"] == "amsapi-auto"
        assert info["构建地址"].startswith("http")

    def test_gitlab_pipeline_detected(self, monkeypatch):
        monkeypatch.delenv("BUILD_NUMBER", raising=False)
        monkeypatch.delenv("JOB_NAME", raising=False)
        monkeypatch.setenv("GITLAB_CI", "true")
        monkeypatch.setenv("CI_PIPELINE_ID", "2024")
        info = metadata.ci_info()
        assert info["运行位置"] == "CI 流水线"
        assert info["构建号"] == "2024"


class TestDependencyVersions:
    def test_includes_pytest(self):
        versions = metadata.dependency_versions()
        assert "pytest" in versions

    def test_unknown_package_skipped(self):
        """采集失败（未安装）时应跳过而不是报错。"""
        assert isinstance(metadata.dependency_versions(), dict)
