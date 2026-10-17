# -*- coding: utf-8 -*-
"""
单元测试：utils/allureutil.py（Allure 报告工具层）
==================================================
关键约定：未安装 allure 时必须自动降级为空操作，框架不能因为缺 Allure 而崩溃。
本测试通过 monkeypatch 模拟「未安装」与「已安装但不产生真实附件」两种情况。
"""
import os

import pytest

from utils import allureutil


# ======================================================================
# 一、文本化与截断
# ======================================================================
class TestToText:
    def test_dict_to_pretty_json(self):
        text = allureutil._to_text({"a": 1})
        assert '"a": 1' in text

    def test_list_to_json(self):
        text = allureutil._to_text([1, 2])
        assert "1" in text and "2" in text
        assert text.startswith("[")                      # 缩进后的多行 JSON

    def test_plain_string(self):
        assert allureutil._to_text("hello") == "hello"

    def test_none(self):
        assert allureutil._to_text(None) == "None"

    def test_unserializable_object_falls_back_to_str(self):
        class Weird:
            def __repr__(self):
                return "<weird>"
        assert "weird" in allureutil._to_text({"x": Weird()})

    def test_long_content_truncated(self):
        text = allureutil._to_text("x" * (allureutil.MAX_ATTACH_LEN + 100))
        assert "内容过长已截断" in text
        assert len(text) < allureutil.MAX_ATTACH_LEN + 200

    def test_short_content_not_truncated(self):
        assert "截断" not in allureutil._to_text("x" * 10)


# ======================================================================
# 二、附件（拦截 allure.attach，避免产生真实报告文件）
# ======================================================================
@pytest.fixture
def captured_attach(monkeypatch):
    """记录 allure.attach 的调用参数。"""
    calls = []

    def fake_attach(body, name=None, attachment_type=None):
        calls.append({"body": body, "name": name, "type": attachment_type})

    monkeypatch.setattr(allureutil.allure, "attach", fake_attach)
    monkeypatch.setattr(allureutil, "ALLURE_AVAILABLE", True, raising=False)
    return calls


class TestAttach:
    def test_attach_text(self, captured_attach):
        allureutil.attach_text("请求信息", "GET http://x")
        assert captured_attach[0]["name"] == "请求信息"
        assert captured_attach[0]["body"] == "GET http://x"

    def test_attach_json(self, captured_attach):
        allureutil.attach_json("响应体", {"status": 200})
        assert '"status": 200' in captured_attach[0]["body"]

    def test_attach_request_full(self, captured_attach):
        allureutil.attach_request("post", "http://x/api",
                                  headers={"A": "1"}, params={"q": 1}, body={"b": 2})
        body = captured_attach[0]["body"]
        assert "POST http://x/api" in body
        assert "【请求头】" in body
        assert "【查询参数】" in body
        assert "【请求体】" in body

    def test_attach_request_minimal(self, captured_attach):
        """只有方法+地址时不应产生多余小节。"""
        allureutil.attach_request("get", "http://x")
        body = captured_attach[0]["body"]
        assert body == "GET http://x"

    @pytest.mark.parametrize("method", ["get", "post", "put", "delete", "patch", "head", "options"])
    def test_attach_request_method_uppercased(self, captured_attach, method):
        """七种方法在报告头部统一大写展示。"""
        allureutil.attach_request(method, "http://x/api")
        assert captured_attach[0]["body"] == "{} http://x/api".format(method.upper())

    def test_attach_request_delete_with_body(self, captured_attach):
        """DELETE 携带请求体时，报告应展示【请求体】小节且不出现【查询参数】。"""
        allureutil.attach_request("delete", "http://x/api", body={"ids": [1, 2]})
        body = captured_attach[0]["body"]
        assert "DELETE http://x/api" in body
        assert "【请求体】" in body
        assert "【查询参数】" not in body

    def test_attach_response(self, captured_attach):
        allureutil.attach_response({"code": 200, "elapsed": 12.3,
                                    "url": "http://x", "method": "GET",
                                    "body": {"status": 200}})
        names = [c["name"] for c in captured_attach]
        assert names == ["响应信息", "响应体"]
        assert "200" in captured_attach[0]["body"]

    def test_attach_response_ignores_non_dict(self, captured_attach):
        """传入非字典（如异常对象）时应静默跳过，不能抛错。"""
        allureutil.attach_response("not a dict")
        assert captured_attach == []


# ======================================================================
# 三、降级为无 Allure 环境
# ======================================================================
class TestDegrade:
    def test_all_methods_noop_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(allureutil, "ALLURE_AVAILABLE", False)
        # 全部调用都不应抛异常，也不应产生任何副作用
        assert allureutil.attach_text("n", "c") is None
        assert allureutil.attach_json("n", {}) is None
        assert allureutil.attach_request("get", "http://x", headers={"a": 1}) is None
        assert allureutil.attach_response({"code": 200}) is None

    def test_step_is_nullcontext_when_unavailable(self, monkeypatch):
        monkeypatch.setattr(allureutil, "ALLURE_AVAILABLE", False)
        with allureutil.step("步骤") as value:
            assert value is None

    def test_step_works_when_available(self):
        """真实环境下 step 必须可作上下文管理器使用。"""
        with allureutil.step("步骤") as value:
            assert True


# ======================================================================
# 四、环境信息文件
# ======================================================================
class TestWriteEnvironment:
    def test_writes_properties(self, tmp_path):
        target = str(tmp_path / "allure-results")
        allureutil.write_environment(target, {"环境": "test", "超时": 10})
        content = open(os.path.join(target, "environment.properties"), encoding="utf-8").read()
        assert "环境=test" in content
        assert "超时=10" in content

    def test_creates_directory(self, tmp_path):
        target = str(tmp_path / "deep" / "nested")
        allureutil.write_environment(target, {"a": 1})
        assert os.path.isdir(target)

    def test_empty_dir_is_noop(self):
        assert allureutil.write_environment("", {"a": 1}) is None
        assert allureutil.write_environment(None, {"a": 1}) is None

    def test_oserror_is_swallowed(self, monkeypatch):
        """写环境文件失败（如目录不可写）不应影响测试执行。"""
        def boom(*args, **kwargs):
            raise OSError("disk full")
        monkeypatch.setattr(os, "makedirs", boom)
        assert allureutil.write_environment("/anywhere", {"a": 1}) is None

    def test_empty_env_dict(self, tmp_path):
        target = str(tmp_path / "r")
        allureutil.write_environment(target, {})
        assert os.path.isfile(os.path.join(target, "environment.properties"))
