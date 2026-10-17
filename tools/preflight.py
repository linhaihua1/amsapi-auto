# -*- coding: utf-8 -*-
"""
环境预检（Preflight）
=====================
在**执行用例之前**把「环境能不能跑」一次性确认清楚，避免把环境问题
表现为一堆用例失败 —— 后者会让排查从「看环境」变成「读业务断言」，
在 CI 上尤其费时间。

检查项（分三档：错误 / 警告 / 提示）：

    [错误] Python 版本过低（低于项目下限 3.7）
    [错误] 必需依赖缺失（pytest / requests / openpyxl / PyYAML）
    [错误] 配置项非法（数据源取值、超时非数字等）
    [错误] 指定的系统适配档案不存在
    [错误] 用例数据不可读（Excel 文件 / sheet 缺失，YAML 目录为空）
    [错误] 日志 / 报告目录不可写
    [警告] 被测域名不可达（TCP 连接超时或拒绝）
    [警告] 目标为内网地址但存在系统代理且未开启自动绕过
    [警告] 未安装可选依赖（allure-pytest / PyMySQL / jsonschema / cryptography）
    [提示] 本次生效的关键配置（数据源 / 档案 / 域名 / 超时 / 脱敏状态）

用法：
    python tools/preflight.py                 # 完整预检（含目标可达性）
    python tools/preflight.py --no-target     # 跳过网络可达性检查
    python tools/preflight.py --strict        # 有警告也返回非 0（用于把守门禁）
    python tools/preflight.py --json          # 以 JSON 输出（供流水线解析）

退出码：0 = 可以执行；1 = 存在阻断性问题（或 --strict 下存在警告）。
"""
import argparse
import importlib
import json
import os
import socket
import sys
from urllib.parse import urlparse

# 允许从任意工作目录直接运行本脚本
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings                                        # noqa: E402

# 必需依赖（缺失即无法执行）
REQUIRED_PACKAGES = ("pytest", "requests", "openpyxl", "yaml")
# 可选依赖（缺失只降级：Allure 报告 / MySQL 数据源 / schema 断言 / 加解密钩子）
OPTIONAL_PACKAGES = (("allure", "allure-pytest", "Allure 附件与步骤"),
                     ("pymysql", "PyMySQL", "MySQL 数据源与数据库断言"),
                     ("jsonschema", "jsonschema", "expects 的 schema 断言"),
                     ("cryptography", "cryptography", "AES 加解密 / RSA 签名钩子"))

LEVEL_ERROR = "错误"
LEVEL_WARN = "警告"
LEVEL_INFO = "提示"


class Report:
    """预检结果收集器（便于同时输出给人看与给流水线解析）。"""

    def __init__(self):
        self.items = []

    def add(self, level, title, detail=""):
        self.items.append({"level": level, "title": title, "detail": detail})

    def error(self, title, detail=""):
        self.add(LEVEL_ERROR, title, detail)

    def warn(self, title, detail=""):
        self.add(LEVEL_WARN, title, detail)

    def info(self, title, detail=""):
        self.add(LEVEL_INFO, title, detail)

    @property
    def errors(self):
        return [item for item in self.items if item["level"] == LEVEL_ERROR]

    @property
    def warnings(self):
        return [item for item in self.items if item["level"] == LEVEL_WARN]

    def render(self):
        """渲染成给人看的文本报告。"""
        icon = {LEVEL_ERROR: "[错误]", LEVEL_WARN: "[警告]", LEVEL_INFO: "[提示]"}
        lines = ["=" * 72, "环境预检（preflight）", "=" * 72]
        for item in self.items:
            head = "{} {}".format(icon.get(item["level"], "[-]"), item["title"])
            lines.append(head)
            if item["detail"]:
                for line in str(item["detail"]).splitlines():
                    lines.append("        {}".format(line))
        lines.append("-" * 72)
        lines.append("汇总：{} 个错误，{} 个警告".format(len(self.errors), len(self.warnings)))
        if self.errors:
            lines.append("结论：存在阻断性问题，请先修复后再执行用例。")
        elif self.warnings:
            lines.append("结论：可以执行，但建议关注上述警告。")
        else:
            lines.append("结论：环境检查全部通过。")
        lines.append("=" * 72)
        return "\n".join(lines)


