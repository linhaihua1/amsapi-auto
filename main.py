# -*- coding: utf-8 -*-
"""
测试入口
========
统一启动脚本，等价于在项目根目录执行 pytest，并按需生成报告。

用法：
    python main.py                          # 按 conf.ini 执行全部用例（报告类型由 conf.ini 决定）
    python main.py --smoke                  # 只执行冒烟用例（CI/CD 构建后快速验证）
    python main.py --report allure          # 生成 Allure 报告（非 CI 环境下自动渲染 HTML）
    python main.py --report html            # 只生成 pytest-html 报告
    python main.py --report both            # 同时生成 Allure 与 HTML
    python main.py --report none            # 不生成任何报告
    python main.py -m excel                 # 只跑 Excel 数据驱动用例（marker 优先于 data_source）
    python main.py -m yaml                  # 只跑 YAML 数据驱动用例
    python main.py -m "not network"         # 跳过依赖真实服务环境的用例
    python main.py -k login                 # 只跑名称含 login 的用例
    python main.py --collect-only           # 只收集用例不执行（完全只读，不改任何文件）

数据源（conf.ini 的 [run] data_source，或用 AMSAPI_DATA_SOURCE 覆盖）：
    excel / yaml / mysql   只运行该数据源的用例
    all                    同时运行 Excel 与 YAML 驱动
    注：命令行显式给了 -m 或 -k 时，以命令行为准，data_source 不再参与过滤。

报告位置：
    Allure 原始数据 report/allure-results  -> 渲染后的 HTML 在 report/allure-report
    pytest-html    report/report.html

CI/CD 说明：
    1. 检测到 CI 环境（JENKINS_URL / GITLAB_CI / BUILD_NUMBER / CI 等）时，
       默认跳过本地 HTML 渲染——流水线通常由 Allure 插件基于 allure-results 渲染，
       可显著缩短构建时长。如需强制渲染，设置 AMSAPI_RENDER_ALLURE=1。
    2. 流水线中推荐用环境变量而非修改配置文件来切换环境，例如：
           AMSAPI_ENV=uat AMSAPI_BASE_URL=https://api.example.com AMSAPI_WRITE_BACK=false
    3. 退出码即 pytest 退出码：0 全部通过，非 0 视为失败，可直接用于流水线判定。
"""
import os
import sys

import pytest

from common import mask
from config import settings

# 支持的报告类型
VALID_REPORT_TYPES = ("allure", "html", "both", "none")

# 常见 CI 环境变量（存在任意一个即认为运行在流水线中）。
# 清单可在 conf.ini 的 [ci] detect_env_vars 中调整，代码不再写死。
CI_ENV_KEYS = settings.CIConfig.DETECT_ENV_VARS


def _is_ci():
    """判断当前是否运行在 CI/CD 流水线中。"""
    return any(os.environ.get(key) for key in CI_ENV_KEYS)


def _apply_smoke_marker(pytest_args):
    """
    把 smoke 条件合并进 pytest 的 -m 表达式。

    数据驱动用例（Excel / YAML）在冒烟模式下会自动为整个模块打上 smoke 标记，
    这里再统一加一层筛选，可同时排除未标记的 PO 风格用例与 SQL 驱动用例。
    若用户已传 -m，则与其条件做「与」合并，而不是覆盖。

    :param pytest_args: 原始 pytest 参数
    :return: 合并后的参数列表
    """
    args = list(pytest_args)

    # 形式一：-m expr
    if "-m" in args:
        index = args.index("-m")
        if index + 1 < len(args):
            args[index + 1] = "({}) and smoke".format(args[index + 1])
        else:
            args.append("smoke")
        return args

    # 形式二：-m=expr
    for index, arg in enumerate(args):
        if isinstance(arg, str) and arg.startswith("-m="):
            args[index] = "-m=({}) and smoke".format(arg.split("=", 1)[1])
            return args

    # 未指定 -m：直接追加
    return args + ["-m", "smoke"]


def _parse_args(argv):
    """
    分离「自定义参数」与「透传给 pytest 的参数」。

    :return: (报告类型, 是否冒烟模式, pytest 参数列表)
    """
    report_type = settings.RunConfig.REPORT_TYPE
    smoke = settings.RunConfig.SMOKE_ONLY
    pytest_args = []

    index = 0
    while index < len(argv):
        arg = argv[index]

        if arg == "--report":
            if index + 1 >= len(argv):
                print("[错误] --report 需指定类型：{}".format(" | ".join(VALID_REPORT_TYPES)))
                sys.exit(2)
            report_type = argv[index + 1]
            index += 2
        elif arg.startswith("--report="):
            report_type = arg.split("=", 1)[1]
            index += 1
        elif arg == "--smoke":
            smoke = True
            index += 1
        else:
            pytest_args.append(arg)
            index += 1

    report_type = str(report_type).strip().lower()
    if report_type not in VALID_REPORT_TYPES:
        print("[错误] 不支持的报告类型：{}（可选：{}）".format(report_type, " | ".join(VALID_REPORT_TYPES)))
        sys.exit(2)

    return report_type, smoke, pytest_args


