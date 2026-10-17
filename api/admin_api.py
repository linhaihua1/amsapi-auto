# -*- coding: utf-8 -*-
"""
管理端接口对象
==============
涵盖管理端权限与组织相关接口：
    GET /admin/resource/authority                 查询当前用户权限点
    GET /admin/org/getTreeRootParentCodePage      查询组织结构树分页

对应 Excel 用例：id=3「测试1」、id=5「测试3」
这两个接口都需要在请求头中携带 access-ticket（由登录接口提取）。
"""
from api.base_api import BaseApi
from common.variable import GlobalVar


class AdminApi(BaseApi):
    """管理端接口集合。"""

    AUTHORITY_PATH = "/admin/resource/authority"
    ORG_TREE_PATH = "/admin/org/getTreeRootParentCodePage"

    # ------------------------------------------------------------------
    # 权限
    # ------------------------------------------------------------------
    def get_authority(self, app_code, type_="btn", headers=None, **extra):
        """
        查询当前用户的权限点列表。

        :param app_code: 应用编码，如 demo-app
        :param type_:    资源类型，默认 btn
        :param headers:  额外请求头（通常需带 access-ticket=${ticket}）
        """
        payload = {"appCode": app_code, "type": type_}
        payload.update(extra)
        return self.request("get", self.AUTHORITY_PATH, data=payload, headers=headers)

    def get_authority_with_ticket(self, app_code, type_="btn", username=None):
        """
        便捷方法：自动注入 access-ticket 请求头后查询权限。

        依赖登录用例已把 ticket 写入全局变量池。
        """
        ticket = GlobalVar.get("ticket")
        headers = {"access-ticket": ticket}
        if username is not None:
            headers["username"] = username
        return self.get_authority(app_code, type_, headers=headers)

    # ------------------------------------------------------------------
    # 组织
    # ------------------------------------------------------------------
    def get_org_tree_page(self, code, page=1, size=20, headers=None, **extra):
        """
        分页查询组织结构树根节点。

        :param code:    组织编码，如 demo-org
        :param page:    页码
        :param size:    每页条数
        :param headers: 额外请求头（通常需带 access-ticket/ticket）
        """
        payload = {"page": page, "size": size, "code": code}
        payload.update(extra)
        return self.request("get", self.ORG_TREE_PATH, data=payload, headers=headers)

    def get_org_rows(self, code, page=1, size=20, headers=None, **extra):
        """查询组织树并直接返回 rows 列表，便于断言。"""
        self.get_org_tree_page(code, page, size, headers=headers, **extra)
        body = self.body if isinstance(self.body, dict) else {}
        return body.get("rows", [])