# ----------------------------------------------------------------------
# 各项检查
# ----------------------------------------------------------------------
def check_python(report):
    version = sys.version_info
    if version < (3, 7):
        report.error("Python 版本过低：{}.{}".format(version[0], version[1]),
                     "项目要求 Python 3.7+（建议 3.10+），当前解释器：{}".format(sys.executable))
    elif version < (3, 10):
        report.info("Python {}.{}（可用，建议升级到 3.10+）".format(version[0], version[1]))
    else:
        report.info("Python {}.{}.{}".format(version[0], version[1], version[2]))


def check_packages(report):
    missing_required = []
    for name in REQUIRED_PACKAGES:
        try:
            importlib.import_module(name)
        except ImportError:
            missing_required.append(name)
    if missing_required:
        report.error("必需依赖缺失：{}".format(", ".join(missing_required)),
                     "请执行：pip install -r requirements.txt")

    missing_optional = []
    for module, package, purpose in OPTIONAL_PACKAGES:
        try:
            importlib.import_module(module)
        except ImportError:
            missing_optional.append("{}（{}）".format(package, purpose))
    if missing_optional:
        report.warn("可选依赖未安装，相关能力自动降级：",
                    "\n".join(missing_optional) + "\n安装：pip install -r requirements-dev.txt")


def check_runtime_config(report):
    """配置合法性：数据源取值、超时、系统档案。"""
    source = settings.resolve_data_source()
    if source and source not in settings.VALID_DATA_SOURCES:
        report.error("conf.ini [run] data_source 取值非法：'{}'".format(source),
                     "可选值：{}".format(" | ".join(settings.VALID_DATA_SOURCES)))

    if int(settings.RunConfig.TIMEOUT or 0) <= 0:
        report.error("请求超时配置非法：{}".format(settings.RunConfig.TIMEOUT),
                     "请检查 conf.ini [run] timeout 或 AMSAPI_TIMEOUT")

    from common.exceptions import ConfigError
    from common.profile import available_systems, load_profile
    try:
        profile = load_profile(force=True)
    except ConfigError as exc:
        report.error("系统适配档案不可用", str(exc))
        return None
    report.info("系统适配档案：{}（{}）".format(profile.name, profile.title),
                "主域名：{}\n响应判定：{} / 认证：{}".format(
                    profile.effective_base_url or "(用例自带完整地址)",
                    settings_label(profile), profile.auth.name))
    if not os.path.exists(os.path.join(settings.SYSTEMS_DIR, profile.name + ".ini")) \
            and profile.name != "default":
        report.warn("系统适配档案 '{}' 无对应文件，正在使用内置默认行为".format(profile.name))
    if available_systems():
        report.info("可用档案：{}".format(", ".join(available_systems())))
    return profile


def settings_label(profile):
    """档案的响应判定摘要（供提示信息展示）。"""
    try:
        return profile.response.style
    except AttributeError:
        return "unknown"


def check_case_data(report):
    """用例数据可读性：按当前数据源检查对应数据文件。"""
    source = settings.resolve_data_source()
    if source in ("excel", "all", ""):
        try:
            from utils.excelutil import ExcelUtil
            cases = ExcelUtil().read_cases(only_runnable=True)
            if not cases:
                report.warn("Excel 中没有可执行用例（检查 isdel 列是否为 1）",
                            "文件：{}".format(settings.EXCEL_FILE))
            else:
                report.info("Excel 可执行用例：{} 条".format(len(cases)),
                            "文件：{}".format(settings.EXCEL_FILE))
        except Exception as exc:                       # noqa: BLE001 —— 预检本身不能崩
            report.error("Excel 用例读取失败", "{}: {}".format(type(exc).__name__, exc))

    if source in ("yaml", "all"):
        try:
            from utils.yamlutil import read_cases
            cases = read_cases()
            if not cases:
                report.warn("YAML 用例目录为空", "目录：{}".format(settings.CASES_DIR))
            else:
                report.info("YAML 用例：{} 条".format(len(cases)),
                            "目录：{}".format(settings.CASES_DIR))
        except Exception as exc:                       # noqa: BLE001
            report.error("YAML 用例读取失败", "{}: {}".format(type(exc).__name__, exc))

    if source == "mysql":
        missing = settings.missing_db_keys()
        if missing:
            report.error("MySQL 数据源未配置（缺少：{}）".format(", ".join(missing)),
                         "请在 conf.ini [db] 填写或注入 AMSAPI_DB_* 环境变量")
        else:
            report.info("MySQL 数据源已配置：{}:{}".format(
                settings.DB_CONFIG.get("host"), settings.DB_CONFIG.get("port")))


