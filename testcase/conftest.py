# -*- coding: utf-8 -*-
"""
pytest 全局配置（conftest.py）
=============================
pytest 会自动加载本文件，无需手动 import。职责：
    1. 注册自定义 marker（避免告警，并支持 -m 筛选）
    2. 补全 Allure 结果目录，使「直接运行 pytest」也能产出 Allure 原始数据
    3. 会话开始 / 结束钩子：清空变量池、写入报告环境信息（含执行元数据）、
       结果落盘、汇总后置清理失败
    4. 提供跨用例复用的 fixture

运行示例：
    pytest                              # 按 conf.ini 配置执行（默认产出 Allure 数据）
    pytest -m excel                     # 只跑 Excel 数据驱动用例
    pytest -m "not network"             # 跳过依赖真实环境的用例
    python main.py --report both        # 同时产出 Allure 与 HTML 报告
"""
import pytest

from api.base_api import TEARDOWN_FAIL_PREFIX, BaseApi
from common import mask, metadata
from common.profile import load_profile
from common.variable import GlobalVar
from config import settings
from utils import allureutil
from utils.excelutil import ExcelUtil
from utils.logutil import logger


# ----------------------------------------------------------------------
# 一、会话初始化
# ----------------------------------------------------------------------
def pytest_configure(config):
    """注册 marker，并按配置补全 Allure 结果目录。"""
    config.addinivalue_line("markers", "excel: Excel 数据驱动用例")
    config.addinivalue_line("markers", "yaml: YAML 数据驱动用例")
    config.addinivalue_line("markers", "mysql: MySQL 数据驱动用例")
    config.addinivalue_line("markers", "network: 依赖真实服务环境的用例")
    config.addinivalue_line("markers", "smoke: 冒烟用例（CI/CD 构建后快速验证）")

    # 需要 Allure 报告且命令行未指定 --alluredir 时，补上项目内默认目录
    if settings.RunConfig.REPORT_TYPE in ("allure", "both"):
        if not getattr(config.option, "allure_report_dir", None):
            config.option.allure_report_dir = settings.ALLURE_RESULTS_DIR


def pytest_collection_modifyitems(config, items):
    """
    按 conf.ini 的 [run] data_source 加载对应的数据驱动用例。

    规则（与 docs/02-操作手册.md「切换数据源」一致）：

        1. 命令行显式给了 -m 或 -k —— 以用户为准，**不按 data_source 过滤**。
           这是「临时只跑某一种数据源 / 某一批用例」的快捷方式，优先级最高。
        2. 否则按 data_source 只保留对应驱动的用例：
               excel    只跑 Excel 驱动
               yaml     只跑 YAML 驱动
               mysql    只跑 MySQL 驱动
               all      同时跑 Excel 与 YAML（兼容早期版本行为）
        3. 非数据驱动用例（PO 风格手写用例，如 testcase/test_login.py）不受影响。

    取值非法时直接报错，避免「配置写错了却悄悄按默认跑」——
    那会让人以为用例被跳过了，其实是配置没生效。
    """
    markexpr = getattr(config.option, "markexpr", "") or ""
    keyword = getattr(config.option, "keyword", "") or ""
    if markexpr or keyword:
        return

    source = settings.resolve_data_source()
    if source and source not in settings.VALID_DATA_SOURCES:
        raise pytest.UsageError(
            "conf.ini [run] data_source 取值非法：'{}'\n"
            "  可选值：{}".format(source, " | ".join(settings.VALID_DATA_SOURCES)))

    keep_marker = settings.data_source_marker()
    if keep_marker is None:                       # all / 空：不做限制
        return

    driver_markers = set(settings.DATA_SOURCE_MARKERS.values())
    kept = []
    for item in items:
        own = {mark.name for mark in item.iter_markers()}
        if not (own & driver_markers) or item.get_closest_marker(keep_marker) is not None:
            kept.append(item)                     # 非驱动用例，或命中所选驱动
    dropped = len(items) - len(kept)
    if dropped:
        logger.info("按 data_source={} 过滤：保留 {} 条，过滤掉 {} 条其它数据源用例".format(
            source, len(kept), dropped))
    items[:] = kept


