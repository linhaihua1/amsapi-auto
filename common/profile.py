# -*- coding: utf-8 -*-
"""
系统适配档案层（SystemProfile）
===============================
这是「一套框架适配多种 web 系统」的核心。

不同系统的差异其实只有固定的那么几处：域名怎么给、怎么鉴权、成功怎么判定、
报文是什么格式什么编码、要不要签名加密。把这些差异从代码里抽出来放进一份
档案（config/systems/<系统>.ini），换系统就只是换档案：

    config/systems/
    ├── default.ini          内置默认，等价于框架原始行为
    ├── gov.ini      党政 / 政务
    ├── finance_erp.ini      财务 / ERP
    ├── mall.ini             商城 / 购物
    └── dataplatform.ini     数据中台 / 信息系统

切换方式（优先级由高到低）：

    1. 环境变量      AMSAPI_SYSTEM=mall          （CI 中最常用）
    2. conf.ini      [env] system = mall
    3. 代码显式指定   load_profile("mall")

不指定时用内置默认档案，**行为与改造前完全一致**，因此本模块对存量用例零影响。

档案里每一项都能被环境变量临时覆盖（保证「不改仓库文件也能换环境」）：

    AMSAPI_BASE_URL            主域名
    AMSAPI_TIMEOUT / VERIFY    超时 / 证书校验
    AMSAPI_ENCODING            响应编码（gbk / utf-8）
    AMSAPI_CONTENT_TYPE        默认请求体类型
    AMSAPI_RESPONSE_FORMAT     响应解析格式（auto / json / xml / text）
    AMSAPI_HOST_<别名大写>     [hosts] 段某个域名别名，如 AMSAPI_HOST_ADMIN
    AMSAPI_AUTH_<字段名大写>   [auth] 段某个字段，如 AMSAPI_AUTH_CLIENT_SECRET

档案字段速查（详细说明见 docs/08-系统适配指南.md）：

    [system]    name / description             仅用于展示
    [env]       base_url / timeout / verify / encoding / content_type / response_format
    [hosts]     域名别名 = 真实域名             支持网关 + 多服务的微服务系统
    [headers]   默认请求头（大小写敏感）
    [cookies]   默认 Cookie
    [response]  style / success_path / success_values / message_path / data_path / http_ok
    [auth]      type 及各自参数
    [hooks]     before_request / after_response
"""
import configparser
import os

from common import base
from common import auth as auth_module
from common import response as response_module
from common.exceptions import ConfigError
from common.hooks import HookRegistry
from config import settings
from utils.logutil import logger

# 默认（未启用任何适配）时的行为，必须与框架改造前一致
BUILTIN_DEFAULT = {
    "system": {"name": "默认", "description": "未启用系统适配档案，行为与框架原始版本一致"},
    "env": {},
    "hosts": {},
    "headers": {},
    "cookies": {},
    "response": {"style": response_module.STYLE_STATUS},
    "auth": {"type": auth_module.AUTH_NONE},
    "hooks": {},
}

# 档案缓存：同名档案只解析一次
_CACHE = {}


def _lower(data):
    """把配置字典的键统一小写（用于除 [headers] / [cookies] 之外的段）。"""
    return {str(key).strip().lower(): value for key, value in (data or {}).items()}


def _read_ini(path):
    """
    读取档案文件。

    注意：
        1. 保留键的原始大小写（`optionxform = str`），否则请求头名会被
           configparser 默认改成小写，导致 X-Auth-Token 之类的头名发出去不对。
        2. 关闭插值（`interpolation=None`），否则 `%`（时间戳格式）与 `${var}`
           会被当作插值语法而报错。
    非请求头段落读取时再统一小写。
    """
    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(path, encoding="utf-8")
    return {section: dict(parser.items(section)) for section in parser.sections()}


def available_systems():
    """列出 config/systems 下已有的档案名（不含 .ini）。"""
    directory = settings.SYSTEMS_DIR
    if not os.path.isdir(directory):
        return []
    return sorted(name[:-4] for name in os.listdir(directory) if name.endswith(".ini"))


def env_value(field):
    """
    读取 `AMSAPI_<FIELD>` 环境变量。

    用途：让档案里的每一项都能被环境变量临时覆盖（CI/CD 常用）。
    例如档案写了 `encoding = gbk`，流水线上可临时用
    `AMSAPI_ENCODING=utf-8` 覆盖而无需改仓库文件。

    :param field: 字段名，如 encoding / content_type / response_format
    :return: 环境变量值；未设置或为空串时返回 None（空串不覆盖）
    """
    value = os.environ.get("{}{}".format(settings.ENV_PREFIX, str(field).upper()))
    if value is None or str(value).strip() == "":
        return None
    return value


def clear_cache():
    """
    清空档案缓存。

    档案是进程内缓存的（避免每条用例重复读盘），改了档案或单元测试需要
    隔离状态时调用本函数；也可用 load_profile(force=True)。
    """
    _CACHE.clear()


