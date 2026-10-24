# -*- coding: utf-8 -*-
"""
单元测试：common/mask.py（敏感信息脱敏层）
==========================================
本文件守护的是一条**安全约束**：日志与报告里不允许出现明文口令 / 令牌 / 票据。

为什么必须有这层测试：
    脱敏是「反向需求」—— 忘记脱敏不会有任何报错，只会安静地把口令写进日志和报告，
    直到有人拿报告去复现环境时才发现。因此必须用测试把行为钉死：
        1. 敏感字段必须被打码
        2. 业务字段必须**不**被打码（打码过度会让报告失去排错价值）
        3. 脱敏只是「输出侧」行为，不代表可以放松对真实凭据的保护
"""
import pytest

from common import mask


# ======================================================================
# 一、敏感字段名判定
# ======================================================================
class TestIsSensitiveKey:
    @pytest.mark.parametrize("name", [
        "password", "passwd", "pwd", "PASSWORD", "userPassword",
        "pass_word", "pass-word",
        "access-ticket", "accessTicket", "ticket",
        "token", "accessToken", "refresh_token", "access-token",
        "apiKey", "api_key", "x-api-key", "appKey", "privateKey",
        "secret", "clientSecret", "client_secret", "appSecret",
        "authorization", "Authorization", "x-auth-token",
        "cookie", "JSESSIONID", "sessionId",
        "sign", "signature", "salt", "credential",
    ])
    def test_sensitive_names(self, name):
        assert mask.is_sensitive_key(name) is True, name

    @pytest.mark.parametrize("name", [
        "status", "code", "data", "msg", "message", "total", "rows",
        "url", "method", "headers", "elapsed", "success",
        "design", "assignee", "tokenizer", "monkey", "key", "keys",
        "orgCode", "appCode", "port_num",
    ])
    def test_business_names_not_masked(self, name):
        """业务字段一旦被误打码，报告就失去了排错价值。"""
        assert mask.is_sensitive_key(name) is False, name

    def test_none_and_empty(self):
        assert mask.is_sensitive_key(None) is False
        assert mask.is_sensitive_key("") is False
        assert mask.is_sensitive_key("---") is False

    def test_extra_keys_from_config(self):
        """[mask] extra_keys 支持追加业务自定义敏感字段。"""
        from config import settings
        settings.MaskConfig.EXTRA_KEYS = "mobile,idCard"
        mask.clear_cache()
        try:
            assert mask.is_sensitive_key("mobile") is True
            assert mask.is_sensitive_key("idCard") is True
            assert mask.is_sensitive_key("username") is False
        finally:
            settings.MaskConfig.EXTRA_KEYS = ""
            mask.clear_cache()


# ======================================================================
# 二、打码规则
# ======================================================================
class TestMaskValue:
    def test_partial_keeps_edge_chars(self):
        assert mask.mask_value("p@ssw0rd") == "p@s****rd"

    def test_short_value_fully_masked(self):
        """值太短时不做首尾保留，否则等于把口令原样印出来。"""
        assert mask.mask_value("abc") == mask.MASK_MIDDLE
        assert mask.mask_value("") == ""
        assert mask.mask_value(None) is None

    def test_full_mode_reveals_nothing(self):
        from config import settings
        settings.MaskConfig.MODE = "full"
        try:
            assert mask.mask_value("p@ssw0rd") == mask.MASK_MIDDLE
        finally:
            settings.MaskConfig.MODE = "partial"

    def test_non_string_value(self):
        assert "****" in mask.mask_value(12345678)


