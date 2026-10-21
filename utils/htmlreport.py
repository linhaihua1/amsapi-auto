# -*- coding: utf-8 -*-
"""
HTML 报告可读性修复
===================
pytest 要求 nodeid 是 ASCII 安全的：`@pytest.mark.parametrize(..., ids=<中文>)`
会被 pytest 统一转成 `\\u767b\\u5f55` 这种转义形式，而 pytest-html 把 nodeid
原样展示到结果表格，于是报告里读到的是：

    test_api[id1001[login.yaml::\\u767b\\u5f55\\u5e76\\u63d0\\u53d6\\u7968\\u636e]]

数据本身没错（用例确实跑了、也确实通过了），但**人读不了** —— 验收时这被记为
一个可读性缺陷：报告的第一读者是人，不是 JSON 解析器。

本模块只做一件事：报告落盘后，把数据区里的 `\\uXXXX` 还原成真实字符。
纯展示层修复，不碰 nodeid、不影响 `-k id1001` 这类按编号筛选（它们依赖 ASCII 编号）。

为什么不直接把 ids 改成纯 ASCII：
    改成 `id1001` 虽然也解决显示问题，但会丢掉「这是哪条中文用例」的信息；
    而保留中文 ids、只在展示层还原，两个目标都能满足。
"""
import os
import re

# HTML 里数据是以「JSON 字符串」的形式塞进 data-jsonblob 属性的：
#     JSON 层面的 `\\u767b`（一个反斜杠）在 HTML 里被转义成 `\\\\u767b`（两个反斜杠）
# 因此这里匹配 **两个** 反斜杠。只匹配单反斜杠会把合法的 JSON 转义提前展开，
# 反而可能破坏 JSON 结构。
_ESCAPED_RE = re.compile(r"\\\\u([0-9a-fA-F]{4})")


def _safe_char(code):
    """
    只还原非 ASCII 字符（码点 >= 0x80）。

    为什么限制范围：
        `\\u0022`（双引号）、`\\u005c`（反斜杠）、`\\u000a`（换行）这类 ASCII 字符
        如果被还原，会直接破坏 JSON 字符串的转义结构，导致整个报告数据解析失败。
        而实际需要还原的（中文、全角标点、emoji）都在 0x80 以上，限制范围足够。
    """
    return chr(code) if code >= 0x80 else None


def unescape(text):
    """
    还原文本中的 `\\\\uXXXX` 序列（仅非 ASCII 字符）。

    :param text: 原文本
    :return: 还原后的文本
    """
    if not text:
        return text

    def _repl(match):
        char = _safe_char(int(match.group(1), 16))
        return char if char is not None else match.group(0)

    return _ESCAPED_RE.sub(_repl, text)


def fix_report(path):
    """
    就地修复一个 HTML 报告文件（可重复执行，幂等）。

    :param path: HTML 报告绝对路径
    :return: True = 内容被改写；False = 无需改写 / 文件不存在 / 读写失败
    """
    if not path:
        return False
    try:
        if not os.path.isfile(path):
            return False
        with open(path, "r", encoding="utf-8") as fp:
            original = fp.read()
    except (OSError, UnicodeDecodeError):
        return False

    fixed = unescape(original)
    if fixed == original:
        return False
    try:
        with open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(fixed)
    except OSError:
        return False
    return True