class SystemProfile:
    """一个被测系统的全部适配差异。"""

    def __init__(self, name="default", data=None):
        """
        :param name: 档案名（不含 .ini）
        :param data: 档案内容（section -> 键值对）；为空表示使用内置默认
        """
        merged = dict(BUILTIN_DEFAULT)
        for section, values in (data or {}).items():
            merged[section] = values

        system_sec = _lower(merged.get("system"))
        env_sec = _lower(merged.get("env"))
        self.name = name
        self.title = system_sec.get("name") or name
        self.description = system_sec.get("description", "")

        # ---------------- 域名与多服务路由 ----------------
        # 别名 -> 真实域名；键统一小写，值去掉末尾斜杠。
        # 每个别名都可用 AMSAPI_HOST_<别名大写> 环境变量临时覆盖（CI 换环境极常用）。
        self.hosts = {}
        for key, value in (merged.get("hosts") or {}).items():
            alias = str(key).strip().lower()
            text = (env_value("host_{}".format(alias)) or str(value or "")).strip().rstrip("/")
            if text:
                self.hosts[alias] = text
        # 主域名：环境变量 AMSAPI_BASE_URL 的优先级在 effective_base_url 里处理
        self._base_url = str(env_sec.get("base_url") or "").strip().rstrip("/")

        # ---------------- 请求行为 ----------------
        # 超时 / 证书：这里只记「档案有没有显式声明」，真正的取值交给属性在读取时决定。
        # 这样 conf.ini 或环境变量在运行期被改动时能立刻生效，不会冻结成加载时的快照。
        self._timeout = env_sec.get("timeout")
        self._verify = env_sec.get("verify")
        # 响应编码：GBK / GB2312 的政务财务系统必须显式声明，否则中文会乱码
        self._encoding = str(env_sec.get("encoding") or "").strip() or None
        # 默认请求体类型：用例未声明 Content-Type 时使用
        self._content_type = str(env_sec.get("content_type") or "").strip() or None
        # 响应体解析格式：auto（先 json 再 xml 再文本）| json | xml | text
        self._response_format = str(env_sec.get("response_format") or "auto").strip().lower()

        # 默认请求头：保留大小写，避免 header 名被改写
        self.headers = {str(key).strip(): str(value)
                        for key, value in (merged.get("headers") or {}).items()}
        self.cookies = {str(key).strip(): str(value)
                        for key, value in (merged.get("cookies") or {}).items()}

        # ---------------- 响应判定 ----------------
        resp_sec = _lower(merged.get("response"))
        http_ok = response_module.ResponseSpec._as_list(resp_sec.get("http_ok"))
        self.response = response_module.ResponseSpec(
            style=resp_sec.get("style") or response_module.STYLE_STATUS,
            success_path=resp_sec.get("success_path"),
            success_values=resp_sec.get("success_values"),
            message_path=resp_sec.get("message_path"),
            data_path=resp_sec.get("data_path"),
            http_ok=http_ok or None,
        )

        # ---------------- 认证与钩子 ----------------
        # [auth] 段的每一项都可用 AMSAPI_AUTH_<字段名大写> 覆盖，例如：
        #     AMSAPI_AUTH_CLIENT_SECRET=xxx   （CI 里从凭据注入，不必写进档案）
        #     AMSAPI_AUTH_TOKEN_URL=https://sso.example.com/oauth/token
        #     AMSAPI_AUTH_TYPE=bearer
        auth_sec = _lower(merged.get("auth"))
        for key in list(auth_sec):
            override = env_value("auth_{}".format(key))
            if override is not None:
                auth_sec[key] = override
        self.auth = auth_module.build_auth(auth_sec)

        hooks_sec = _lower(merged.get("hooks"))
        # [hooks] 段同样支持环境变量覆盖，便于 CI 中临时开关签名 / 解密：
        #     AMSAPI_HOOKS_BEFORE_REQUEST='common.hooks:make_sign_hook({"salt": "xxx"})'
        #     AMSAPI_HOOKS_AFTER_RESPONSE='common.hooks:make_decrypt_response_hook({"key": "xxx"})'
        for key in ("before_request", "after_response"):
            override = env_value("hooks_{}".format(key))
            if override:
                hooks_sec[key] = override
        self.hooks = HookRegistry(before=hooks_sec.get("before_request"),
                                  after=hooks_sec.get("after_response"))

    # ------------------------------------------------------------------
    # 运行期参数（档案未声明时实时回退运行配置）
    # ------------------------------------------------------------------
    @property
    def base_url(self):
        """档案里声明的主域名（不含 AMSAPI_BASE_URL 覆盖，覆盖见 effective_base_url）。"""
        return self._base_url

    @property
    def encoding(self):
        """
        响应字符编码。

        优先级：AMSAPI_ENCODING 环境变量 > 档案 [env] encoding > 自动判断（None）。
        """
        return env_value("encoding") or self._encoding

    @property
    def content_type(self):
        """
        默认请求体类型（用例未声明 Content-Type 时使用）。

        优先级：AMSAPI_CONTENT_TYPE > 档案 [env] content_type > 未指定。
        """
        return env_value("content_type") or self._content_type

    @property
    def response_format(self):
        """
        响应体解析格式（auto | json | xml | text）。

        优先级：AMSAPI_RESPONSE_FORMAT > 档案 [env] response_format > auto。
        """
        return (env_value("response_format") or self._response_format or "auto").lower()

    @property
    def timeout(self):
        """
        请求超时（秒）。

        优先级：AMSAPI_TIMEOUT 环境变量 > 档案 [env] timeout > conf.ini [run] timeout。
        环境变量最高，是为了保证流水线能临时调整而不必改仓库里的档案。
        """
        if "TIMEOUT" in settings.ENV_OVERRIDES:
            return settings.RunConfig.TIMEOUT
        if self._timeout not in (None, ""):
            return int(self._timeout)
        return settings.RunConfig.TIMEOUT

    @property
    def verify(self):
        """
        是否校验 https 证书。

        优先级与 timeout 一致：AMSAPI_VERIFY > 档案 [env] verify > conf.ini [run] verify。
        """
        if "VERIFY" in settings.ENV_OVERRIDES:
            return settings.RunConfig.VERIFY
        if self._verify in (None, ""):
            return settings.RunConfig.VERIFY
        return base.to_bool(self._verify, settings.RunConfig.VERIFY)

    # ------------------------------------------------------------------
    # 域名解析
    # ------------------------------------------------------------------
    @property
    def effective_base_url(self):
        """
        生效的主域名。

        优先级：conf.ini / AMSAPI_BASE_URL 注入的域名 > 档案里的 base_url。
        理由：域名是 CI 流水线里最常被临时替换的东西（同一套用例跑测试/预发/生产），
        而超时、编码这些属于系统固有属性，所以这里单独让运行配置优先。
        """
        return (settings.RunConfig.BASE_URL or self.base_url or "").rstrip("/")

    def resolve_url(self, path, host=None, default_base=None):
        """
        把用例里的路径解析成完整地址。

        支持三种写法：
            绝对地址      http://10.0.0.1:9001/v1/user
            内联别名      user:/v1/user           （user 在 [hosts] 段声明）
            相对路径      /v1/user                （拼主域名）
        也可由用例字段 host=user 指定别名，效果与内联别名一致。

        :param path:         用例里的 url
        :param host:         用例声明的域名别名
        :param default_base: 主域名（BaseApi 实例显式指定时传入，优先级高于档案）
        :return: 完整地址
        """
        path = str(path or "").strip()
        if not path:
            return path
        if path.lower().startswith(("http://", "https://")):
            return path

        # 内联别名：前缀命中 [hosts] 才替换，否则当作普通路径
        if ":" in path:
            prefix, _, rest = path.partition(":")
            key = prefix.strip().lower()
            if key in self.hosts:
                return "{}/{}".format(self.hosts[key], rest.lstrip("/"))

        base_url = None
        if host:
            base_url = self.hosts.get(str(host).strip().lower())
            if not base_url:
                logger.warning("档案 {} 中未声明域名别名 '{}'，回退主域名".format(self.name, host))
        base_url = base_url or default_base or self.effective_base_url
        if not base_url:
            return path
        return "{}/{}".format(base_url.rstrip("/"), path.lstrip("/"))

    # ------------------------------------------------------------------
    # 展示
    # ------------------------------------------------------------------
    def describe(self):
        """给日志与 Allure「环境」页展示的摘要（不含任何凭证）。"""
        info = {
            "系统档案": self.name,
            "系统名称": self.title,
            "主域名": self.effective_base_url or "(用例自带完整地址)",
            "响应格式": self.response_format,
            "响应编码": self.encoding or "auto",
            "超时(秒)": str(self.timeout),
        }
        if self.hosts:
            info["域名别名"] = ", ".join(sorted(self.hosts))
        info.update(self.response.describe())
        info.update(self.auth.describe())
        info.update(self.hooks.describe())
        return info


