# -*- coding: utf-8 -*-
"""
HTTP 请求工具层
===============
在 requests 之上做一层统一封装，屏蔽细节：

    1. 支持 get / post / put / delete / patch / head / options
    2. 自动根据 method 与 Content-Type 决定参数挂载位置（见下表）：
         - GET / HEAD / OPTIONS     -> params
         - DELETE                   -> 无 Content-Type 时 params；显式声明载体类型时按声明挂载
         - Content-Type: form       -> data
         - Content-Type: multipart  -> files
         - Content-Type: xml / text -> data（原文发送，不做 json 序列化）
         - 其它（默认，含 POST/PUT/PATCH） -> json

    挂载规则速查：
    ┌─────────┬───────────────────────────────┬──────────────┐
    │ method  │ 传入的 Content-Type           │ 挂载位置     │
    ├─────────┼───────────────────────────────┼──────────────┤
    │ get     │ 任意                          │ params       │
    │ head    │ 任意                          │ params       │
    │ options │ 任意                          │ params       │
    │ delete  │ 未声明 / 其它                 │ params       │
    │ delete  │ application/json              │ json         │
    │ delete  │ x-www-form-urlencoded         │ data         │
    │ delete  │ multipart/form-data           │ files        │
    │ post    │ application/json（或未声明）  │ json         │
    │ put     │ application/json（或未声明）  │ json         │
    │ patch   │ application/json（或未声明）  │ json         │
    │ post    │ x-www-form-urlencoded         │ data         │
    │ post    │ multipart/form-data           │ files        │
    │ post    │ application/xml / text/xml    │ data（原文） │
    │ post    │ text/plain                    │ data（原文） │
    │ delete  │ xml / text                    │ data（原文） │
    └─────────┴───────────────────────────────┴──────────────┘

    也可在 send() 里显式传 params= / files= 覆盖自动判定（优先级最高）。
    3. 统一超时、证书校验、会话复用（keep-alive）
    4. 统一返回结构，附带耗时，便于断言与日志排查

返回结构：
    {
        "code":    200,                 # HTTP 状态码
        "body":    {...} | "文本",       # 响应体，能解析 json 则给对象
        "cookies": {...},               # 响应 Set-Cookie
        "headers": {...},               # 响应头
        "elapsed": 123.45,              # 耗时（毫秒）
        "url":     "最终请求地址",
        "method":  "GET",
    }
"""
import json
import time

import requests

from common import base
from config import settings
from utils.logutil import logger

# 常见 Content-Type 前缀常量
CT_JSON = "application/json"
CT_FORM = "application/x-www-form-urlencoded"
CT_MULTIPART = "multipart/form-data"
CT_XML = "application/xml"
CT_SOAP = "application/soap+xml"        # SOAP 1.2（政务 / 财务老系统）
CT_TEXT_XML = "text/xml"                # SOAP 1.1 / 部分老 ERP
CT_TEXT = "text/plain"

# 按「原始文本」发送的类型：报文本身就是 XML / 文本，不能再按 json 序列化
RAW_TEXT_TYPES = (CT_XML, CT_SOAP, CT_TEXT_XML, CT_TEXT)

# 响应解析格式
FORMAT_AUTO = "auto"
FORMAT_JSON = "json"
FORMAT_XML = "xml"
FORMAT_TEXT = "text"


