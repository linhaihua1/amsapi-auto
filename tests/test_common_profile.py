# -*- coding: utf-8 -*-
"""
单元测试：common/profile.py（系统适配档案层）
=============================================
这是「一套框架适配多种 web 系统」的入口层。档案读错一项，表现就是整套用例
打错域名、带错令牌或判错成功 —— 因此这里覆盖到字段解析、域名路由、
优先级链和错误提示的每一处。
"""
import os

import pytest

from common import profile as profile_module
from common.auth import BearerAuth, HeaderAuth, NoAuth
from common.exceptions import ConfigError
from common.profile import SystemProfile, available_systems, load_profile
from config import settings


@pytest.fixture
def systems_dir(tmp_path, monkeypatch):
    """把档案目录指向临时目录，避免碰到仓库里真实的 config/systems。"""
    directory = tmp_path / "systems"
    directory.mkdir()
    monkeypatch.setattr(settings, "SYSTEMS_DIR", str(directory))
    profile_module.clear_cache()
    return directory


def write_ini(directory, name, content):
    path = directory / "{}.ini".format(name)
    path.write_text(content, encoding="utf-8")
    return path


# ======================================================================
# 一、内置默认（不提供任何档案文件时的行为）
# ======================================================================
class TestBuiltinDefault:
    def test_no_profile_file_still_works(self, systems_dir):
        """开箱即用：没有 systems 目录也能跑，行为等同改造前。"""
        profile = load_profile("default")
        assert profile.name == "default"
        assert profile.response.style == "status"
        assert isinstance(profile.auth, NoAuth)

    def test_empty_name_falls_back_to_default(self, systems_dir):
        assert load_profile("").name == "default"

    def test_run_config_system_is_used(self, systems_dir):
        settings.RunConfig.SYSTEM = "default"
        assert load_profile().name == "default"