def load_profile(system=None, force=False):
    """
    加载系统适配档案（带进程内缓存）。

    :param system: 档案名；为空则取 settings.RunConfig.SYSTEM，再为空则用 default
    :param force:  为 True 时忽略缓存重新读取
    :return: SystemProfile
    :raises ConfigError: 指定的档案不存在（附可用档案清单，避免打错名字悄悄跑错环境）
    """
    name = str(system or settings.RunConfig.SYSTEM or "default").strip() or "default"

    if not force and name in _CACHE:
        return _CACHE[name]

    path = os.path.join(settings.SYSTEMS_DIR, name + ".ini")
    if os.path.exists(path):
        data = _read_ini(path)
    elif name == "default":
        data = {}                        # 内置默认：不需文件，保证开箱即用
    else:
        raise ConfigError(
            "未找到系统适配档案 '{}'。\n"
            "  期望文件：{}\n"
            "  可用档案：{}\n"
            "可用 AMSAPI_SYSTEM=<名称> 或 config/conf.ini 的 [env] system 指定；"
            "不指定则使用内置默认档案（等价于框架原始行为）。".format(
                name, path, ", ".join(available_systems()) or "(无)"))

    profile = SystemProfile(name, data)
    _CACHE[name] = profile
    logger.info("【适配】加载系统档案：{}（{}）".format(profile.name, profile.title))
    return profile