def build_pytest_args(report_type, smoke, pytest_args):
    """
    组装最终交给 pytest 的参数列表（纯函数，便于单测覆盖）。

    :param report_type: 报告类型（allure | html | both | none）
    :param smoke:       是否冒烟模式
    :param pytest_args: 用户透传给 pytest 的参数
    :return: 新的参数列表（不修改入参）
    """
    args = list(pytest_args)

    # 需要 HTML 报告时补上 pytest-html 参数（文件名可在 conf.ini [report] html_name 中配置）
    if report_type in ("html", "both"):
        # 必须写成 --html=<路径>（等号连写），不能写成 `--html <路径>`（分离式）。
        # 原因：pytest 在很早的 _initini 阶段解析命令行时，pytest-html 的 --html
        # 选项尚未注册，分离式写法中的「路径」会被 argparse 当成一个位置参数，
        # 也就是被误认为「用例路径」。而本框架的用例目录是靠 pytest.ini 的
        # testpaths 定位的（命令行本身不带位置参数），于是：
        #     第一次运行（report.html 还不存在）→ 路径被过滤掉，一切正常；
        #     第二次运行（report.html 已存在）→ 该路径成为收集入口，rootdir
        #         被上翻到公共父目录、pytest.ini 不再生效、收集范围扩大到整个
        #         上层目录，最终以 UsageError 退出（退出码 4，日志表现为
        #         "rootdir: C:\Users" 且 "collected 1001 items"）。
        # 等号连写只是一个 token，不产生位置参数，从而彻底规避该问题。
        args.append("--html={}".format(settings.ReportConfig.html_path()))
        args.append("--self-contained-html")

    # 冒烟模式：追加 marker 筛选，确保只执行冒烟用例
    if smoke:
        args = _apply_smoke_marker(args)

    return args


def _render_allure_report():
    """
    调用 tools/generate_report.py 渲染 Allure HTML 报告。
    未安装 allure 命令行工具时仅提示，不影响测试结果。
    """
    tools_dir = os.path.join(settings.BASE_DIR, "tools")
    if tools_dir not in sys.path:
        sys.path.insert(0, tools_dir)
    try:
        import generate_report
        return generate_report.generate(open_browser=False, clean=True)
    except Exception as exc:                        # noqa: BLE001 —— 报告渲染失败不应影响测试结论
        print("[提示] Allure 报告渲染失败：{}".format(exc))
        print("       可稍后手动执行：python tools/generate_report.py")
        return 1


def main():
    # 切到项目根目录，保证 pytest 能找到 pytest.ini 与 testpaths
    os.chdir(settings.BASE_DIR)

    report_type, smoke, pytest_args = _parse_args(sys.argv[1:])

    # 写入配置，供 conftest 与各 driver 判断报告类型 / 是否冒烟
    settings.RunConfig.REPORT_TYPE = report_type
    settings.RunConfig.SMOKE_ONLY = smoke

    # 只收集不执行（--collect-only）：不产出报告，避免用没有结果的数据覆盖历史报告
    collect_only = any(arg in ("--collect-only", "--co") for arg in pytest_args)
    if collect_only:
        report_type = "none"
        settings.RunConfig.REPORT_TYPE = report_type

    # 拼装 pytest 参数：报告参数 + 冒烟筛选
    pytest_args = build_pytest_args(report_type, smoke, pytest_args)

    in_ci = _is_ci()

    print("=" * 70)
    print("{} 启动".format(settings.ReportConfig.TITLE))
    print("项目根目录 : {}".format(settings.BASE_DIR))
    print("运行环境   : {}".format(settings.RunConfig.ENV))
    print("系统档案   : {}".format(settings.RunConfig.SYSTEM))
    print("执行模式   : {}".format(
        "冒烟（标签 {}）".format(settings.RunConfig.TAGS) if smoke else "全量"))
    print("数据源     : {}".format(settings.RunConfig.DATA_SOURCE))
    print("结果回写   : {}".format(settings.RunConfig.WRITE_BACK))
    print("敏感脱敏   : {}".format(
        "开启（{}）".format(settings.MaskConfig.MODE) if settings.MaskConfig.ENABLED else "关闭"))
    print("CI 环境    : {}".format("是" if in_ci else "否"))
    print("报告类型   : {}".format(report_type + ("（仅收集用例，不产出报告）" if collect_only else "")))
    if report_type in ("allure", "both"):
        print("Allure 数据: {}".format(settings.ALLURE_RESULTS_DIR))
    if report_type in ("html", "both"):
        print("HTML 报告  : {}".format(settings.ReportConfig.html_path()))
    print("pytest 参数: {}".format(pytest_args or "(默认)"))
    print("=" * 70)

    exit_code = pytest.main(pytest_args)

    # 跑完按需渲染 Allure HTML 报告
    if report_type in ("allure", "both"):
        if in_ci and os.environ.get("AMSAPI_RENDER_ALLURE") != "1":
            print("[提示] 检测到 CI 环境，跳过本地 HTML 渲染。")
            print("       原始数据已产出：{}".format(settings.ALLURE_RESULTS_DIR))
            print("       如需本地渲染，设置 AMSAPI_RENDER_ALLURE=1 或执行 python tools/generate_report.py")
        else:
            _render_allure_report()

    # 最终兜底脱敏：报告中可能含第三方插件直接落盘的内容
    # （如 allure-pytest 把 parametrize 的整条用例写成报告参数），
    # 渲染完成后再统一扫一遍，确保**归档出去的制品里没有明文口令 / 令牌**。
    _sanitize_reports()

    print("=" * 70)
    print("测试结束，退出码 = {}（0 表示全部通过）".format(exit_code))
    print("=" * 70)

    sys.exit(exit_code)


def _sanitize_reports():
    """报告目录落盘后兜底脱敏（重复执行无副作用；脱敏关闭时不做任何事）。"""
    try:
        mask.sanitize_dir(settings.REPORT_DIR)
    except Exception:                     # 兜底动作绝不能影响退出码
        pass


if __name__ == "__main__":
    main()
