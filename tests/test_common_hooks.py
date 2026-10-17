# -*- coding: utf-8 -*-
"""
单元测试：common/hooks.py（请求/响应钩子与签名工具）
====================================================
财务、政务、商城系统的「业务协议」（签名、防重放、加解密）都挂在这一层。
钩子跑错顺序或签名算法差一个字母，表现都是对方返回「签名校验失败」，
排查成本极高，因此这里把拼接规则、参数解析、执行顺序全部固定下来。

加解密相关用例依赖可选依赖 cryptography：未安装时自动跳过（不算失败）。
"""
import pytest

from common import hooks as hooks_module
from common.hooks import (HookRegistry, digest, load_hook, make_aes_hook,
                          make_decrypt_response_hook, make_sign_hook,
                          make_timestamp_nonce_hook, mask_sensitive, split_top_level)


def ctx(payload=None, headers=None):
    """构造一个请求前钩子上下文。"""
    return {
        "method": "POST",
        "url": "http://x/api",
        "headers": {} if headers is None else headers,
        "cookies": {},
        "payload": payload if payload is not None else {},
        "location": "json",
    }


# ======================================================================
# 一、顶层切分
# ======================================================================
class TestSplitTopLevel:
    def test_simple(self):
        assert split_top_level("a, b ,c") == ["a", "b", "c"]

    def test_ignores_commas_inside_braces(self):
        """钩子参数是 JSON 时会带逗号，不能被误切。"""
        text = 'common.hooks:make_sign_hook({"salt": "a", "upper": true}),other.mod:fn'
        assert split_top_level(text) == [
            'common.hooks:make_sign_hook({"salt": "a", "upper": true})',
            "other.mod:fn",
        ]

    def test_empty_items_dropped(self):
        assert split_top_level("a,,b") == ["a", "b"]

    def test_empty_string(self):
        assert split_top_level("") == []


# ======================================================================
# 二、钩子声明解析
# ======================================================================
def module_level_hook(context):
    """供 load_hook 测试引用的模块级钩子。"""
    context["headers"]["X-From"] = "module"
    return context


class TestLoadHook:
    def test_none_returns_none(self):
        assert load_hook(None) is None
        assert load_hook("") is None

    def test_callable_passthrough(self):
        assert load_hook(module_level_hook) is module_level_hook

    def test_dotted_path_with_colon(self):
        assert load_hook("common.hooks:digest") is digest

    def test_dotted_path_without_colon(self):
        assert load_hook("common.hooks.digest") is digest

    def test_factory_without_args(self):
        hook = load_hook("common.hooks:make_sign_hook()")
        assert callable(hook)
        assert hook.__name__ == "sign_request"

    def test_factory_referenced_without_call_raises(self):
        """
        直接引用工厂（漏写括号）必须报错。

        否则注册进去的是工厂本身，运行期会表现成「钩子返回了一个函数而不是上下文」，
        这种错误几乎无法从现象反推原因。
        """
        with pytest.raises(ValueError, match="需要调用后才生效"):
            load_hook("common.hooks:make_sign_hook")

    def test_factory_with_json_args(self):
        """带参数声明是档案里配置签名的唯一途径，必须能解析。"""
        hook = load_hook('common.hooks:make_sign_hook({"salt": "abc", "upper": true})')
        outcome = hook(ctx({"a": 1}))
        assert len(outcome["payload"]["sign"]) == 32
        assert outcome["payload"]["sign"] == outcome["payload"]["sign"].upper()

    def test_factory_with_empty_arg_object(self):
        assert callable(load_hook("common.hooks:make_sign_hook({})"))

    def test_invalid_json_args_raises(self):
        with pytest.raises(ValueError, match="不是合法 JSON"):
            load_hook("common.hooks:make_sign_hook({salt: abc})")

    def test_non_object_args_raises(self):
        with pytest.raises(ValueError, match="必须是 JSON 对象"):
            load_hook("common.hooks:make_sign_hook([1,2])")

    def test_malformed_declaration_raises(self):
        with pytest.raises(ValueError, match="格式错误"):
            load_hook(":noname")


