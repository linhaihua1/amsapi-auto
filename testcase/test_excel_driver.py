# -*- coding: utf-8 -*-
"""
Excel 数据驱动用例
==================
从 data/api_tables.xlsx 的 test_case_list 读取用例，逐行执行并断言。

分工：
    本文件      —— 组织执行、断言、回写结果（用例层）
    api/        —— 发请求、参数化、关联提取（接口层）
    utils/      —— Excel 读写、日志、Allure 附件（工具层）

Allure 集成说明：
    每个 Excel 行在报告中是一条独立用例，标题为「id + 用例名」，
    参数区展示接口地址 / 方法 / 期望状态码；请求与响应附件由接口层自动附加。

注意：Excel 行序即执行顺序，因此「登录」用例排在前面，
      后续用例可通过 ${ticket} 引用其提取出的票据。

CI/CD 冒烟模式：
    当 SMOKE_ONLY 为真（`python main.py --smoke` 或环境变量 AMSAPI_SMOKE=1）时，
    只加载 tags 列命中 SMOKE 标签的用例，供流水线在构建后快速验证。
"""
import allure
import pytest

from api.base_api import CaseSkipped
from config import settings
from utils import allureutil
from utils.excelutil import ExcelUtil
from utils.logutil import logger

# 冒烟模式：只取带指定标签的用例
SMOKE_ONLY = settings.RunConfig.SMOKE_ONLY
FILTER_TAGS = settings.RunConfig.TAGS if SMOKE_ONLY else None

# 模块级只读一次用例数据，会话内复用
_excel = ExcelUtil()
CASES = _excel.read_cases(only_runnable=True, tags=FILTER_TAGS)

# 冒烟模式下给整个模块打上 smoke 标记，便于报告分类与 `pytest -m smoke` 筛选
pytestmark = pytest.mark.smoke if SMOKE_ONLY else []

# 没有可执行用例时，整模块跳过，避免 parametrize 参数为空报错
if not CASES:
    if SMOKE_ONLY:
        pytest.skip("Excel 中未找到标签为 {} 的冒烟用例（检查 tags 列）".format(FILTER_TAGS),
                    allow_module_level=True)
    pytest.skip("Excel 中未读取到可执行用例（检查 isdel 列是否为 1）", allow_module_level=True)


def _case_id(case):
    """为 pytest 生成可读的用例 id，如 id1[登录系统]。"""
    return "id{}[{}]".format(case.get("id"), case.get("title"))


def _attach_teardown_warning(api):
    """
    后置清理失败时在报告中显式提示。

    清理失败不改变用例结论（否则「清理接口挂了」会被误报成业务问题），
    但它意味着被测系统可能残留脏数据，必须在报告里留下痕迹，
    否则一轮「全绿」的背后是真脏数据，下一次构建会莫名失败。
    """
    if getattr(api, "teardown_failed", False):
        allureutil.attach_text("后置清理失败（可能残留脏数据，请人工确认）",
                               "\n".join(api.teardown_errors))


@allure.epic("接口自动化")
@allure.feature("Excel 数据驱动")
@pytest.mark.excel
class TestExcelDriver:
    """把 Excel 中的每一行用例映射为一个 pytest 参数化用例。"""

    @pytest.mark.parametrize("case", CASES, ids=_case_id)
    def test_api(self, case, api_client):
        title = case.get("title")
        case_id = case.get("id")

        # 动态设置 Allure 报告中的标题、层级与参数区
        allure.dynamic.title("id{} {}".format(case_id, title))
        allure.dynamic.story("用例列表")
        allure.dynamic.parameter("用例id", case_id)
        allure.dynamic.parameter("接口地址", case.get("url"))
        allure.dynamic.parameter("请求方法", case.get("method"))
        allure.dynamic.parameter("期望状态码", case.get("expected_code"))
        allure.dynamic.parameter("系统档案", api_client.profile.name)

        logger.info("-" * 60)
        logger.info("执行用例：id={} title={}".format(case_id, title))

        is_pass = False
        try:
            # 步骤 1：完整生命周期（前置 -> 请求 -> 关联 -> 断言 -> 后置清理），
            # 全部交给接口层，用例层只负责报告与结果回写。
            # depends 依赖不满足时接口层抛 CaseSkipped，这里转成「跳过」而不是「失败」。
            with allure.step("执行接口请求与断言"):
                try:
                    api_client.run_case(case)
                except CaseSkipped as exc:
                    pytest.skip(str(exc))
            is_pass = True
            logger.info("用例通过：{}".format(title))
        finally:
            # 无论成功失败都回写结果：写入内存，会话结束时统一落盘。
            # 断言失败也要写，否则失败用例在 Excel 里看不到痕迹。
            with allure.step("回写执行结果到 Excel"):
                response = api_client.res
                if settings.RunConfig.WRITE_BACK and response is not None:
                    _excel.update_result(case["__row__"], response, is_pass)

            # 后置清理若失败，在报告中显式留痕（不影响本用例结论）
            with allure.step("检查后置清理结果"):
                _attach_teardown_warning(api_client)

    @classmethod
    def teardown_class(cls):
        """本类执行完毕即落盘一次，防止会话中途异常导致结果丢失。"""
        if settings.RunConfig.WRITE_BACK:
            ExcelUtil.flush()