def check_writable_dirs(report):
    """日志与报告目录必须可写，否则跑完拿不到任何产物。"""
    for label, path in (("日志目录", settings.LOG_DIR), ("报告目录", settings.REPORT_DIR)):
        try:
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, ".preflight-probe")
            with open(probe, "w", encoding="utf-8") as fp:
                fp.write("ok")
            os.remove(probe)
        except OSError as exc:
            report.error("{}不可写：{}".format(label, path), str(exc))


def check_proxy(report, target_url):
    """
    代理提示。

    这是国内企业环境的高频坑：CI 机器配了「出公网」代理，
    而访问内网被测系统的请求被代理拦下，表现为 502 或连接失败，
    报错信息完全指不到代理这一层。
    """
    proxy_vars = {key: value for key, value in os.environ.items()
                  if key.lower() in ("http_proxy", "https_proxy", "all_proxy") and value}
    if not proxy_vars:
        return

    from utils.requestsutil import is_internal_host
    host = urlparse(target_url or "").hostname or ""
    internal = is_internal_host(host)

    if internal and settings.NetworkConfig.TRUST_ENV \
            and not settings.NetworkConfig.AUTO_BYPASS_PROXY:
        report.warn("目标为内网地址，但「自动绕过代理」已关闭",
                    "存在系统代理：{}\n内网请求很可能被代理拦截（表现为 502 / 连接失败）\n"
                    "建议：conf.ini [network] auto_bypass_proxy = true".format(
                        ", ".join(sorted(proxy_vars))))
    elif internal:
        report.info("检测到系统代理，但目标为本机 / 内网地址，框架将自动绕过",
                    "代理：{}".format(", ".join(sorted(proxy_vars))))
    else:
        report.info("检测到系统代理，目标为公网地址，将沿用系统代理",
                    "代理：{}".format(", ".join(sorted(proxy_vars))))


def check_target(report, target_url):
    """目标可达性（TCP 连接）。这一步能提前暴露「域名写错 / 服务没起」。"""
    if not target_url:
        report.warn("未配置被测域名（[env] base_url 为空）",
                    "用例需自带完整地址；CI 中建议用 AMSAPI_BASE_URL 注入")
        return
    parsed = urlparse(target_url if "://" in target_url else "http://" + target_url)
    host = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not host:
        report.error("被测域名无法解析：{}".format(target_url))
        return

    try:
        with socket.create_connection((host, port), timeout=5):
            report.info("目标可达：{}:{}".format(host, port))
    except OSError as exc:
        report.warn("目标不可达：{}:{}".format(host, port),
                    "{}: {}\n如为内网地址，请确认已连接内网 / VPN。".format(type(exc).__name__, exc))


def run(no_target=False, strict=False):
    """执行全部预检，返回 (Report, 退出码)。"""
    report = Report()

    check_python(report)
    check_packages(report)
    profile = check_runtime_config(report)
    check_case_data(report)
    check_writable_dirs(report)

    target_url = (settings.RunConfig.BASE_URL or (profile.effective_base_url if profile else "") or "")
    check_proxy(report, target_url)
    if not no_target:
        check_target(report, target_url)

    report.info("生效配置",
                "环境：{}\n数据源：{}\n档案：{}\n结果回写：{}\n脱敏：{}（{}）".format(
                    settings.RunConfig.ENV, settings.RunConfig.DATA_SOURCE,
                    settings.RunConfig.SYSTEM, settings.RunConfig.WRITE_BACK,
                    "开启" if settings.MaskConfig.ENABLED else "关闭",
                    settings.MaskConfig.MODE))

    failed = bool(report.errors) or (strict and bool(report.warnings))
    return report, (1 if failed else 0)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="执行用例前的环境预检（依赖 / 配置 / 数据 / 网络 / 可写性）")
    parser.add_argument("--no-target", action="store_true",
                        help="跳过被测域名可达性检查（离线环境使用）")
    parser.add_argument("--strict", action="store_true",
                        help="有警告也返回非 0（用于把守 CI 门禁）")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    report, code = run(no_target=args.no_target, strict=args.strict)

    if args.json:
        print(json.dumps({"exit_code": code, "items": report.items}, ensure_ascii=False, indent=2))
    else:
        print(report.render())
    return code


if __name__ == "__main__":
    sys.exit(main())
