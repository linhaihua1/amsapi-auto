# -*- coding: utf-8 -*-
"""
认证策略层（Auth）
==================
不同 web 系统的鉴权方式差别极大，原框架只能靠用例里手工写 `${ticket}` 塞请求头，
换个系统就要改用例。本模块把主流鉴权方式收敛成**可插拔策略**，
由系统适配档案的 [auth] 段声明，用例数据不用动。

已内置（覆盖市场上绝大多数系统）：

    none      无需鉴权（内部系统 / 只读接口）
    basic     HTTP Basic（老政务、内部管理后台）
    bearer    Bearer Token / JWT（商城、中台、微服务网关）
    header    自定义请求头携带令牌（如 access-ticket、X-Auth-Token）
    apikey    API Key，可放请求头或 query 参数（数据中台、开放平台）
    cookie    会话 Cookie（传统 web 系统、老 ERP）
    oauth2    OAuth2 client_credentials 模式，自动取 token 并缓存续期（中台、开放平台）

关键设计：**令牌值支持 `${var}` 占位符**，在每次请求前从全局变量池实时解析。
于是「先调登录接口拿 ticket，后续接口自动带上」这类链路无需任何额外代码 ——
这也是原框架用 `${ticket}` 手工拼头的通用化版本。
"""
import base64
import threading
import time

import requests

from common import base
from common.variable import GlobalVar
from config import settings
from utils.logutil import logger

# 认证类型常量
AUTH_NONE = "none"
AUTH_BASIC = "basic"
AUTH_BEARER = "bearer"
AUTH_HEADER = "header"
AUTH_APIKEY = "apikey"
AUTH_COOKIE = "cookie"
AUTH_OAUTH2 = "oauth2"

AUTH_TYPES = (AUTH_NONE, AUTH_BASIC, AUTH_BEARER, AUTH_HEADER,
              AUTH_APIKEY, AUTH_COOKIE, AUTH_OAUTH2)


def resolve_credential(value):
    """
    解析凭证里可能存在的 ${var} 占位符（值来自全局变量池）。

    令牌常常是前序接口提取出来的（如登录接口的 ticket），
    因此必须在**每次请求前**解析，而不是构造认证对象时解析一次。

    缺失变量时**保留原串并告警**，不走 base.relace() 的两种默认行为：
        · 默认（strict=True）会抛「用例引用了未定义变量」—— 但占位符是**档案**写的，
          用例一个字都没提这个变量，报错层级完全错位（真实原因是「没跑登录取票」）；
        · strict=False 会替换成空串 —— Authorization 变成 "Bearer "，
          服务端只会回一个没有上下文的 401。
    保留 ${token} 原样更利于定位：日志里能直接看出是哪个变量没取到。
    """
    if isinstance(value, str) and "${" in value:
        missing = [name for name in (base.find(value) or []) if not GlobalVar.has(name)]
        if missing:
            logger.warning("认证凭证中的变量未解析：{}（缺失 {}，"
                           "请确认前序接口已提取该变量）".format(value, "、".join(missing)))
            return value
        return base.relace(value, strict=False)
    return value


class AuthStrategy:
    """认证策略基类。默认不做任何事。"""

    name = AUTH_NONE

    def apply(self, headers, cookies, params):
        """
        把认证信息附加到请求要素上。

        :param headers: 请求头字典（就地修改）
        :param cookies: cookie 字典（就地修改）
        :param params:  query 参数字典（就地修改）
        """
        return headers, cookies, params

    def describe(self):
        """给日志 / 报告的摘要信息（不含密文）。"""
        return {"认证方式": self.name}


class NoAuth(AuthStrategy):
    """无需鉴权。"""

    name = AUTH_NONE


class BasicAuth(AuthStrategy):
    """HTTP Basic：Authorization: Basic base64(user:password)。"""

    name = AUTH_BASIC

    def __init__(self, username="", password=""):
        self.username = username
        self.password = password

    def apply(self, headers, cookies, params):
        user = resolve_credential(self.username)
        pwd = resolve_credential(self.password)
        raw = "{}:{}".format(user, pwd).encode("utf-8")
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "用户名": self.username}