# ======================================================================
# 三、钩子注册表
# ======================================================================
class TestHookRegistry:
    def test_empty_registry_is_noop(self):
        registry = HookRegistry()
        original = ctx({"a": 1})
        assert registry.run_before(original) is original
        assert registry.before_hooks == [] and registry.after_hooks == []

    def test_runs_in_declaration_order(self):
        """顺序有意义：先加密再签名，与先签名再加密结果完全不同。"""
        order = []

        def first(context):
            order.append("first")
            return context

        def second(context):
            order.append("second")
            return context

        HookRegistry(before=[first, second]).run_before(ctx())
        assert order == ["first", "second"]

    def test_comma_separated_string(self):
        registry = HookRegistry(before="common.hooks:digest,common.hooks:digest")
        assert len(registry.before_hooks) == 2

    def test_parameterized_declarations_split_correctly(self):
        """带 JSON 参数的声明内部有逗号，注册表不能把它切成两条。"""
        registry = HookRegistry(
            before='common.hooks:make_sign_hook({"salt": "a", "upper": true}), '
                   'common.hooks:make_timestamp_nonce_hook()')
        assert len(registry.before_hooks) == 2
        assert registry.before_hooks[0].__name__ == "sign_request"
        assert registry.before_hooks[1].__name__ == "inject_timestamp_nonce"

    def test_add_hooks_after_construction(self):
        registry = HookRegistry()
        registry.add_before(module_level_hook).add_after(module_level_hook)
        assert len(registry.before_hooks) == 1
        assert len(registry.after_hooks) == 1

    def test_hook_returning_none_keeps_context(self):
        """钩子可以就地修改上下文而不 return，不能因此把上下文变成 None。"""
        def in_place(context):
            context["headers"]["X-A"] = "1"

        outcome = HookRegistry(before=[in_place]).run_before(ctx())
        assert outcome["headers"] == {"X-A": "1"}

    def test_describe_lists_hook_names(self):
        info = HookRegistry(before=[module_level_hook]).describe()
        assert "module_level_hook" in info["请求前钩子"]
        assert info["响应后钩子"] == "(无)"


# ======================================================================
# 四、摘要与签名
# ======================================================================
class TestDigest:
    def test_md5(self):
        assert digest("abc", "md5") == "900150983cd24fb0d6963f7d28e17f72"

    def test_sha256(self):
        assert digest("abc", "sha256") == \
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    def test_hmac_md5(self):
        assert len(digest("abc", "hmac-md5", key="k")) == 32

    def test_hmac_sha256(self):
        assert len(digest("abc", "hmac-sha256", key="k")) == 64

    def test_default_alg_is_md5(self):
        assert digest("abc") == digest("abc", "md5")

    def test_non_string_input(self):
        assert digest(123) == digest("123")


class TestSignSorted:
    def test_keys_are_sorted(self):
        """参数顺序不能影响签名结果 —— 否则 JS 端与 Python 端永远对不上。"""
        assert hooks_module.sign_sorted({"b": 2, "a": 1}) == \
            hooks_module.sign_sorted({"a": 1, "b": 2})

    def test_known_value(self):
        assert hooks_module.sign_sorted({"a": "1", "b": "2"}, salt="x") == \
            digest("a=1&b=2x", "md5")

    def test_upper(self):
        result = hooks_module.sign_sorted({"a": "1"}, upper=True)
        assert result == result.upper()

    def test_exclude(self):
        """sign 字段自身通常不参与签名，否则循环依赖。"""
        assert hooks_module.sign_sorted({"a": "1", "sign": "xxx"}, exclude=("sign",)) == \
            hooks_module.sign_sorted({"a": "1"})

    def test_skip_empty_by_default(self):
        assert hooks_module.sign_sorted({"a": "1", "b": ""}) == \
            hooks_module.sign_sorted({"a": "1"})

    def test_skip_empty_disabled(self):
        assert hooks_module.sign_sorted({"a": "1", "b": ""}, skip_empty=False) == \
            digest("a=1&b=")

    def test_nested_value_serialized_as_compact_json(self):
        result = hooks_module.sign_sorted({"a": {"x": 1}})
        assert result == digest('a={"x":1}')

    def test_custom_joiners(self):
        assert hooks_module.sign_sorted({"a": "1", "b": "2"}, join="|", kv_sep=":") == \
            digest("a:1|b:2")

    def test_empty_params(self):
        assert hooks_module.sign_sorted({}, salt="s") == digest("s")


# ======================================================================
# 五、内置钩子工厂
# ======================================================================
class TestTimestampNonceHook:
    def test_injects_both_fields(self):
        outcome = make_timestamp_nonce_hook()(ctx({"a": 1}))
        assert "timestamp" in outcome["payload"] and "nonce" in outcome["payload"]
        assert outcome["payload"]["a"] == 1

    def test_custom_field_names(self):
        outcome = make_timestamp_nonce_hook(fields=("ts", "rand"))(ctx())
        assert "ts" in outcome["payload"] and "rand" in outcome["payload"]

    def test_millisecond_unit(self):
        seconds = make_timestamp_nonce_hook(ts_unit="s")(ctx())["payload"]["timestamp"]
        millis = make_timestamp_nonce_hook(ts_unit="ms")(ctx())["payload"]["timestamp"]
        assert millis > seconds

    def test_ts_digits_truncates(self):
        outcome = make_timestamp_nonce_hook(ts_digits=10)(ctx())
        assert len(str(outcome["payload"]["timestamp"])) == 10

    def test_nonce_length(self):
        outcome = make_timestamp_nonce_hook(nonce_len=8)(ctx())
        assert len(outcome["payload"]["nonce"]) == 8

    def test_non_dict_payload_untouched(self):
        """原始报文（XML/文本）不是 dict，钩子应安全跳过而不是崩。"""
        original = ctx("RAW")
        assert make_timestamp_nonce_hook()(original)["payload"] == "RAW"

    def test_nonce_differs_between_calls(self):
        hook = make_timestamp_nonce_hook()
        assert hook(ctx())["payload"]["nonce"] != hook(ctx())["payload"]["nonce"]


