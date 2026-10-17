# -*- coding: utf-8 -*-
"""
登录接口对象
============
对应接口：GET /v1/users/login
业务作用：登录成功后返回 ticket，后续接口通过请求头 access-ticket 携带该票据。

对应 Excel 用例：id=1「登录系统」，关联表达式 ticket=body.data.ticket
"""
from api.base_api import BaseApi
from common.variable import GlobalVar
from utils.logutil import logger


class LoginApi(BaseApi):
    """登录相关接口集合。"""

    # 接口路径常量，避免路径散落在用例中
    LOGIN_PATH = "/v1/users/login"

    def login(self, username, password, sign=None, **extra):
        """
        用户登录。

        :param username: 用户名，如 demo_user
        :param password: 密码（此处为业务方要求的加密串）
        :param sign:     签名，可选
        :param extra:    其它需要透传的参数
        :return: 统一响应字典
        """
        payload = {"username": username, "password": password}
        if sign is not None:
            payload["sign"] = sign
        payload.update(extra)
        return self.request("get", self.LOGIN_PATH, data=payload)

    def login_and_save_ticket(self, username, password, sign=None):
        """
        登录并自动把 ticket 存入全局变量池，返回 ticket 值。

        典型用法（用例层）：
            ticket = LoginApi().login_and_save_ticket("demo_user", pwd, sign)
            之后其它接口即可直接使用 ${ticket} 占位符。
        """
        self.login(username, password, sign)
        self.check_business_code(200)
        self.extract("ticket=body.data.ticket")

        ticket = GlobalVar.get("ticket")
        logger.info("登录成功，ticket = {}".format(ticket))
        return ticket