class BearerAuth(AuthStrategy):
    """Bearer Token（含 JWT）：Authorization: Bearer <token>。"""

    name = AUTH_BEARER

    def __init__(self, token="", header="Authorization", prefix="Bearer "):
        self.token = token
        self.header = header or "Authorization"
        # 允许 prefix 为空串（部分系统直接放裸 token）
        self.prefix = "" if prefix is None else prefix

    def apply(self, headers, cookies, params):
        headers[self.header] = "{}{}".format(self.prefix, resolve_credential(self.token))
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "请求头": self.header}


class HeaderAuth(AuthStrategy):
    """
    自定义请求头携带令牌。

    适用于「不是标准 Bearer、也不叫 Authorization」的系统，
    例如 access-ticket / X-Auth-Token / Token。
    """

    name = AUTH_HEADER

    def __init__(self, header="Token", value="", prefix=""):
        self.header = header or "Token"
        self.value = value
        self.prefix = prefix or ""

    def apply(self, headers, cookies, params):
        headers[self.header] = "{}{}".format(self.prefix, resolve_credential(self.value))
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "请求头": self.header}


class ApiKeyAuth(AuthStrategy):
    """API Key：可放请求头（默认）或 query 参数。"""

    name = AUTH_APIKEY

    def __init__(self, name="X-Api-Key", value="", location="header"):
        self.key_name = name or "X-Api-Key"
        self.value = value
        self.location = (location or "header").strip().lower()

    def apply(self, headers, cookies, params):
        value = resolve_credential(self.value)
        if self.location == "query":
            params[self.key_name] = value
        else:
            headers[self.key_name] = value
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "参数名": self.key_name, "位置": self.location}


class CookieAuth(AuthStrategy):
    """
    会话 Cookie。

    支持两种写法：
        cookie_string = "JSESSIONID=abc; token=xyz"
        cookies       = {"JSESSIONID": "abc"}
    """

    name = AUTH_COOKIE

    def __init__(self, cookies=None, cookie_string=""):
        self.cookies = dict(cookies or {})
        self.cookie_string = cookie_string or ""
        # 把 "a=1; b=2" 解析进 cookies
        for item in self.cookie_string.split(";"):
            if "=" in item:
                key, _, value = item.partition("=")
                self.cookies[key.strip()] = value.strip()

    def apply(self, headers, cookies, params):
        for key, value in self.cookies.items():
            cookies[key] = resolve_credential(value)
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "Cookie 数": len(self.cookies)}