# ======================================================================
# 三、结构化脱敏
# ======================================================================
class TestMaskMapping:
    def test_nested_dict_and_list(self):
        data = {
            "status": 200,
            "data": {"ticket": "TK-abcdefgh", "user": {"name": "demo", "password": "secret123"}},
            "rows": [{"token": "abcdefghij"}],
        }
        out = mask.mask_mapping(data)
        assert out["status"] == 200                       # 业务字段原样
        assert out["data"]["user"]["name"] == "demo"
        assert out["data"]["ticket"] != "TK-abcdefgh"
        assert out["data"]["user"]["password"] != "secret123"
        assert out["rows"][0]["token"] != "abcdefghij"

    def test_structure_preserved(self):
        """结构必须保持 dict / list，否则 _to_text 的 JSON 展示会错乱。"""
        data = {"a": 1, "list": [1, 2, {"password": "x"}]}
        out = mask.mask_mapping(data)
        assert isinstance(out, dict)
        assert isinstance(out["list"], list)
        assert isinstance(out["list"][2], dict)

    def test_scalar_passthrough(self):
        assert mask.mask_mapping(5) == 5
        assert mask.mask_mapping(None) is None

    def test_text_form_secret_in_non_sensitive_key(self):
        """
        口令以「文本形式」藏在非敏感字段名下时同样要打码。

        真实形态：接口把登录失败原因写在 message 里 ——
        `{"msg": "认证失败 password=abc123"}`，键名 msg 不敏感，
        但值里的口令是明文。只按「键名敏感」打码会整条漏过去，
        而这份 dict 会被日志 Filter 与 Allure 附件直接落盘。
        """
        out = mask.mask_mapping({"msg": "认证失败 password=abc123"})
        assert "abc123" not in out["msg"]
        assert "msg" in out                              # 键名与结构不变

    def test_text_form_secret_in_nested_list(self):
        out = mask.mask_mapping({"rows": [{"note": "token=abcdefg"}]})
        assert "abcdefg" not in out["rows"][0]["note"]


# ======================================================================
# 四、文本脱敏（日志场景）
# ======================================================================
class TestMaskText:
    def test_python_dict_repr(self):
        """日志里最常见的形式：logger.info("headers = {}".format(headers))。"""
        text = "headers = {'access-ticket': 'TK-vezuhypcwrux'}"
        out = mask.mask_text(text)
        assert "TK-vezuhypcwrux" not in out
        assert "access-ticket" in out                     # 字段名保留，便于排错

    def test_json_text(self):
        out = mask.mask_text('{"token": "abc123456"}')
        assert "abc123456" not in out
        assert out == '{"token": "abc****56"}'

    def test_kv_pairs(self):
        out = mask.mask_text("username = demo_user, password = demo_password")
        assert "demo_password" not in out
        assert "demo_user" in out

    def test_bearer_token(self):
        """
        `Authorization: Bearer <token>` 是最容易漏的一种形态：
        认证方案名（Bearer）不是秘密，真正的令牌紧随其后，必须一起处理掉。
        """
        out = mask.mask_text("Authorization: Bearer AbCdEf12345678")
        assert "AbCdEf12345678" not in out
        assert "Bearer" in out                    # 方案名保留，报告依然可读

    def test_non_sensitive_untouched(self):
        """业务字段与普通文本必须逐字保留（否则日志就没法看了）。"""
        text = "status = 200 | body.data.total = 3 | GET http://x/v1/users"
        assert mask.mask_text(text) == text

    def test_empty_and_none(self):
        assert mask.mask_text("") == ""
        assert mask.mask_text(None) is None

    def test_short_secret_in_text(self):
        out = mask.mask_text("pwd=1")
        assert "1" not in out.split("=")[1]

    def test_multiple_secrets(self):
        text = "a = 1, password = secret1, token = secret2, b = 2"
        out = mask.mask_text(text)
        assert "secret1" not in out and "secret2" not in out
        assert "a = 1" in out and "b = 2" in out

    def test_url_query_string(self):
        """
        请求地址形如 `/login?username=demo_user&password=demo_password`。

        这是最容易漏的一种形态：若「值」的字符集能吃掉 `&`，
        `username=demo_user&password=demo_password` 会被整体挂在**非敏感的 username** 名下，
        真正的口令就整条漏过去了。
        """
        out = mask.mask_text("http://x/v1/users/login?username=demo_user&password=demo_password")
        assert "demo_password" not in out
        assert "demo_user" in out                 # 非敏感值原样保留
        assert "password=" in out                 # 字段名保留，便于排错

    def test_url_with_token_param(self):
        out = mask.mask_text("http://x/api?sysCode=demo&access-ticket=TK-abcdefgh")
        assert "TK-abcdefgh" not in out
        assert "sysCode=demo" in out


