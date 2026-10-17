# -*- coding: utf-8 -*-
"""
框架自定义异常
==============
把「配置问题」与「用例跳过」这两类语义从普通 Exception 中区分出来，
便于用例层做精准处理（例如把跳过转成 pytest.skip 而不是失败）。

    ConfigError   配置/适配档案有问题 —— 属于环境搭建错误，应尽早暴露
    CaseSkipped   用例被主动跳过（如依赖的用例未通过）—— 不应算失败
"""


class ConfigError(Exception):
    """配置或系统适配档案不合法。"""


class CaseSkipped(Exception):
    """
    用例被主动跳过。

    典型场景：用例声明了 depends（依赖前置用例），而前置用例执行失败。
    用例层捕获本异常后应转为 pytest.skip()，而不是断言失败 ——
    因为「前置没成功」并不代表「本用例的实现是错的」。
    """