class OAuth2ClientCredentials(AuthStrategy):
    """
    OAuth2 client_credentials 模式。

    首次请求前自动调用 token_url 取令牌，并按 expires_in 缓存；
    到期前若干秒自动续期（提前量可配，见 conf.ini [auth] refresh_ahead）。
    令牌请求本身失败会向上抛，避免后续用例"莫名 401"。
    """

    name = AUTH_OAUTH2
    # 距过期多少秒时提前续期，避免边界上刚好失效。
    # 默认取自配置中心，也可在实例化时用 refresh_ahead 覆盖。
    REFRESH_AHEAD = settings.AuthConfig.REFRESH_AHEAD

    def __init__(self, token_url, client_id="", client_secret="", scope="",
                 header="Authorization", prefix="Bearer ", auth_mode="post",
                 timeout=None, verify=None, refresh_ahead=None):
        self.token_url = token_url
        self.client_id = client_id
        self.client_secret = client_secret
        self.scope = scope
        self.header = header or "Authorization"
        self.prefix = "Bearer " if prefix is None else prefix
        # post = client_id/secret 放表单；basic = 走 HTTP Basic（部分平台要求）
        self.auth_mode = (auth_mode or "post").strip().lower()
        # 超时与证书校验默认走配置中心（不再写死 10 / False）
        self.timeout = settings.AuthConfig.TOKEN_TIMEOUT if timeout is None else timeout
        self.verify = settings.AuthConfig.TOKEN_VERIFY if verify is None else verify
        # 提前续期秒数：实例级 > 类默认（配置中心）
        self.refresh_ahead = (self.REFRESH_AHEAD if refresh_ahead is None
                              else int(refresh_ahead))

        self._token = None
        self._expire_at = 0.0
        # 顺序执行下不会并发，加锁是为了防止将来并行执行时重复取 token
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    def _fetch_token(self):
        """向 token_url 申请令牌。"""
        payload = {"grant_type": "client_credentials"}
        if self.scope:
            payload["scope"] = self.scope

        kwargs = {"data": payload, "timeout": self.timeout, "verify": self.verify}
        if self.auth_mode == "basic":
            kwargs["auth"] = (self.client_id, self.client_secret)
        else:
            payload["client_id"] = self.client_id
            payload["client_secret"] = self.client_secret

        logger.info("【认证】OAuth2 申请令牌：{}".format(self.token_url))
        res = requests.post(self.token_url, **kwargs)
        if res.status_code != 200:
            raise RuntimeError("OAuth2 取令牌失败：HTTP {} {}".format(
                res.status_code, res.text[:200]))

        data = res.json()
        token = data.get("access_token") or data.get("token")
        if not token:
            raise RuntimeError("OAuth2 响应中未找到 access_token：{}".format(data))

        expires_in = data.get("expires_in") or data.get("expiresIn") or 3600
        self._token = token
        self._expire_at = time.time() + float(expires_in)
        logger.info("【认证】OAuth2 令牌获取成功，有效期 {} 秒".format(expires_in))
        return token

    @property
    def token(self):
        """取有效令牌；临近过期或未获取时自动刷新。"""
        with self._lock:
            if self._token is None or time.time() >= self._expire_at - self.refresh_ahead:
                return self._fetch_token()
            return self._token

    def apply(self, headers, cookies, params):
        headers[self.header] = "{}{}".format(self.prefix, self.token)
        return headers, cookies, params

    def describe(self):
        return {"认证方式": self.name, "取令牌地址": self.token_url, "模式": self.auth_mode}


# ----------------------------------------------------------------------
# 工厂
# ----------------------------------------------------------------------
def build_auth(cfg):
    """
    按适配档案 [auth] 段的配置构造认证策略。

    :param cfg: 小写键的配置字典；来自 config/systems/*.ini 的 [auth] 段
    :return: AuthStrategy 实例
    """
    cfg = {str(k).lower(): v for k, v in (cfg or {}).items()}
    kind = str(cfg.get("type") or AUTH_NONE).strip().lower()

    if kind in ("", AUTH_NONE, "no", "false"):
        return NoAuth()
    if kind == AUTH_BASIC:
        return BasicAuth(cfg.get("username", ""), cfg.get("password", ""))
    if kind == AUTH_BEARER:
        return BearerAuth(cfg.get("token", ""), cfg.get("header", "Authorization"),
                          cfg.get("prefix", "Bearer "))
    if kind == AUTH_HEADER:
        return HeaderAuth(cfg.get("header", "Token"), cfg.get("token", ""),
                          cfg.get("prefix", ""))
    if kind == AUTH_APIKEY:
        return ApiKeyAuth(cfg.get("key_name", "X-Api-Key"), cfg.get("token", ""),
                          cfg.get("key_in", "header"))
    if kind == AUTH_COOKIE:
        return CookieAuth(cookies=base.safe_loads(cfg.get("cookies"), None),
                          cookie_string=cfg.get("cookie_string", ""))
    if kind == AUTH_OAUTH2:
        return OAuth2ClientCredentials(
            token_url=cfg.get("token_url", ""),
            client_id=cfg.get("client_id", ""),
            client_secret=cfg.get("client_secret", ""),
            scope=cfg.get("scope", ""),
            header=cfg.get("header", "Authorization"),
            prefix=cfg.get("prefix", "Bearer "),
            auth_mode=cfg.get("auth_mode", "post"),
            timeout=int(cfg.get("timeout") or settings.AuthConfig.TOKEN_TIMEOUT),
            verify=base.to_bool(cfg.get("verify"), settings.AuthConfig.TOKEN_VERIFY),
            refresh_ahead=cfg.get("refresh_ahead"),
        )

    # 未识别类型：不静默放过，否则会变成难查的 401
    raise ValueError("不支持的认证类型 '{}'，可选：{}".format(kind, ", ".join(AUTH_TYPES)))
