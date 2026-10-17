# -*- coding: utf-8 -*-
"""
PO 风格用例示例
===============
演示「接口层封装 + 用例层调用」的写法：
用例中看不到 url、headers、json 序列化、变量替换等细节，全部由接口对象承担。

对比原来的写法：
    原：res = RequestSend().send(url, method, data=eval(case['request_body']), ...)
    现：res = LoginApi().login(username, password, sign)

本文件同时演示「接口间参数关联」：登录提取 ticket，后续接口自动携带。

**账号从哪里来**（不再把账号密码写死在代码里）：
    优先级：环境变量 > conf.ini 默认值
        AMSAPI_DEMO_USER      用户名
        AMSAPI_DEMO_PASSWORD  密码
        AMSAPI_DEMO_SIGN      签名（可选）
    没配置时用示例值，配合 tools/mock_server.py 即可离线跑通。

标记为 network，可用 `pytest -m "not network"` 跳过。
"""
import os

import allure
import pytest

from api.admin_api import AdminApi
from api.dict_api import DictApi
from api.login_api import LoginApi

# 示例账号：默认值可被环境变量覆盖（避免把真实账号写进仓库）
USERNAME = os.environ.get("AMSAPI_DEMO_USER") or "demo_user"
PASSWORD = os.environ.get("AMSAPI_DEMO_PASSWORD") or "demo_password"
SIGN = os.environ.get("AMSAPI_DEMO_SIGN") or None


@allure.epic("接口自动化")
@allure.feature("PO 风格用例")
@pytest.mark.network
class TestLoginFlow:
    """登录及其后续调用链。"""

    @allure.story("登录流程")
    @allure.title("登录 -> 提取 ticket -> 查询权限点")
    @allure.severity(allure.severity_level.CRITICAL)
    def test_login_and_use_ticket(self):
        """登录 -> 提取 ticket -> 用 ticket 查询权限点（接口间参数关联）。"""
        # 1) 登录，ticket 自动写入全局变量池
        with allure.step("登录并提取 ticket"):
            login = LoginApi()
            ticket = login.login_and_save_ticket(USERNAME, PASSWORD, SIGN)
            login.check_status(200)                 # HTTP 状态码断言
            login.check_business_code(200)          # 业务状态码断言
            assert ticket, "登录成功但未提取到 ticket"

        # 2) 用刚拿到的 ticket 访问权限接口
        with allure.step("携带 ticket 查询权限点"):
            admin = AdminApi()
            admin.get_authority_with_ticket("demo-app", username=USERNAME)
            admin.check_status(200)
            admin.check_business_code(200)
            assert isinstance(admin.body.get("data"), list), "权限接口返回结构不符"

        # 3) 断言响应中的具体字段（路径以完整响应为根）
        with allure.step("断言响应字段 body.status == 200"):
            admin.check_json("body.status", 200)

    @allure.story("字典查询")
    @allure.title("按 id 查询字典")
    @allure.severity(allure.severity_level.NORMAL)
    def test_dict_query(self):
        """字典查询：演示接口对象的业务化封装。"""
        with allure.step("按 id 查询字典 demo-type"):
            api = DictApi()
            api.get_dict_by_id("demo-type", sys_code="demo-admin")
            api.check_business_code(200)

            rows = api.body.get("rows", [])
            assert rows and rows[0].get("id") == "demo-type", "字典查询返回不符"
