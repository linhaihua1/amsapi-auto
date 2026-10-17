# -*- coding: utf-8 -*-
"""
字典接口对象
============
对应接口：GET /dicts
业务作用：查询字典/参数列表（如素材资源类型、音视频标签等）。

对应 Excel 用例：id=2「测试」、id=4「测试2」
"""
from api.base_api import BaseApi


class DictApi(BaseApi):
    """字典查询接口集合。"""

    DICT_PATH = "/dicts"

    def get_dicts(self, **params):
        """
        按条件查询字典列表。

        :param params: 查询参数，如 id="demo-type", sysCode="demo-admin"
        :return: 统一响应字典
        """
        return self.request("get", self.DICT_PATH, data=params or None)

    def get_dict_by_id(self, dict_id, sys_code=None, **params):
        """
        按字典 id 精确查询。

        :param dict_id:  字典标识，如 demo-type
        :param sys_code: 所属系统编码，可选
        """
        params["id"] = dict_id
        if sys_code is not None:
            params["sysCode"] = sys_code
        return self.request("get", self.DICT_PATH, data=params)

    def get_dict_rows(self, **params):
        """查询字典并直接返回 rows 列表，便于用例层断言。"""
        self.get_dicts(**params)
        body = self.body if isinstance(self.body, dict) else {}
        return body.get("rows", [])
