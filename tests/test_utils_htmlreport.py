# -*- coding: utf-8 -*-
"""
单元测试：utils/htmlreport.py（HTML 报告可读性修复）
===================================================
守护的是验收时发现的一个可读性缺陷：

    pytest 要求 nodeid 是 ASCII 安全，`@pytest.mark.parametrize(ids=<中文>)`
    会被转成 `\\u767b\\u5f55`；pytest-html 把 nodeid 原样展示，于是报告表格里
    读到的是转义串 —— 用例确实跑了、也确实通过了，但人读不了。

修复只在「展示层」进行：还原数据区里的 `\\uXXXX`，不动 nodeid
（`-k id1001` 这类按编号筛选依赖 nodeid 里的 ASCII 编号）。
"""
import json

import pytest

from utils import htmlreport

# pytest-html 的数据是这样嵌的：JSON 字符串塞进 data-jsonblob 属性，
# 因此反斜杠在文件里是**两个**（JSON 层一个，HTML 层再转义一个）
_ESCAPED = "\\\\u767b\\\\u5f55"


# ======================================================================
# 一、unescape
# ======================================================================
class TestUnescape:
    def test_restores_chinese(self):
        assert htmlreport.unescape(_ESCAPED) == "登录"

    def test_restores_full_width_punctuation(self):
        assert htmlreport.unescape("\\\\u67e5\\\\u8be2\\\\uff08x\\\\uff09") == "查询（x）"

    def test_keeps_ascii_escapes(self):
        """
        ASCII 字符（引号 / 反斜杠 / 换行）**不能**还原 ——
        还原后 JSON 字符串的转义结构会被破坏，整份报告都解析不出来。
        """
        for escaped in ("\\\\u0022", "\\\\u005c", "\\\\u000a"):
            assert htmlreport.unescape(escaped) == escaped

    def test_plain_text_unchanged(self):
        assert htmlreport.unescape("普通文本 abc") == "普通文本 abc"

    def test_empty_input(self):
        assert htmlreport.unescape("") == ""
        assert htmlreport.unescape(None) is None

    def test_single_backslash_json_escape_left_alone(self):
        """
        单反斜杠的 `\\u767b` 是合法 JSON 转义，`JSON.parse` 会自行还原。
        提前展开反而可能改变 JSON 语义，因此不处理。
        """
        assert htmlreport.unescape("\\u767b") == "\\u767b"


# ======================================================================
# 二、fix_report
# ======================================================================
def _write_report(path, nodeid):
    """写一份结构等价于 pytest-html 的最小报告（只需要 data-jsonblob 那一段）。"""
    data = {"tests": {nodeid: [{"result": "Passed", "testId": nodeid}]}}
    # json.dumps 默认 ensure_ascii=True：nodeid 里的字面 `\u767b`（6 个字符）
    # 被转义成 `\\u767b`（两个反斜杠）—— 这正是 HTML 文件里的真实形态。
    # 随后把引号替成 HTML 实体，模拟 Jinja2 的 autoescape。
    blob = json.dumps(data).replace('"', "&#34;")
    path.write_text(
        '<div id="data-container" data-jsonblob="{}"></div>'.format(blob),
        encoding="utf-8")
    return path


class TestFixReport:
    def test_rewrites_report_in_place(self, tmp_path):
        path = _write_report(tmp_path / "report.html",
                             r"testcase/test_yaml_driver.py::test_api[id1001[\u767b\u5f55]]")
        assert htmlreport.fix_report(str(path)) is True

        text = path.read_text(encoding="utf-8")
        assert "\\u767b" not in text

        # 还原后的数据仍然可以被 JSON.parse 解析（结构没有被破坏）
        start = text.index('data-jsonblob="') + len('data-jsonblob="')
        blob = text[start:text.index('"', start)].replace("&#34;", '"')
        parsed = json.loads(blob)
        assert "登录" in list(parsed["tests"])[0]

    def test_idempotent(self, tmp_path):
        path = _write_report(tmp_path / "report.html", r"x::test[\u767b]")
        assert htmlreport.fix_report(str(path)) is True
        assert htmlreport.fix_report(str(path)) is False   # 第二次无需再改

    def test_missing_file_returns_false(self, tmp_path):
        assert htmlreport.fix_report(str(tmp_path / "nope.html")) is False

    def test_empty_path_returns_false(self):
        assert htmlreport.fix_report("") is False
        assert htmlreport.fix_report(None) is False

    @pytest.mark.parametrize("content", ["", "plain html no data"])
    def test_nothing_to_fix(self, tmp_path, content):
        path = tmp_path / "report.html"
        path.write_text(content, encoding="utf-8")
        assert htmlreport.fix_report(str(path)) is False
