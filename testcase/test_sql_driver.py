# -*- coding: utf-8 -*-
"""
MySQL 数据驱动用例
==================
与其他数据源驱动的差别（沿用原有业务规则）：
    1. 用例来自数据库 test_case_list 表，按 web 筛选（而非 Excel 行）
    2. 接口地址由 test_config 表的配置域名与用例的 port_num 动态拼接：
           完整地址 = 配置域名 + ':' + port_num + 用例 url
       对应原写法：load_confkey('gov','139')[0]['value'] + ':' + str(case['port_num']) + case['url']
    3. 执行结果写入 test_result_record 表

仅当 config/conf.ini 中 run.data_source = mysql 时执行，否则整体跳过。
可用 `pytest -m "not mysql"` 强制排除。
"""
import allure
import pytest

from api.base_api import CaseSkipped
from config import settings
from utils import allureutil
from utils.logutil import logger
from utils.readmysql import RdTestcase

# 整个模块打上 mysql 标记，便于筛选
pytestmark = pytest.mark.mysql


@allure.epic("接口自动化")
@allure.feature("MySQL 数据驱动")
class TestSqlDriver:
    """把数据库中的用例逐条执行并回写结果。"""

    @allure.title("MySQL 用例批量执行")
    def test_api(self, api_client):
        # 数据源开关：非 mysql 时直接跳过
        if settings.RunConfig.DATA_SOURCE != "mysql":
            pytest.skip("当前数据源不是 mysql，跳过 SQL 驱动用例")

        # 数据库未配置时给出明确指引并跳过。
        # 本机没装/没连数据库是常态，不该表现为一条失败用例 —— 那会让
        # 「框架自检」和「CI 首次接入」都被一条无意义的红点淹没。
        missing = settings.missing_db_keys()
        if missing:
            pytest.skip(
                "MySQL 数据源未配置（缺少：{}）。请在 conf.ini 的 [db] 段填写 "
                "host / user / password / database，或注入 AMSAPI_DB_* 环境变量".format(
                    ", ".join(missing)))

        web = settings.resolve_db_web()
        environment = settings.resolve_db_environment()

        repo = RdTestcase(web=web)
        cases = repo.is_run_data()
        if not cases:
            pytest.skip("数据库中未读取到可执行用例（web={}，isdel=1）".format(web))

        # 域名取自 test_config 表，与用例 port_num 拼接出完整地址
        base_url = repo.get_conf_value(web=web, environment=environment)
        logger.info("MySQL 数据源：web={} environment={} 配置域名={}".format(web, environment, base_url))

        allure.dynamic.parameter("业务标识 web", web)
        allure.dynamic.parameter("配置环境 environment", environment)
        allure.dynamic.parameter("配置域名", base_url)
        allure.dynamic.parameter("用例数量", len(cases))

        # 逐条执行（每条作为一个 Allure 步骤展示）
        for case in cases:
            self._run_one(case, repo, base_url, api_client)

    # ------------------------------------------------------------------
    # 内部：执行单条用例
    # ------------------------------------------------------------------
    @staticmethod
    def _run_one(case, repo, base_url, api_client):
        """
        执行单条数据库用例，并把结果写回 test_result_record。

        :param api_client: 会话级接口对象（由用例方法注入，静态方法内无法访问 fixture）
        """
        case_id = case.get("id")
        title = case.get("title")

        # 域名由 test_config 表提供，与用例的 port_num 拼成完整地址后再交给接口层
        case = dict(case)
        case["url"] = repo.build_case_url(case, base_url=base_url)

        logger.info("-" * 60)
        logger.info("执行 SQL 用例：id={} title={} url={}".format(case_id, title, case["url"]))

        with allure.step("用例 id={} {}".format(case_id, title)):
            is_pass = False
            try:
                # 完整生命周期统一走接口层的 run_case：
                # 参数化、认证、钩子、关联提取、业务断言、前后置步骤全部复用，
                # 与 Excel / YAML 驱动保持一致 —— 换被测系统只改档案，不改驱动。
                with allure.step("执行接口请求与断言"):
                    try:
                        api_client.run_case(case)
                    except CaseSkipped as exc:
                        pytest.skip(str(exc))
                is_pass = True
            finally:
                with allure.step("结果写入 test_result_record"):
                    if settings.RunConfig.WRITE_BACK:
                        repo.update_results(api_client.res, is_pass, case_id)

                # 后置清理失败时在报告中显式留痕（用例结论不受影响，但可能有脏数据残留）
                if getattr(api_client, "teardown_failed", False):
                    allureutil.attach_text("后置清理失败（可能残留脏数据，请人工确认）",
                                           "\n".join(api_client.teardown_errors))