class TestSignHook:
    def test_writes_to_payload_field(self):
        outcome = make_sign_hook(salt="s")(ctx({"a": "1"}))
        assert len(outcome["payload"]["sign"]) == 32

    def test_writes_to_header(self):
        outcome = make_sign_hook(target="header", header="X-Sign", salt="s")(ctx({"a": "1"}))
        assert len(outcome["headers"]["X-Sign"]) == 32
        assert "sign" not in outcome["payload"]

    def test_signature_matches_manual_computation(self):
        """签名值必须等于按同一规则手算的结果，这是与对方联调的唯一依据。"""
        outcome = make_sign_hook(salt="salt")(ctx({"a": "1", "b": "2"}))
        assert outcome["payload"]["sign"] == \
            hooks_module.sign_sorted({"a": "1", "b": "2"}, salt="salt", exclude=("sign",))

    def test_non_dict_payload_untouched(self):
        assert make_sign_hook()(ctx("RAW"))["payload"] == "RAW"


class TestMaskSensitive:
    def test_masks_known_fields(self):
        result = mask_sensitive({"username": "u", "password": "p"})
        assert result["username"] == "u" and result["password"] == "******"

    def test_masks_nested(self):
        result = mask_sensitive({"data": {"token": "t"}}, fields=("token",))
        assert result["data"]["token"] == "******"

    def test_does_not_mutate_input(self):
        original = {"password": "p"}
        mask_sensitive(original)
        assert original["password"] == "p"

    def test_custom_placeholder(self):
        assert mask_sensitive({"pwd": "p"})["pwd"] == "******"

    def test_non_dict_passthrough(self):
        assert mask_sensitive("text") == "text"


# ======================================================================
# 六、加解密（可选依赖，未安装自动跳过）
# ======================================================================
crypto = pytest.mark.skipif(not hooks_module.crypto_available(),
                            reason="未安装可选依赖 cryptography")


@crypto
class TestAes:
    KEY = "0123456789abcdef"

    def test_ecb_round_trip(self):
        encrypted = hooks_module.aes_encrypt("hello 中文", self.KEY)
        assert encrypted != "hello 中文"
        assert hooks_module.aes_decrypt(encrypted, self.KEY) == "hello 中文"

    def test_cbc_round_trip(self):
        iv = "abcdef0123456789"
        encrypted = hooks_module.aes_encrypt("hello", self.KEY, iv=iv, mode="CBC")
        assert hooks_module.aes_decrypt(encrypted, self.KEY, iv=iv, mode="CBC") == "hello"

    def test_deterministic_in_ecb(self):
        """ECB 同明文同密钥结果一致 —— 对方按此实现时才能对上。"""
        assert hooks_module.aes_encrypt("x", self.KEY) == hooks_module.aes_encrypt("x", self.KEY)

    def test_raw_bytes_output(self):
        result = hooks_module.aes_encrypt("x", self.KEY, b64=False)
        assert isinstance(result, bytes)

    def test_aes_hook_encrypts_field(self):
        outcome = make_aes_hook(self.KEY, fields=("data",))(
            ctx({"data": {"a": 1}, "other": 2}))
        assert outcome["payload"]["other"] == 2
        assert isinstance(outcome["payload"]["data"], str)
        assert hooks_module.aes_decrypt(outcome["payload"]["data"], self.KEY) == '{"a":1}'

    def test_aes_hook_adds_alg_field(self):
        outcome = make_aes_hook(self.KEY, alg_field="encryptType")(ctx({"data": "x"}))
        assert outcome["payload"]["encryptType"] == "AES/ECB"

    def test_decrypt_response_hook(self):
        cipher_text = hooks_module.aes_encrypt("明文", self.KEY)
        hook = make_decrypt_response_hook(self.KEY, fields=("data",))
        outcome = hook({"response": {"code": 200, "body": {"data": cipher_text}}})
        assert outcome["response"]["body"]["data"] == "明文"

    def test_decrypt_response_hook_drops_fields(self):
        hook = make_decrypt_response_hook(self.KEY, fields=(), drop_fields=("sign",))
        outcome = hook({"response": {"body": {"sign": "xxx", "a": 1}}})
        assert "sign" not in outcome["response"]["body"]

    def test_decrypt_failure_does_not_break_context(self):
        """解密失败只记日志，不能让整条用例在钩子里炸掉、丢失原始响应。"""
        hook = make_decrypt_response_hook("bad-key-length-x", fields=("data",))
        outcome = hook({"response": {"body": {"data": "not-base64-@@@"}}})
        assert outcome["response"]["body"]["data"] == "not-base64-@@@"

    def test_missing_library_message_is_actionable(self):
        """未安装依赖时，报错必须直接告诉用户装什么。"""
        message = hooks_module.CRYPTO_HINT
        assert "cryptography" in message and "pip install" in message


def test_crypto_available_returns_bool():
    assert isinstance(hooks_module.crypto_available(), bool)
