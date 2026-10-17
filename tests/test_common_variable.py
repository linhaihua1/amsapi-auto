# -*- coding: utf-8 -*-
"""
单元测试：common/variable.py（全局变量池）
=========================================
变量池承担「接口间参数传递」，是关联提取的落点。
重点验证：基础读写、点号路径、批量写入、存在性判断、清空。
"""
from common.variable import GlobalVar


class TestGlobalVar:
    def test_set_and_get(self):
        GlobalVar.set("ticket", "abc")
        assert GlobalVar.get("ticket") == "abc"

    def test_get_default_when_missing(self):
        assert GlobalVar.get("nope") is None
        assert GlobalVar.get("nope", default="D") == "D"

    def test_flat_key_containing_dot(self):
        """直接以 'a.b' 为键写入时，应优先精确命中，而不是走层级查找。"""
        GlobalVar.set("user.id", 1)
        assert GlobalVar.get("user.id") == 1

    def test_dot_path_lookup_on_nested_dict(self):
        GlobalVar.set("user", {"id": 7, "name": "张三"})
        assert GlobalVar.get("user.id") == 7
        assert GlobalVar.get("user.name") == "张三"

    def test_dot_path_missing_returns_default(self):
        GlobalVar.set("user", {"id": 7})
        assert GlobalVar.get("user.age", default=-1) == -1

    def test_update_batch(self):
        GlobalVar.update({"a": 1, "b": 2})
        assert GlobalVar.get("a") == 1
        assert GlobalVar.get("b") == 2

    def test_update_none_is_safe(self):
        GlobalVar.update(None)
        assert GlobalVar.all() == {}

    def test_has(self):
        GlobalVar.set("a", None)
        assert GlobalVar.has("a") is True          # 值为 None 也算存在
        assert GlobalVar.has("b") is False

    def test_all_returns_copy(self):
        GlobalVar.set("a", 1)
        snapshot = GlobalVar.all()
        snapshot["a"] = 99
        assert GlobalVar.get("a") == 1             # 外部改动不影响内部

    def test_clear(self):
        GlobalVar.set("a", 1)
        GlobalVar.clear()
        assert GlobalVar.all() == {}

    def test_set_returns_value(self):
        assert GlobalVar.set("a", 1) == 1
