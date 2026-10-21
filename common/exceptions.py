# -*- coding: utf-8 -*-
"""
框架自定义异常
==============
把「配置问题」与「用例跳过」这两类语义从普通 Exception 中区分出来，
便于用例层做精准处理（例如把跳过转成 pytest.skip 而不是失败）。

    ConfigError   配置/适配档案有问题 —— 属于环境搭建错误，应尽早暴露
    CaseSkipped   用例被主动跳过（如依赖的用例未通过）—— 不应算失败
    CaseDataError 用例数据本身不完整/不合法 —— 应判失败，但要指明是数据问题
"""


class ConfigError(Exception):
    """配置或系统适配档案不合法。"""


class CaseDataError(AssertionError):
    """
    用例数据不完整或不合法（缺 url、缺 method、缺 expected_code、引用了未定义变量）。

    为什么继承 AssertionError 而不是 Exception：
        这类问题的表现应当是「用例失败」，而不是「框架崩溃」或（更糟）「用例通过」。
        pytest 会把 AssertionError 计为 failed，展示形式与断言失败一致，
        同时错误信息里能直接写明「该改哪一行」，避免把数据问题误判成产品缺陷。
    """


class CaseSkipped(Exception):
    """
    用例被主动跳过。

    典型场景：用例声明了 depends（依赖前置用例），而前置用例执行失败。
    用例层捕获本异常后应转为 pytest.skip()，而不是断言失败 ——
    因为「前置没成功」并不代表「本用例的实现是错的」。
    """
