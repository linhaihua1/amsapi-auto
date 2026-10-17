# -*- coding: utf-8 -*-
"""
接口层（API Object / PO 层）
============================
本层职责：把「一个接口」封装成一个类方法，屏蔽 HTTP 细节。

分层约定：
    api/            接口层 —— 只描述「怎么调接口」，不含用例逻辑
    testcase/       用例层 —— 只描述「测什么、期望什么」，调用 api 层
    data/           数据层 —— 提供用例数据（Excel / YAML）
    common/ utils/  公共层与工具层 —— 被上层复用

命名约定：一个业务模块一个文件，如 login_api.py / dict_api.py
"""