# ======================================================================
# 五、统一入口与开关
# ======================================================================
class TestMaskPayload:
    def test_dict(self):
        masked = mask.mask_payload({"password": "abcdefgh"})["password"]
        assert masked != "abcdefgh"
        assert "****" in masked

    def test_str(self):
        out = mask.mask_payload("token = abcdefgh")
        assert "abcdefgh" not in out
        assert "token" in out

    def test_other_types_passthrough(self):
        assert mask.mask_payload(123) == 123
        assert mask.mask_payload(None) is None

    def test_disabled_returns_original(self):
        """关闭开关必须真的不脱敏（排查问题时的逃生门）。"""
        from config import settings
        settings.MaskConfig.ENABLED = False
        try:
            data = {"password": "abcdefgh"}
            assert mask.mask_payload(data) == data
            assert mask.mask_text("password = abcdefgh") == "password = abcdefgh"
            assert mask.enabled() is False
        finally:
            settings.MaskConfig.ENABLED = True

    def test_dumps_is_json_without_secret(self):
        text = mask.dumps({"token": "abcdefgh", "code": 0}, indent=2)
        assert "abcdefgh" not in text
        assert '"code": 0' in text


# ======================================================================
# 六、与日志组件的集成
# ======================================================================
class TestLogFilter:
    def test_log_record_is_masked(self):
        """脱敏过滤器必须对 logger 生效 —— 这是「不遗漏」的关键。"""
        import logging

        from utils.logutil import logger
        records = []

        class Capture(logging.Handler):
            def emit(self, record):
                records.append(record.getMessage())

        handler = Capture()
        logger.addHandler(handler)
        try:
            logger.info("headers = {'access-ticket': 'TK-abcdefgh'}")
        finally:
            logger.removeHandler(handler)

        assert records, "日志未产生输出"
        assert "TK-abcdefgh" not in records[0]

    def test_log_does_not_raise_on_weird_payload(self):
        """脱敏本身绝不能把日志调用搞崩。"""
        from utils.logutil import logger
        logger.info({"password": object()})
        logger.info("value = %s", object())


# ======================================================================
# 七、落盘后兜底脱敏（第三方插件直接写文件的路径）
# ======================================================================
class TestSanitizeFile:
    def test_json_parametrize_repr_is_masked(self, tmp_path):
        """
        Allure 的 pytest 插件会把 parametrize 的每个参数写成报告参数；
        框架传的是整条用例数据，于是明文口令出现在 `parameters[].value` 里。
        这条路径不经过 attach_*，只能靠落盘后兜底。
        """
        import json

        payload = {
            "name": "case",
            "parameters": [{"name": "case",
                            "value": "{'username': 'demo_user', 'password': 'demo_password'}"}],
        }
        path = tmp_path / "result.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        assert mask.sanitize_file(str(path)) is True
        text = path.read_text(encoding="utf-8")
        assert "demo_password" not in text
        assert "password" in text                 # 字段名保留
        assert json.loads(text)["parameters"][0]["name"] == "case"   # 仍是合法 JSON

    def test_txt_attachment_is_masked(self, tmp_path):
        path = tmp_path / "attachment.txt"
        path.write_text("请求地址：http://x/login?username=demo_user&password=demo_password",
                        encoding="utf-8")
        assert mask.sanitize_file(str(path)) is True
        assert "demo_password" not in path.read_text(encoding="utf-8")

    def test_unchanged_file_reports_false(self, tmp_path):
        path = tmp_path / "clean.json"
        path.write_text('{"code": 200, "msg": "success"}', encoding="utf-8")
        assert mask.sanitize_file(str(path)) is False

    def test_missing_file_reports_false(self, tmp_path):
        assert mask.sanitize_file(str(tmp_path / "nope.txt")) is False

    def test_broken_json_falls_back_to_text(self, tmp_path):
        path = tmp_path / "broken.json"
        path.write_text("{token: 'abcdefgh'", encoding="utf-8")
        assert mask.sanitize_file(str(path)) is True
        assert "abcdefgh" not in path.read_text(encoding="utf-8")