# ======================================================================
# 二、档案加载与错误提示
# ======================================================================
class TestLoad:
    def test_loads_values_from_file(self, systems_dir):
        write_ini(systems_dir, "demo", """
[system]
name = 演示系统
description = 用于单测

[env]
base_url = http://demo.local/
timeout = 25
encoding = gbk
content_type = application/x-www-form-urlencoded
response_format = xml
""")
        profile = load_profile("demo")
        assert profile.title == "演示系统"
        assert profile.base_url == "http://demo.local"      # 末尾斜杠被去掉
        assert profile.timeout == 25
        assert profile.encoding == "gbk"
        assert profile.content_type == "application/x-www-form-urlencoded"
        assert profile.response_format == "xml"

    def test_missing_non_default_profile_raises_with_choices(self, systems_dir):
        """档案名打错必须立刻报错 —— 静默回退默认档案会让人跑错环境而不自知。"""
        write_ini(systems_dir, "mall", "[system]\nname = 商城\n")
        with pytest.raises(ConfigError) as exc:
            load_profile("malll")
        assert "mall" in str(exc.value)          # 提示里列出可用档案

    def test_error_message_mentions_env_var(self, systems_dir):
        with pytest.raises(ConfigError, match="AMSAPI_SYSTEM"):
            load_profile("nope")

    def test_cache_returns_same_instance(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = A\n")
        assert load_profile("demo") is load_profile("demo")

    def test_force_reloads(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = A\n")
        first = load_profile("demo")

        write_ini(systems_dir, "demo", "[system]\nname = B\n")
        assert load_profile("demo", force=True).title == "B"
        assert first.title == "A"

    def test_clear_cache(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = A\n")
        first = load_profile("demo")
        profile_module.clear_cache()
        assert load_profile("demo") is not first

    def test_available_systems_lists_files(self, systems_dir):
        write_ini(systems_dir, "b", "[system]\n")
        write_ini(systems_dir, "a", "[system]\n")
        assert available_systems() == ["a", "b"]

    def test_available_systems_on_missing_dir(self, monkeypatch, tmp_path):
        monkeypatch.setattr(settings, "SYSTEMS_DIR", str(tmp_path / "nope"))
        assert available_systems() == []


# ======================================================================
# 三、请求头与 Cookie（大小写必须保真）
# ======================================================================
class TestHeadersAndCookies:
    def test_header_name_case_preserved(self, systems_dir):
        """
        请求头名区分大小写，不能被 configparser 默认行为改成小写，
        否则 X-Auth-Token 之类的头名发出去对方不认。
        """
        write_ini(systems_dir, "demo", """
[headers]
X-Auth-Token = abc
Content-Type = application/json
""")
        profile = load_profile("demo")
        assert set(profile.headers) == {"X-Auth-Token", "Content-Type"}

    def test_cookies_loaded(self, systems_dir):
        write_ini(systems_dir, "demo", """
[cookies]
JSESSIONID = sid-1
""")
        assert load_profile("demo").cookies == {"JSESSIONID": "sid-1"}


# ======================================================================
# 四、域名与多服务路由
# ======================================================================
class TestResolveUrl:
    @pytest.fixture
    def profile(self, systems_dir):
        write_ini(systems_dir, "demo", """
[env]
base_url = http://main.local

[hosts]
user = http://user.local:9001
order = http://order.local
""")
        return load_profile("demo")

    def test_absolute_url_untouched(self, profile):
        assert profile.resolve_url("http://other.local/v1/x") == "http://other.local/v1/x"

    def test_relative_url_uses_main_domain(self, profile):
        assert profile.resolve_url("/v1/x") == "http://main.local/v1/x"

    def test_relative_url_without_leading_slash(self, profile):
        assert profile.resolve_url("v1/x") == "http://main.local/v1/x"

    def test_inline_alias(self, profile):
        """用例里写 user:/v1/x 即可路由到用户服务。"""
        assert profile.resolve_url("user:/v1/x") == "http://user.local:9001/v1/x"

    def test_host_argument(self, profile):
        assert profile.resolve_url("/v1/x", host="order") == "http://order.local/v1/x"

    def test_host_argument_case_insensitive(self, profile):
        assert profile.resolve_url("/v1/x", host="ORDER") == "http://order.local/v1/x"

    def test_unknown_alias_falls_back_to_main(self, profile):
        assert profile.resolve_url("/v1/x", host="nope") == "http://main.local/v1/x"

    def test_colon_in_path_is_not_treated_as_alias(self, profile):
        """路径里带冒号但前缀不是别名时，不能被误当成域名别名。"""
        assert profile.resolve_url("/v1/search:name") == "http://main.local/v1/search:name"

    def test_default_base_argument_wins_over_profile(self, profile):
        """BaseApi(base_url=...) 的显式指定优先级高于档案。"""
        assert profile.resolve_url("/v1/x", default_base="http://explicit.local") == \
            "http://explicit.local/v1/x"

    def test_alias_beats_default_base(self, profile):
        assert profile.resolve_url("user:/v1/x", default_base="http://explicit.local") == \
            "http://user.local:9001/v1/x"

    def test_no_base_anywhere_returns_path(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert load_profile("demo").resolve_url("/v1/x") == "/v1/x"

    def test_empty_path(self, profile):
        assert profile.resolve_url("") == ""


class TestEffectiveBaseUrl:
    def test_run_config_base_url_wins(self, systems_dir):
        """域名是 CI 中最常被临时替换的东西，运行配置应压过档案。"""
        write_ini(systems_dir, "demo", "[env]\nbase_url = http://from-profile\n")
        settings.RunConfig.BASE_URL = "http://from-ci"
        assert load_profile("demo").effective_base_url == "http://from-ci"

    def test_profile_used_when_run_config_empty(self, systems_dir):
        write_ini(systems_dir, "demo", "[env]\nbase_url = http://from-profile\n")
        settings.RunConfig.BASE_URL = ""
        assert load_profile("demo").effective_base_url == "http://from-profile"


# ======================================================================
# 五、超时与证书的优先级链
# ======================================================================
class TestTimeoutAndVerify:
    def test_profile_value_used_when_env_not_set(self, systems_dir):
        write_ini(systems_dir, "demo", "[env]\ntimeout = 42\n")
        settings.ENV_OVERRIDES.discard("TIMEOUT")
        assert load_profile("demo").timeout == 42

    def test_env_override_beats_profile(self, systems_dir):
        """流水线用 AMSAPI_TIMEOUT 临时调整时必须生效。"""
        write_ini(systems_dir, "demo", "[env]\ntimeout = 42\n")
        settings.ENV_OVERRIDES.add("TIMEOUT")
        try:
            assert load_profile("demo").timeout == settings.RunConfig.TIMEOUT
        finally:
            settings.ENV_OVERRIDES.discard("TIMEOUT")

    def test_run_config_used_when_profile_omits(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        settings.RunConfig.TIMEOUT = 33
        assert load_profile("demo").timeout == 33

    def test_verify_from_profile(self, systems_dir):
        write_ini(systems_dir, "demo", "[env]\nverify = true\n")
        settings.ENV_OVERRIDES.discard("VERIFY")
        assert load_profile("demo").verify is True

    def test_verify_env_override(self, systems_dir):
        write_ini(systems_dir, "demo", "[env]\nverify = true\n")
        settings.ENV_OVERRIDES.add("VERIFY")
        try:
            assert load_profile("demo").verify == settings.RunConfig.VERIFY
        finally:
            settings.ENV_OVERRIDES.discard("VERIFY")

    def test_verify_falls_back_to_run_config(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        settings.RunConfig.VERIFY = True
        assert load_profile("demo").verify is True


# ======================================================================
# 六、响应规则 / 认证 / 钩子
# ======================================================================
class TestResponseSection:
    def test_style_and_values(self, systems_dir):
        write_ini(systems_dir, "demo", """
[response]
style = code
success_values = 0
message_path = body.msg
data_path = body.rows
http_ok = 200
""")
        spec = load_profile("demo").response
        assert spec.style == "code"
        assert spec.success_values == ["0"]
        assert spec.message_paths == ("body.msg",)
        assert spec.data_paths == ("body.rows",)
        assert spec.http_ok == {200}

    def test_omitted_section_keeps_status_style(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert load_profile("demo").response.style == "status"

    def test_require_expected_defaults_to_true(self, systems_dir):
        """默认 fail-closed：缺 expected_code 时必须报错，而不是「HTTP 200 即通过」。"""
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert load_profile("demo").response.require_expected is True

    def test_require_expected_can_be_disabled(self, systems_dir):
        """存量系统确实无法补齐期望值时，档案里可显式关掉（有据可查，不是静默默认）。"""
        write_ini(systems_dir, "demo", """
[response]
style = status
require_expected = false
""")
        assert load_profile("demo").response.require_expected is False


class TestAuthSection:
    def test_bearer(self, systems_dir):
        write_ini(systems_dir, "demo", """
[auth]
type = bearer
token = ${token}
""")
        assert isinstance(load_profile("demo").auth, BearerAuth)

    def test_header_auth(self, systems_dir):
        write_ini(systems_dir, "demo", """
[auth]
type = header
header = access-ticket
token = ${ticket}
""")
        auth = load_profile("demo").auth
        assert isinstance(auth, HeaderAuth)
        assert auth.header == "access-ticket"

    def test_default_is_no_auth(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert isinstance(load_profile("demo").auth, NoAuth)


class TestHooksSection:
    def test_hooks_declared_and_split(self, systems_dir):
        write_ini(systems_dir, "demo", """
[hooks]
before_request = common.hooks:make_sign_hook({"salt": "a", "upper": true}), common.hooks:make_timestamp_nonce_hook()
""")
        registry = load_profile("demo").hooks
        assert len(registry.before_hooks) == 2
        assert registry.before_hooks[0].__name__ == "sign_request"
        assert registry.before_hooks[1].__name__ == "inject_timestamp_nonce"

    def test_no_hooks_by_default(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert load_profile("demo").hooks.before_hooks == []


# ======================================================================
# 七、展示信息
# ======================================================================
class TestDescribe:
    def test_contains_system_and_domain(self, systems_dir):
        write_ini(systems_dir, "demo", """
[system]
name = 演示
[env]
base_url = http://d.local
[hosts]
user = http://u.local
""")
        info = load_profile("demo").describe()
        assert info["系统档案"] == "demo"
        assert info["系统名称"] == "演示"
        assert info["主域名"] == "http://d.local"
        assert info["域名别名"] == "user"

    def test_never_leaks_credentials(self, systems_dir):
        """报告「环境」页会展示这些内容，绝不能把令牌带出去。"""
        write_ini(systems_dir, "demo", """
[auth]
type = header
header = X-Token
token = SUPER-SECRET-VALUE
""")
        info = load_profile("demo").describe()
        assert "SUPER-SECRET" not in str(info)

    def test_empty_domain_shown_as_placeholder(self, systems_dir):
        write_ini(systems_dir, "demo", "[system]\nname = x\n")
        assert load_profile("demo").describe()["主域名"] == "(用例自带完整地址)"


# ======================================================================
# 八、仓库内真实档案的完整性（防止示例档案被改坏）
# ======================================================================
class TestShippedProfiles:
    """
    这些断言直接跑在仓库真实的 config/systems/*.ini 上。
    示例档案是新人抄写的模板，必须保证「存在且能被解析」。
    """

    EXPECTED = {"default", "gov", "finance_erp", "mall", "dataplatform"}

    def test_all_ship_with_project(self):
        assert self.EXPECTED.issubset(set(available_systems()))

    @pytest.mark.parametrize("name", sorted(EXPECTED))
    def test_shipped_profile_loads(self, name):
        profile = profile_module.load_profile(name, force=True)
        assert profile.name == name
        assert profile.title and profile.title != name
        assert profile.response.style in ("status", "code", "success", "errno", "retcode", "raw")

    def test_default_profile_matches_original_behavior(self):
        """default 档案必须等价于改造前的行为，否则存量用例会被悄悄改判定规则。"""
        profile = profile_module.load_profile("default", force=True)
        assert profile.response.style == "status"
        assert profile.response.code_paths == ("body.status",)
        assert isinstance(profile.auth, NoAuth)
        assert profile.base_url == ""
        assert profile.hosts == {}

    def test_gov_uses_real_ticket_header(self):
        """真实被测系统靠 access-ticket 请求头传票据，档案要如实反映。"""
        profile = profile_module.load_profile("gov", force=True)
        assert isinstance(profile.auth, HeaderAuth)
        assert profile.auth.header == "access-ticket"

    def test_mall_declares_multi_host(self):
        assert "order" in profile_module.load_profile("mall", force=True).hosts


def test_systems_dir_constant_points_into_config():
    assert os.path.basename(settings.SYSTEMS_DIR) == "systems"
    assert os.path.basename(os.path.dirname(settings.SYSTEMS_DIR)) == "config"


def test_builtin_default_style_is_status():
    assert profile_module.BUILTIN_DEFAULT["response"]["style"] == "status"


def test_profile_constructor_accepts_raw_dict():
    """SystemProfile 可以被直接构造，便于在代码里临时定制而不落盘档案。"""
    profile = SystemProfile("inline", {"response": {"style": "success"}})
    assert profile.response.style == "success"


# ======================================================================
# 九、环境变量覆盖（保证「不改仓库文件也能换环境」）
# ======================================================================
class TestEnvOverrides:
    """
    档案里的每一项都应能被 AMSAPI_* 临时覆盖。

    这是 CI/CD 的硬需求：同一份档案要跑测试/预发/生产三套环境，
    差异（域名、编码、密钥）只能来自流水线注入的环境变量，不能来自改文件。
    """

    def test_env_value_empty_returns_none(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_ENCODING", "")
        assert profile_module.env_value("encoding") is None

    def test_env_value_reads_and_strips_nothing(self, monkeypatch):
        monkeypatch.setenv("AMSAPI_ENCODING", "gbk")
        assert profile_module.env_value("encoding") == "gbk"

    def test_encoding_override(self, systems_dir, monkeypatch):
        write_ini(systems_dir, "demo", "[env]\nencoding = gbk\n")
        monkeypatch.setenv("AMSAPI_ENCODING", "utf-8")
        assert load_profile("demo").encoding == "utf-8"

    def test_content_type_override(self, systems_dir, monkeypatch):
        write_ini(systems_dir, "demo", "[env]\ncontent_type = application/json\n")
        monkeypatch.setenv("AMSAPI_CONTENT_TYPE", "application/x-www-form-urlencoded")
        assert load_profile("demo").content_type == "application/x-www-form-urlencoded"

    def test_response_format_override(self, systems_dir, monkeypatch):
        write_ini(systems_dir, "demo", "[env]\nresponse_format = auto\n")
        monkeypatch.setenv("AMSAPI_RESPONSE_FORMAT", "XML")
        assert load_profile("demo").response_format == "xml"

    def test_host_alias_override(self, systems_dir, monkeypatch):
        """AMSAPI_HOST_<别名大写> 用于 CI 里临时换网关地址。"""
        write_ini(systems_dir, "demo", "[hosts]\nadmin = http://old:8080\n")
        monkeypatch.setenv("AMSAPI_HOST_ADMIN", "https://new:8443/")
        profile = load_profile("demo")
        assert profile.hosts["admin"] == "https://new:8443"      # 末尾斜杠被去掉

    def test_host_alias_kept_when_not_overridden(self, systems_dir):
        write_ini(systems_dir, "demo", "[hosts]\nadmin = http://keep:8080\n")
        assert load_profile("demo").hosts["admin"] == "http://keep:8080"

    def test_auth_field_override(self, systems_dir, monkeypatch):
        """AMSAPI_AUTH_* 用于 CI 注入密钥，避免把 client_secret 写进档案。"""
        write_ini(systems_dir, "demo", """
[auth]
type = oauth2
token_url = http://old/token
client_id = old-id
client_secret = old-secret
""")
        monkeypatch.setenv("AMSAPI_AUTH_TOKEN_URL", "https://sso.example.com/oauth/token")
        monkeypatch.setenv("AMSAPI_AUTH_CLIENT_SECRET", "from-ci-credential")
        auth = load_profile("demo").auth
        assert auth.token_url == "https://sso.example.com/oauth/token"
        assert auth.client_secret == "from-ci-credential"
        assert auth.client_id == "old-id"              # 未覆盖的字段保持档案值

    def test_auth_type_override(self, systems_dir, monkeypatch):
        write_ini(systems_dir, "demo", "[auth]\ntype = none\n")
        monkeypatch.setenv("AMSAPI_AUTH_TYPE", "bearer")
        monkeypatch.setenv("AMSAPI_AUTH_TOKEN", "T-1")
        assert isinstance(load_profile("demo").auth, BearerAuth)

    def test_hooks_override(self, systems_dir, monkeypatch):
        """AMSAPI_HOOKS_* 用于 CI 里临时开关签名 / 解密。"""
        write_ini(systems_dir, "demo", "[hooks]\nbefore_request =\n")
        monkeypatch.setenv(
            "AMSAPI_HOOKS_BEFORE_REQUEST",
            'common.hooks:make_sign_hook({"salt": "s", "upper": true})')
        assert len(load_profile("demo").hooks.before_hooks) == 1

    def test_hooks_override_empty_is_ignored(self, systems_dir, monkeypatch):
        write_ini(systems_dir, "demo", """
[hooks]
before_request = common.hooks:make_timestamp_nonce_hook()
""")
        monkeypatch.setenv("AMSAPI_HOOKS_BEFORE_REQUEST", "")
        assert len(load_profile("demo").hooks.before_hooks) == 1


# ======================================================================
# 十、仓库档案的开源约束
# ======================================================================
class TestShippedProfilesAreSanitized:
    """
    开源约束：随仓库发布的示例档案里不允许出现真实环境信息。

    这些断言跑在真实档案文本上（而非解析结果），因为要拦的是
    「文件里有没有写下不该写的字面量」这类问题。
    """

    # 内网地址前缀 / 真实业务标识黑名单（出现即视为泄漏）。
    # 用片段拼接而非整串字面量，避免本文件自己命中自己的规则。
    FORBIDDEN = ("139" ".186.", "10.0." "0.", "192.16" "8.", "linha" "ihua",
                 "dangji" "anyun", "cp" "ms", "materi" "al-types")

    @pytest.mark.parametrize("name", sorted(TestShippedProfiles.EXPECTED))
    def test_profile_text_has_no_real_env_info(self, name):
        path = os.path.join(settings.SYSTEMS_DIR, "{}.ini".format(name))
        text = open(path, encoding="utf-8").read()
        for bad in self.FORBIDDEN:
            assert bad not in text, "档案 {} 中残留真实环境信息：{}".format(name, bad)
