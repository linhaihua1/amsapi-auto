# -*- coding: utf-8 -*-
"""
项目路径常量
============
统一从 config.settings 读取，避免多处用 os.path 相对拼接导致路径不一致。
"""
from config import settings


class Path:
    project_path = settings.BASE_DIR

    # 用例数据
    test_case_path = settings.EXCEL_FILE
    cases_dir = settings.CASES_DIR

    # 配置
    conf_path = settings.CONF_FILE
    test_config_path = conf_path      # 兼容旧名称，实际指向 config/conf.ini

    # 输出
    test_report_path = settings.REPORT_DIR
    test_log_path = settings.LOG_DIR


if __name__ == "__main__":
    print("project_path   =", Path.project_path)
    print("test_case_path =", Path.test_case_path)
    print("report path    =", Path.test_report_path)