class TestSanitizeDir:
    def test_walks_subdirectories(self, tmp_path):
        sub = tmp_path / "allure-results"
        sub.mkdir()
        (sub / "a.json").write_text('{"value": "password=demo_password"}', encoding="utf-8")
        (sub / "b.txt").write_text("ticket=TK-abcdefgh", encoding="utf-8")
        (sub / "c.bin").write_bytes(b"password=demo_password")     # 非目标后缀不动

        assert mask.sanitize_dir(str(tmp_path)) == 2
        assert "demo_password" not in (sub / "a.json").read_text(encoding="utf-8")
        assert "TK-abcdefgh" not in (sub / "b.txt").read_text(encoding="utf-8")
        assert (sub / "c.bin").read_bytes() == b"password=demo_password"

    def test_idempotent(self, tmp_path):
        """重复执行不能反复改写（否则会话收尾 + 入口兜底会重复劳动）。"""
        (tmp_path / "a.json").write_text('{"value": "pwd=demopass123"}', encoding="utf-8")
        assert mask.sanitize_dir(str(tmp_path)) == 1
        assert mask.sanitize_dir(str(tmp_path)) == 0

    def test_missing_dir_returns_zero(self, tmp_path):
        assert mask.sanitize_dir(str(tmp_path / "nope")) == 0
        assert mask.sanitize_dir("") == 0

    def test_disabled_does_nothing(self, tmp_path):
        from config import settings
        path = tmp_path / "a.txt"
        path.write_text("password=demo_password", encoding="utf-8")
        settings.MaskConfig.ENABLED = False
        try:
            assert mask.sanitize_dir(str(tmp_path)) == 0
            assert "demo_password" in path.read_text(encoding="utf-8")
        finally:
            settings.MaskConfig.ENABLED = True


# ======================================================================
# 五、嵌套结构脱敏（验收缺陷 D1 的回归用例）
# ======================================================================
class TestNestedStructure:
    """
    守护验收时实测到的真实泄漏：

        Excel 数据源的 `request_body` 是一段 JSON **字符串**，repr 之后形如
            'request_body': '{"username": "demo_user", "password": "demo_password"}'
        旧实现的正则会把整段引号值当成 `request_body` 的一个值，
        而 `request_body` 本身不是敏感词 —— 内层的 `password` 再没有机会被检查。
        YAML 的 `request_body` 是 dict（键值对平铺），不触发这个形态，
        所以这个问题长期没被发现，只在 Excel 链路泄漏。

    修复方式：值内部如果还是一段结构（`{}` / `[]`），继续往里看（见 mask._mask_children）。
    """

    def test_json_string_value_is_masked(self):
        text = ("{'id': 1, 'request_body': '{\"username\": \"demo_user\", "
                "\"password\": \"demo_password\"}'}")
        out = mask.mask_text(text)
        assert "demo_password" not in out
        assert '"password": "dem****rd"' in out

    def test_three_level_nesting(self):
        text = "{'a': '{\"user\": {\"password\": \"deep_secret_123\"}}'}"
        out = mask.mask_text(text)
        assert "deep_secret_123" not in out

    def test_yaml_style_still_works(self):
        """回归保护：dict 形态（YAML）原本就能正确处理，不能被改坏。"""
        out = mask.mask_text("{'request_body': {'password': 'demo_password'}}")
        assert "demo_password" not in out

    def test_idempotent(self):
        """重复脱敏不能把值越改越长 —— sanitize_dir 会对同一文件多跑几次。"""
        text = "{'request_body': '{\"password\": \"demo_password\"}'}"
        once = mask.mask_text(text)
        assert mask.mask_text(once) == once

    def test_deep_nesting_does_not_raise(self):
        """异常输入（超深嵌套）必须止于深度上限，不能拖垮日志输出。"""
        text = "'x'"
        for _ in range(mask._MAX_DEPTH + 2):
            text = "{{'k': {}}}".format(text)
        assert isinstance(mask.mask_text(text), str)

    def test_bearer_token_keeps_separator(self):
        """`Authorization: Bearer xxx` 打码后必须保留空格，否则输出无法再被解析。"""
        out = mask.mask_text("Authorization: Bearer abcdef123456")
        assert out.startswith("Authorization: Bearer ")
        assert "abcdef123456" not in out

    def test_non_sensitive_structure_untouched(self):
        """业务字段里的结构不被打码（过度打码会让报告失去排错价值）。"""
        text = '{"data": "{\\"total\\": 23, \\"page\\": 1}"}'
        assert mask.mask_text(text) == text

    def test_sanitize_json_file_with_nested_string(self, tmp_path):
        """
        落盘兜底路径（真实泄漏点）：Allure result.json 的 parametrize 参数里，
        整条用例以字符串形式存在，口令藏在第二层。
        """
        import json as _json

        path = tmp_path / "result.json"
        payload = {
            "parameters": [{
                "name": "case",
                "value": "{'request_body': '{\"password\": \"demo_password\"}'}",
            }]
        }
        path.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        assert mask.sanitize_file(str(path)) is True
        assert "demo_password" not in path.read_text(encoding="utf-8")