class RequestSend:
    """统一请求发送器。建议在会话级 fixture 中复用同一实例，以复用 TCP 连接。"""

    def __init__(self, timeout=None, verify=None, session=None,
                 encoding=None, response_format=None):
        # 超时：默认取全局配置（秒）
        self.timeout = settings.RunConfig.TIMEOUT if timeout is None else timeout
        # 证书校验：默认取全局配置
        self.verify = settings.RunConfig.VERIFY if verify is None else verify
        # 会话对象：复用可提升性能，同时自动保持 cookie
        self.session = session or requests.Session()
        # 响应字符编码：留空表示自动判断；政务 / 财务的 GBK、GB2312 系统需在此强制指定
        self.encoding = encoding
        # 响应体解析格式：auto | json | xml | text（见 FORMAT_* 常量）
        self.response_format = (response_format or FORMAT_AUTO).lower()

    # ------------------------------------------------------------------
    # 内部辅助
    # ------------------------------------------------------------------
    @staticmethod
    def _norm_body(body):
        """把字符串形式的 json / 表单串转成 Python 对象；已是对象则原样返回。"""
        if isinstance(body, str):
            text = body.strip()
            if not text:
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return body            # 非 json 文本，原样返回
        return body

    @staticmethod
    def _content_type(headers):
        """大小写无关地取出 Content-Type。"""
        for key, value in (headers or {}).items():
            if str(key).lower() == "content-type":
                return str(value).lower()
        return ""

    @staticmethod
    def _is_raw_text(headers):
        """Content-Type 是否属于「原文发送」类型（XML / 纯文本）。"""
        return RequestSend._content_type(headers).startswith(RAW_TEXT_TYPES)

    @classmethod
    def body_location(cls, method, headers):
        """
        判定请求数据应挂载到 requests 的哪个关键字参数。

        这是整个请求层的核心规则，接口层（Allure 附件）也复用本方法，
        以保证「实际发出」与「报告展示」两处判定永远一致。

        :param method:  http 方法（大小写不敏感）
        :param headers: 请求头，用于识别 Content-Type
        :return: "params" | "json" | "data" | "files"
        """
        method = str(method).lower()

        # 无请求体的方法：一律走 query 参数（GET 携带 body 属反模式，不提供支持）
        if method in ("get", "head", "options"):
            return "params"

        ct = cls._content_type(headers)

        # DELETE 是唯一「两可」的方法：默认按 query 处理（兼容历史用法），
        # 但显式声明了 Content-Type 时按声明挂载请求体（REST 批量删除很常见）。
        if method == "delete" and not ct:
            return "params"

        if ct.startswith(CT_MULTIPART):
            return "files"
        if ct.startswith(CT_FORM):
            return "data"
        if ct.startswith(RAW_TEXT_TYPES):
            return "data"              # XML / 纯文本：原文发送
        return "json"                  # json 与未声明 Content-Type 时的默认值

    def _build_kwargs(self, method, data, headers):
        """依据 body_location() 的判定，把 data 放入对应的 requests 参数。"""
        if data is None:
            return {}
        location = self.body_location(method, headers)

        # XML / 纯文本报文不能交给 requests 做表单编码，需要先转成字符串原文。
        # dict 会按约定转成 XML（单键字典以该键为根标签），字符串则原样发送。
        if location == "data" and self._is_raw_text(headers) and not isinstance(data, (str, bytes)):
            if isinstance(data, dict):
                data = base.dict_to_xml(data)
            else:
                data = json.dumps(data, ensure_ascii=False)

        return {location: data}

    # ------------------------------------------------------------------
    # 响应解析
    # ------------------------------------------------------------------
    def _decode_text(self, res):
        """
        取响应文本，并处理编码。

        只有「显式指定了 encoding」或「json 解析失败、需要读文本」时才介入：
        显式编码直接生效；否则当 requests 推断出的编码是 ISO-8859-1 / ASCII
        （即没能从响应头拿到 charset）时，用内容探测结果兜底，
        解决 GBK 政务财务系统中文乱码的问题。
        """
        if self.encoding:
            res.encoding = self.encoding
        else:
            current = str(getattr(res, "encoding", None) or "").lower()
            if current in ("", "iso-8859-1", "ascii"):
                guessed = getattr(res, "apparent_encoding", None)
                if guessed:
                    res.encoding = guessed
        return getattr(res, "text", "")

    def _parse_body(self, res, response_format=None):
        """
        按配置把响应体解析成 dict / list / 文本。

        解析策略：
            auto（默认） 先按 json 解析，失败则**原样给文本** —— 与改造前完全一致。
                         刻意不做"看到 < 就当 XML"的自动探测：那会把 HTML 错误页
                         也解析成 dict，反而让排查变难。
            json         只按 json 解析，失败给文本
            xml          先试 json（兼容网关混返回），失败再按 XML 解析，仍失败给文本
            text         一律给文本
        """
        fmt = str(response_format or self.response_format or FORMAT_AUTO).lower()

        # 除 text 外都先尝试 json —— 与改造前行为一致，保证存量用例零影响
        if fmt != FORMAT_TEXT:
            try:
                return res.json()
            except ValueError:
                pass

        text = self._decode_text(res)

        if fmt == FORMAT_XML:
            parsed = base.xml_to_dict(text)
            if parsed is not None:
                return parsed
        return text

    # ------------------------------------------------------------------
    # 对外接口
    # ------------------------------------------------------------------
    def send(self, url, method, data=None, headers=None, cookies=None,
             params=None, files=None, response_format=None, **kwargs):
        """
        发送请求。

        :param url:     完整地址
        :param method:  请求方法（大小写不敏感）
        :param data:    请求数据，可为 dict / json 字符串，挂载位置自动判断
        :param headers: 请求头
        :param cookies: cookie 字典
        :param params:  显式指定 query 参数（优先级高于自动判断）
        :param files:   显式指定上传文件
        :param response_format: 覆盖实例的响应解析格式（auto/json/xml/text）
        :param kwargs:  透传给 requests 的其它参数（如 allow_redirects）
        :return: 统一响应字典，见模块说明
        """
        method = str(method).lower()
        data = self._norm_body(data)

        # 组装 requests 参数
        req_kwargs = self._build_kwargs(method, data, headers)
        if params is not None:
            req_kwargs["params"] = params
        if files is not None:
            req_kwargs["files"] = files
        # 请求级公共参数
        req_kwargs.setdefault("headers", headers)
        req_kwargs.setdefault("cookies", cookies)
        req_kwargs.setdefault("timeout", self.timeout)
        req_kwargs.setdefault("verify", self.verify)
        req_kwargs.update(kwargs)

        # 日志：请求前
        logger.info("==> {} {}".format(method.upper(), url))
        logger.debug("headers = {}".format(headers))
        logger.debug("params  = {}".format(req_kwargs.get("params")))
        logger.debug("json    = {}".format(req_kwargs.get("json")))
        logger.debug("data    = {}".format(req_kwargs.get("data")))

        start = time.time()
        try:
            res = self.session.request(method=method, url=url, **req_kwargs)
        except requests.RequestException as exc:
            # 网络层异常：记录日志后向上抛，由用例层捕获为失败
            logger.error("请求异常：{} {} -> {}".format(method.upper(), url, exc))
            raise
        elapsed = round((time.time() - start) * 1000, 2)

        # 解析响应体：按 response_format 决定 json / xml / 文本
        body = self._parse_body(res, response_format)

        result = {
            "code": res.status_code,
            "body": body,
            "cookies": res.cookies.get_dict(),
            "headers": dict(res.headers),
            "elapsed": elapsed,
            "url": res.url,
            "method": method.upper(),
        }

        # 日志：响应后
        logger.info("<== {} {} | {} ms".format(res.status_code, res.reason, elapsed))
        logger.debug("响应体 = {}".format(body))
        return result

    # 兼容旧框架中的调用名
    def api_run(self, url, method, data=None, headers=None, cookies=None, **kwargs):
        return self.send(url, method, data=data, headers=headers, cookies=cookies, **kwargs)


if __name__ == "__main__":
    # 简单自测：请求一个公开接口
    r = RequestSend().send("https://httpbin.org/get", "get", data={"a": 1})
    print(r["code"], r["elapsed"])
