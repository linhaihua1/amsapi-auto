# -*- coding: utf-8 -*-
"""
执行元数据（Metadata）
======================
回答企业级测试最基本的一个问题：**这份报告跑的是哪个版本、在哪条流水线上跑的？**

采集内容（全部「尽力而为」：任何一项取不到都不影响测试执行）：

    构建信息   流水线判定、构建号、构建地址、任务名
    代码版本   git 提交短哈希、分支、是否有未提交改动
    运行环境   Python 版本、操作系统、框架与关键依赖版本
    执行时间   本次会话开始时间

写入位置：Allure 报告的「环境」页（report/allure-results/environment.properties），
由 testcase/conftest.py 的 pytest_sessionstart 调用。

为什么必须做
------------
报告一旦脱离流水线被单独转发（拉群、邮件、归档），
没有这些信息就无法回答「这份报告对应哪次提交、哪次构建」，
失败复盘只能靠猜；出现「本地复现不了」时更无法确认两边跑的是不是同一份代码。
"""
import os
import platform
import subprocess
import time

from config import settings

# 结果缓存：git / 依赖版本这类信息在一次会话内不会变，
# 而 pytest_sessionstart 可能被多次调用（例如框架自测），不应重复起子进程。
_CACHE = {}

# 采集的关键依赖（缺失即跳过，不报错）
_DEPENDENCIES = ("pytest", "requests", "openpyxl", "PyYAML", "allure-pytest",
                 "PyMySQL", "pytest-html", "jsonschema", "cryptography")

# 常见 CI 平台的构建号 / 任务名环境变量（按优先级）
_CI_BUILD_VARS = ("BUILD_NUMBER", "GITLAB_CI_PIPELINE_ID", "CI_PIPELINE_ID",
                  "GITHUB_RUN_NUMBER", "BUILD_BUILDNUMBER", "TRAVIS_BUILD_NUMBER",
                  "CIRCLE_BUILD_NUM", "DRONE_BUILD_NUMBER")
_CI_JOB_VARS = ("JOB_NAME", "CI_PROJECT_PATH", "GITHUB_REPOSITORY",
                "BUILD_REPOSITORY_NAME", "CI_PROJECT_NAME")
_CI_URL_VARS = ("BUILD_URL", "CI_PIPELINE_URL", "GITHUB_SERVER_URL")


def _run_git(args, timeout=5):
    """
    执行一条 git 命令并返回去除首尾空白的输出；任何异常都返回 None。

    用 subprocess 而不是第三方库：不增加依赖，且在内网 / 无 git 环境下能优雅降级。
    """
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=settings.BASE_DIR,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if result.returncode != 0:
        return None
    try:
        return result.stdout.decode("utf-8", "ignore").strip()
    except AttributeError:                      # 理论上不会发生，兜底避免崩
        return None


def git_info():
    """
    代码版本信息。

    :return: {"Git 提交": "a1b2c3d", "Git 分支": "master", "工作区": "有未提交改动"}；
             不在 git 仓库 / 未安装 git 时返回空字典
    """
    commit = _run_git(["rev-parse", "--short", "HEAD"])
    if not commit:
        return {}

    info = {"Git 提交": commit}
    branch = _run_git(["rev-parse", "--abbrev-ref", "HEAD"])
    if branch:
        info["Git 分支"] = branch

    status = _run_git(["status", "--porcelain"])
    if status is not None:
        # 有未提交改动时必须显式写出来 —— 否则「报告对应的代码」是不可信的
        info["工作区"] = "有未提交改动" if status else "干净"
    return info


def ci_info():
    """流水线信息（构建号 / 任务名 / 构建地址）；本地运行时返回空字典。"""
    info = {}
    for key in _CI_BUILD_VARS:
        value = os.environ.get(key)
        if value:
            info["构建号"] = value
            break
    for key in _CI_JOB_VARS:
        value = os.environ.get(key)
        if value:
            info["流水线任务"] = value
            break
    for key in _CI_URL_VARS:
        value = os.environ.get(key)
        if value and value.startswith("http"):
            info["构建地址"] = value
            break
    # 显式标识当前是否处于 CI，便于区分「本地跑的报告」与「流水线报告」
    info["运行位置"] = "CI 流水线" if any(
        os.environ.get(key) for key in settings.CIConfig.DETECT_ENV_VARS) else "本地"
    return info


def dependency_versions():
    """关键依赖版本；未安装的直接跳过（可选依赖不算错）。"""
    versions = {}
    try:
        from importlib import metadata as importlib_metadata
    except ImportError:                          # Python 3.7 及更早
        return versions

    for name in _DEPENDENCIES:
        try:
            versions[name] = importlib_metadata.version(name)
        except Exception:                        # noqa: BLE001 —— 包元数据异常不该影响测试
            continue
    return versions


def runtime_info():
    """运行环境信息（Python / 操作系统 / 机器架构）。"""
    return {
        "Python 版本": platform.python_version(),
        "操作系统": "{} {}".format(platform.system(), platform.release()).strip(),
        "机器架构": platform.machine() or "未知",
    }


def collect(force=False):
    """
    采集全部执行元数据（带进程内缓存）。

    :param force: 忽略缓存重新采集（单元测试需要隔离状态时使用）
    :return: 有序字典（键为中文，便于直接在 Allure 环境页展示）
    """
    if not force and _CACHE:
        return dict(_CACHE)

    info = {"执行时间": time.strftime("%Y-%m-%d %H:%M:%S")}
    info.update(ci_info())
    info.update(git_info())
    info.update(runtime_info())
    for name, version in sorted(dependency_versions().items()):
        info["依赖 {}".format(name)] = version

    _CACHE.clear()
    _CACHE.update(info)
    return dict(info)


def clear_cache():
    """清空缓存（单元测试隔离，或运行期需要重新采集时使用）。"""
    _CACHE.clear()
