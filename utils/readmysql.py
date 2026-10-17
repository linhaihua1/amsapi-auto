# -*- coding: utf-8 -*-
"""
MySQL 用例数据访问层（可选数据源）
==================================
封装针对 test_case_list / test_config / test_result_record 三张表的读写。
只有 run.data_source = mysql 时才会被用例层调用。

相比原框架的改进：
    1. 惰性连接（原实现模块级 `mysql = MysqlUtil()` 导入即连库）
    2. SQL 参数化，避免注入与引号转义问题
    3. 方法支持显式传入 web，也支持实例级默认 web
"""
import datetime
import json

from utils.logutil import logger
from utils.mysqlutil import MysqlUtil, validate_db_config


class RdTestcase:
    """test_case_list / test_config / test_result_record 的数据访问对象。"""

    def __init__(self, mysql=None, web=None):
        # 只在自己建连接（真实使用路径）时校验配置；
        # 显式注入替身的单测不校验，方便离线验证 URL 拼接等规则。
        if mysql is None:
            validate_db_config()
        self.mysql = mysql or MysqlUtil()
        self.web = web

    # ------------------------------------------------------------------
    # 用例
    # ------------------------------------------------------------------
    def load_all_case(self, web=None):
        """加载指定业务（web）下的全部用例。"""
        web = web or self.web
        sql = "SELECT * FROM test_case_list WHERE web = %s"
        return self.mysql.get_fetchall(sql, (web,))

    def is_run_data(self, web=None):
        """
        筛选可执行用例（isdel == 1）。

        isdel 在不同库里可能是 int 1 或字符串 '1'，统一按字符串比较，
        与 Excel 侧（utils/excelutil.py）的判断口径保持一致。
        """
        return [case for case in self.load_all_case(web)
                if str(case.get("isdel")).strip() == "1"]

    # ------------------------------------------------------------------
    # 环境配置
    # ------------------------------------------------------------------
    def load_confkey(self, web, environment):
        """按 web + environment 查询 test_config 中的配置项。"""
        sql = "SELECT * FROM test_config WHERE web = %s AND environment = %s"
        return self.mysql.get_fetchall(sql, (web, environment))

    def get_conf_value(self, web=None, environment=None, default=None):
        """
        取 test_config 中配置项的 value（通常为接口域名）。

        对应原框架写法：load_confkey('<业务标识>', '<环境标识>')[0]['value']
        """
        rows = self.load_confkey(web or self.web, environment)
        if rows and isinstance(rows[0], dict):
            return rows[0].get("value", default)
        return default

    def build_case_url(self, case, base_url=None, web=None, environment=None):
        """
        拼接用例的完整接口地址，沿用原有业务规则：

            完整地址 = 配置域名 + ':' + port_num + 用例 url

        :param case:     用例数据（需含 url，可选 port_num）
        :param base_url: 已取到的配置域名；不传则自动查询 test_config
        :return: 拼接后的完整地址
        """
        path = str(case.get("url") or "")

        # 用例本身写了完整地址时直接使用
        if path.lower().startswith(("http://", "https://")):
            return path

        if base_url is None:
            base_url = self.get_conf_value(web or self.web, environment) or ""

        port = case.get("port_num")
        if base_url and port:
            return "{}:{}{}".format(str(base_url).rstrip("/"), port, path)
        return "{}{}".format(str(base_url).rstrip("/"), path)

    # ------------------------------------------------------------------
    # 结果落库
    # ------------------------------------------------------------------
    def update_results(self, response, is_pass, case_id):
        """把单条用例执行结果写入 test_result_record。"""
        current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sql = ("INSERT INTO test_result_record(case_id, times, response, result) "
               "VALUES (%s, %s, %s, %s)")
        args = (str(case_id), current_time, json.dumps(response, ensure_ascii=False), str(is_pass))
        rows = self.mysql.sql_execute(sql, args)
        logger.debug("写入执行结果：case_id={} -> {}".format(case_id, rows))
        return rows