def pytest_sessionstart(session):
    """整个测试会话开始前执行一次。"""
    GlobalVar.clear()                     # 清空变量池，避免上次运行残留的脏数据

    need_allure = settings.RunConfig.REPORT_TYPE in ("allure", "both")

    # 报告「环境」页信息（标题/项目名取自 conf.ini [report]，不再写死）
    run_mode = ("冒烟（标签 {}）".format(settings.RunConfig.TAGS)
                if settings.RunConfig.SMOKE_ONLY else "全量")
    env_info = {
        "项目": settings.ReportConfig.PROJECT,
        "报告标题": settings.ReportConfig.TITLE,
        "测试环境": settings.RunConfig.ENV,
        "执行模式": run_mode,
        "数据源": settings.RunConfig.DATA_SOURCE,
        "结果回写": str(settings.RunConfig.WRITE_BACK),
        "Allure可用": str(allureutil.ALLURE_AVAILABLE),
    }
    # 系统适配信息（主域名 / 域名别名 / 响应判定规则 / 认证方式 / 钩子）——
    # 换被测系统时，从报告首页一眼就能看出本次跑的是哪套适配规则
    env_info.update(load_profile().describe())

    # 执行元数据（构建号 / git 提交 / 分支 / Python 与依赖版本）——
    # 报告被单独转发或归档后，仍能确认「这份报告对应哪次构建、哪次提交」
    env_info.update(metadata.collect())

    # 敏感信息脱敏状态也写进报告：看到报告的人需要知道口令类字段是打过码的
    env_info["敏感信息脱敏"] = "开启（{}）".format(settings.MaskConfig.MODE) \
        if settings.MaskConfig.ENABLED else "关闭"

    # 仅在需要 Allure 报告时写盘；--report none / --collect-only 不产生任何文件
    if need_allure:
        allureutil.write_environment(settings.ALLURE_RESULTS_DIR, env_info)

    logger.info("=" * 70)
    for key, value in env_info.items():
        logger.info("{} : {}".format(key, value))
    logger.info("=" * 70)


def pytest_sessionfinish(session, exitstatus):
    """整个测试会话结束后执行一次：把缓存的结果统一落盘，并汇总后置清理失败。"""
    if settings.RunConfig.WRITE_BACK:
        ExcelUtil.flush()
    _warn_teardown_failures()
    _sanitize_reports()
    logger.info("测试会话结束，exitstatus = {}".format(exitstatus))


def _sanitize_reports():
    """
    对报告目录做一次「落盘后兜底脱敏」。

    为什么必须兜这一层：
        Allure 的 pytest 插件会把 `@pytest.mark.parametrize` 的每个参数
        自动写成报告参数，而框架传的是**整条用例数据**
        （形如 `case = "{'password': 'demo_password'}"`）。
        这条路径由插件直接落盘，不经过框架的 `attach_*`；
        若不兜一遍，构建制品里仍会残留明文口令。
    """
    changed = mask.sanitize_dir(settings.REPORT_DIR)
    if changed:
        logger.info("报告产物脱敏完成：{} 个文件已打码".format(changed))


def _warn_teardown_failures():
    """
    汇总「后置清理失败」的用例并告警。

    为什么不能只在单条用例里记一行 error 日志：
        teardown 失败不影响用例结论，于是整轮跑完可能「全绿」，
        但被测系统里已经躺着脏数据 —— 下一次构建会因此出现莫名其妙的失败，
        而那时已经看不到原始线索了。会话级汇总能把这件事明确摆到台面上。
    """
    failed = {key[len(TEARDOWN_FAIL_PREFIX):]: value
              for key, value in GlobalVar.all().items()
              if key.startswith(TEARDOWN_FAIL_PREFIX)}
    if not failed:
        return

    logger.warning("=" * 70)
    logger.warning("有 {} 条用例的后置清理失败，被测系统可能残留脏数据：".format(len(failed)))
    for case_id, reason in sorted(failed.items()):
        logger.warning("    用例 id={} -> {}".format(case_id, reason))
    logger.warning("提示：用例结论不受影响，但请人工确认这些数据是否需要清理。")
    logger.warning("=" * 70)


# ----------------------------------------------------------------------
# 二、公共 fixture
# ----------------------------------------------------------------------
@pytest.fixture(scope="session")
def api_client():
    """
    会话级通用接口对象：整个测试会话复用同一个 session（连接复用）。

    需要自定义域名或公共请求头时，可在用例中直接实例化具体接口对象，
    例如 LoginApi(base_url="http://xxx")。
    """
    return BaseApi()
