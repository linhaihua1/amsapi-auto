# -*- coding: utf-8 -*-
"""
Allure 报告生成脚本
===================
把 pytest 产出的 Allure 原始结果（report/allure-results）渲染为 HTML 报告
（report/allure-report）。

用法：
    python tools/generate_report.py             # 生成报告
    python tools/generate_report.py --clean     # 生成前清空历史报告目录
    python tools/generate_report.py --open      # 生成后启动本地服务并打开浏览器

前置条件：
    需安装 allure 命令行工具（allure-commandline，依赖 Java）。
    下载：https://github.com/allure-framework/allure2/releases
    校验：allure --version
"""
import argparse
import os
import shutil
import subprocess
import sys

# 允许脚本独立运行：把项目根加入模块搜索路径
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from config import settings  # noqa: E402


def _find_allure():
    """定位 allure 可执行文件（Windows 下通常是 allure.bat）。"""
    for name in ("allure", "allure.bat", "allure.cmd"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _run(cmd):
    """
    跨平台执行外部命令。
    Windows 下 .bat/.cmd 需借助 shell 才能被 CreateProcess 执行，故统一走 shell。
    """
    return subprocess.run(cmd, check=True, shell=(os.name == "nt"))


def generate(open_browser=False, clean=False):
    """
    生成 Allure HTML 报告。

    :param open_browser: 生成后是否启动本地服务打开浏览器
    :param clean:        生成前是否清空历史报告目录
    :return: 0 成功，非 0 失败
    """
    allure_bin = _find_allure()
    if not allure_bin:
        print("[错误] 未检测到 allure 命令，请先安装 allure-commandline：")
        print("       https://github.com/allure-framework/allure2/releases")
        print("       安装后执行 allure --version 验证。")
        return 1

    results_dir = settings.ALLURE_RESULTS_DIR
    report_dir = settings.ALLURE_REPORT_DIR

    if not os.path.isdir(results_dir) or not os.listdir(results_dir):
        print("[错误] 未找到 Allure 原始结果：{}".format(results_dir))
        print("       请先执行测试（python main.py）以生成结果。")
        return 1

    if clean and os.path.isdir(report_dir):
        shutil.rmtree(report_dir)
        print("已清空历史报告：{}".format(report_dir))

    cmd = [allure_bin, "generate", results_dir, "-o", report_dir, "--clean"]
    print("生成报告：{}".format(" ".join(cmd)))
    try:
        _run(cmd)
    except subprocess.CalledProcessError as exc:
        print("[错误] allure generate 执行失败：{}".format(exc))
        return exc.returncode or 1

    index_file = os.path.join(report_dir, "index.html")
    print("报告已生成：{}".format(index_file))

    if open_browser:
        # 用 allure open 启动本地服务，避免 file:// 加载限制
        print("启动本地服务查看报告（按 Ctrl+C 结束）...")
        _run([allure_bin, "open", report_dir])

    return 0


def main():
    parser = argparse.ArgumentParser(description="生成 Allure HTML 报告")
    parser.add_argument("--open", action="store_true", help="生成后启动本地服务并打开浏览器")
    parser.add_argument("--clean", action="store_true", help="生成前清空历史报告目录")
    args = parser.parse_args()

    sys.exit(generate(open_browser=args.open, clean=args.clean))


if __name__ == "__main__":
    main()
