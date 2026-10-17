# -*- coding: utf-8 -*-
"""
YAML 数据驱动用例
=================
从 data/cases/*.yaml 读取用例，逐条执行并断言。

与 Excel 驱动的差别仅在于「数据来源」，执行逻辑完全复用接口层的 run_case()，
这正是分层的价值：换数据源不需要改用例逻辑。

Allure 集成：每条 YAML 用例在报告中展示所属文件与用例标题。

CI/CD 冒烟模式：SMOKE_ONLY 为真时，只加载 tags 字段命中 SMOKE 标签的用例。
"""
import allure
import pytest

from api.base_api import CaseSkipped
from config import settings
from utils.logutil import logger
from utils.yamlutil import read_cases

# 冒烟模式：只取带指定标签的用例
SMOKE_ONLY = settings.RunConfig.SMOKE_ONLY
FILTER_TAGS = settings.RunConfig.TAGS if SMOKE_ONLY else None

CASES = read_cases(tags=FILTER_TAGS)

# 冒烟模式下给整个模块打上 smoke 标记
pytestmark = pytest.mark.smoke if SMOKE_ONLY else []

if not CASES:
    if SMOKE_ONLY:
        pytest.skip("未找到标签为 {} 的冒烟用例（检查 YAML 的 tags 字段）".format(FILTER_TAGS),
                    allow_module_level=True)
    pytest.skip("YAML 用例目录为空（data/cases/*.yaml）", allow_module_level=True)


def _case_id(case):
    """
    生成可读用例 id，如 id1001[login.yaml::登录系统]。

    为什么把用例编号 `id` 放在最前面：
        pytest 会把 nodeid 里的非 ASCII 字符转义成 `\\uXXXX`，因此
        `pytest -k 登录` 这类**中文关键字匹配不到任何用例**（静默 0 选中）。
        把用例编号放在开头后，`-k id1001` 就能稳定地按编号筛选用例，
        与 Excel 驱动（`id3[权限查询]`）的写法保持一致。
    `__source__` 由 utils/yamlutil.py 在读取时写入，标识用例来自哪个文件。
    """
    return "id{}[{}::{}]".format(case.get("id"), case.get("__source__", "yaml"),
                                 case.get("title", "case"))


@allure.epic("接口自动化")
@allure.feature("YAML 数据驱动")
@pytest.mark.yaml
class TestYamlDriver:
    """把每个 YAML 用例映射为一个 pytest 参数化用例。"""

    @pytest.mark.parametrize("case", CASES, ids=_case_id)
    def test_api(self, case, api_client):
        title = case.get("title")
        source = case.get("__source__")

        # 动态设置 Allure 报告中的标题、层级与参数区
        allure.dynamic.title("{}".format(title))
        allure.dynamic.story(source or "YAML 用例")
        allure.dynamic.parameter("来源文件", source)
        allure.dynamic.parameter("接口地址", case.get("url"))
        allure.dynamic.parameter("请求方法", case.get("method"))
        allure.dynamic.parameter("期望状态码", case.get("expected_code"))
        allure.dynamic.parameter("系统档案", api_client.profile.name)

        logger.info("-" * 60)
        logger.info("执行 YAML 用例：{}（来源 {}）".format(title, source))

        # 完整生命周期（前置 -> 请求 -> 关联 -> 断言 -> 后置清理）全在接口层完成。
        # YAML 用例不回写文件，因此这里只需把结果如实反映到 pytest。
        with allure.step("执行接口请求与断言"):
            try:
                api_client.run_case(case)
            except CaseSkipped as exc:
                pytest.skip(str(exc))
        logger.info("YAML 用例通过：{}".format(title))
