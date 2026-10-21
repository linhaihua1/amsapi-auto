# -*- coding: utf-8 -*-
"""
响应判定层（ResponseSpec）
==========================
不同的 web 系统对「业务是否成功」的表达方式差异极大：

    {"status": 200}                       —— 本工程原有的被测系统
    {"code": 200, "msg": "ok", "data": {}} —— 党政 / 财务 / ERP 最常见
    {"success": true, "result": {}}        —— 商城 / 中台常见
    {"errno": 0, "errmsg": ""}             —— 部分中台
    {"retCode": "0000", "retMsg": ""}      —— 部分银行 / 政务

原框架把 `body.status` 写死在代码里，换一个系统就断言不了。
本模块把这些差异收敛为**一份可配置的判定规则**，由系统适配档案（config/systems/*.ini）
的 [response] 段声明，用例数据无需改动。

判定语义（关键）：

    用例给了 expected_code  -> 用 expected_code 与「实际业务码」比较
    用例没给 expected_code  -> 用 success_values 集合判断实际业务码是否算成功
    两者都没有              -> **报错**（fail-closed），而不是只看 HTTP 状态码

最后一条是刻意收紧的：早期版本在「两者都没有」时退化为「HTTP 200 即成功」，
而政务 / ERP / 商城系统普遍「业务失败也返回 HTTP 200」，于是漏填 expected_code 的
用例会**静默变绿**（只在日志里留一行 WARNING，没人会去看）。
这类假绿比红色失败危险得多 —— 它让「断言根本没跑」看起来像「功能正常」。
因此现在要求用例显式给出期望值，或由档案配置 success_values；
确实只需判断 HTTP 状态时，把用例的 `check_business` 置 false（语义明确，可被搜索到）。
"""
from common import base
from common.exceptions import CaseDataError
from utils.logutil import logger

# ----------------------------------------------------------------------
# 一、内置风格定义
# ----------------------------------------------------------------------
STYLE_STATUS = "status"          # {"status": 200}
STYLE_CODE = "code"              # {"code": 200}
STYLE_SUCCESS = "success"        # {"success": true}
STYLE_ERRNO = "errno"            # {"errno": 0}
STYLE_RETCODE = "retcode"        # {"retCode": "0000"}
STYLE_RAW = "raw"                # 不看业务码，只看 HTTP 状态码

STYLES = (STYLE_STATUS, STYLE_CODE, STYLE_SUCCESS, STYLE_ERRNO, STYLE_RETCODE, STYLE_RAW)

# 各风格的「业务码路径候选」：按顺序尝试，取第一个取到非 None 的
# 之所以给多个候选，是因为同一种风格在不同系统里字段大小写/命名并不统一
STYLE_PATHS = {
    STYLE_STATUS: ("body.status",),
    STYLE_CODE: ("body.code", "body.retCode", "body.resultCode"),
    STYLE_SUCCESS: ("body.success", "body.ok", "body.isSuccess"),
    STYLE_ERRNO: ("body.errno", "body.errCode", "body.errorCode"),
    STYLE_RETCODE: ("body.retCode", "body.retcode", "body.returnCode"),
    STYLE_RAW: (),
}

# 各风格的「成功值集合」：为空表示必须由用例的 expected_code 提供期望值
STYLE_SUCCESS_VALUES = {
    STYLE_STATUS: (),
    STYLE_CODE: (),
    STYLE_SUCCESS: ("true", "1", "yes", "ok"),
    STYLE_ERRNO: ("0", "200"),
    STYLE_RETCODE: ("0000", "0", "200", "success"),
    STYLE_RAW: (),
}

# 错误消息字段的兜底候选（档案没配 message_path 时按此顺序找）
DEFAULT_MESSAGE_PATHS = (
    "body.msg", "body.message", "body.errmsg", "body.errMsg",
    "body.retMsg", "body.retmsg", "body.info", "body.error", "body.errorMessage",
)

# 业务数据体的兜底候选（data / result / rows / ...）
DEFAULT_DATA_PATHS = (
    "body.data", "body.result", "body.rows", "body.list",
    "body.content", "body.payload", "body.records",
)


class ResponseSpec:
    """一个系统的「响应成功判定」规则。"""

    def __init__(self, style=STYLE_STATUS, success_path=None, success_values=None,
                 message_path=None, data_path=None, http_ok=None, require_expected=True):
        """
        :param style:          内置风格名（见 STYLES）；不识别时按 status 处理
        :param success_path:   自定义业务码路径，如 "body.code"；给出后覆盖风格的默认候选
        :param success_values: 成功值集合（列表 / 逗号分隔字符串）；用例没给 expected_code 时使用
        :param message_path:   错误消息路径；不给出时按 DEFAULT_MESSAGE_PATHS 兜底
        :param data_path:      业务数据体路径；不给出时按 DEFAULT_DATA_PATHS 兜底
        :param http_ok:        视为成功的 HTTP 状态码集合，默认 {200, 201, 202, 204}
        :param require_expected:
            用例没给 expected_code、档案也没配 success_values 时是否报错（默认 True）。
            置 False 可退回旧行为（只看 HTTP 状态码），仅供存量系统过渡期使用。
        """
        self.style = style if style in STYLES else STYLE_STATUS
        # HTTP 成功码统一转 int（档案里写的是 "200,201" 这样的字符串）
        self.http_ok = self._as_http_codes(http_ok)

        # 业务码路径：自定义优先，否则取风格的候选列表
        if success_path:
            self.code_paths = (str(success_path).strip(),)
        else:
            self.code_paths = STYLE_PATHS.get(self.style, ())

        # 成功值集合：自定义优先，否则取风格的默认；统一成字符串列表
        values = success_values if success_values is not None else STYLE_SUCCESS_VALUES.get(self.style, ())
        self.success_values = self._as_list(values)

        self.message_paths = ((str(message_path).strip(),) if message_path
                              else DEFAULT_MESSAGE_PATHS)
        self.data_paths = ((str(data_path).strip(),) if data_path else DEFAULT_DATA_PATHS)

        self.require_expected = bool(require_expected)
        # 非严格模式（require_expected=False）下「判定规则不完整」只警告一次，
        # 避免每条用例刷一行
        self._warned = False

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _as_list(value):
        """把 'a,b' / ['a','b'] / None 统一成字符串列表。"""
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(item).strip() for item in value if str(item).strip()]
        # 兼容中文逗号与分号分隔
        text = str(value).replace("，", ",").replace(";", ",")
        return [item.strip() for item in text.split(",") if item.strip()]

    @staticmethod
    def _pick(response, paths):
        """按候选路径依次取值，返回第一个非 None 的结果。"""
        for path in paths or ():
            value = base.parse_relation(str(path).split("."), response)
            if value is not None:
                return value
        return None

    @staticmethod
    def _as_http_codes(values):
        """
        把 HTTP 成功码配置统一成 int 集合。

        档案里通常写成 "200,201,204" 这样的字符串，也可能是列表；
        非法项直接忽略，全部非法时回退到默认值，避免把配置错误放大成"全量失败"。
        """
        default = {200, 201, 202, 204}
        items = ResponseSpec._as_list(values)
        if not items:
            return default
        codes = set()
        for item in items:
            try:
                codes.add(int(item))
            except (ValueError, TypeError):
                continue
        return codes or default

    @staticmethod
    def equal(actual, expected):
        """
        宽松比较：先按字符串（忽略大小写与首尾空白）比，再退回数值比较。

        这样 "200" == 200、"True" == "true"、"0" == 0 都能成立，
        符合「Excel 里写 200、接口返回字符串 '200'」这类常见情况。
        """
        if actual is None or expected is None:
            return actual is None and expected is None
        left, right = str(actual).strip(), str(expected).strip()
        if left.lower() == right.lower():
            return True
        try:
            # 用 float 兜一层，兼容 "200.0" 与 200 的比较
            return float(left) == float(right)
        except (ValueError, TypeError):
            return False

    # ------------------------------------------------------------------
    # 对外能力
    # ------------------------------------------------------------------
    def is_http_ok(self, response):
        """HTTP 状态码是否算成功。"""
        code = (response or {}).get("code")
        return code is not None and int(code) in self.http_ok

    def actual_code(self, response):
        """
        提取「实际业务码」。

        raw 风格或未配置业务码路径时，退化为 HTTP 状态码 —— 这样
        「只用 HTTP 状态码判成功」的老系统也能正常工作。
        """
        if not self.code_paths:
            return (response or {}).get("code")
        return self._pick(response, self.code_paths)

    def is_success(self, response, expected=None, strict=None):
        """
        判定一次响应是否成功。

        :param response: 统一响应字典
        :param expected: 用例给出的期望业务码；为空则用 success_values 判断
        :param strict:   两者都没有时的处理方式。
                         None（默认）跟随档案的 require_expected；
                         True 抛 CaseDataError（fail-closed），False 退回「只看 HTTP 状态码」。
                         分页抓取这类「框架内部、没有用例上下文」的调用应显式传 False。
        :return: bool
        :raise CaseDataError: 严格模式下「既无 expected_code 也无 success_values」
        """
        if not response:
            return False
        if not self.is_http_ok(response):
            return False

        actual = self.actual_code(response)

        # 用例给了期望值 -> 直接比对
        if expected not in (None, ""):
            return self.equal(actual, expected)

        # 没给期望值 -> 用风格自带的成功值集合
        if self.success_values:
            return any(self.equal(actual, value) for value in self.success_values)

        # raw 风格本来就只判 HTTP 状态码，不存在「判定规则缺失」
        if self.style == STYLE_RAW:
            return True

        if strict is None:
            strict = self.require_expected

        if strict:
            # fail-closed：宁可红，也不要「断言没跑却全绿」。
            # 错误信息必须直接给出两种修法，否则使用者只会看到一条莫名的失败。
            raise CaseDataError(
                "用例缺少 expected_code，无法判定业务是否成功（风格={}，实际业务码={}）。\n"
                "  这说明业务断言**根本没有执行**，而不是被测系统有问题。\n"
                "  修法（二选一）：\n"
                "    1) 在用例数据里补 expected_code（如 {} 风格填 200）；\n"
                "    2) 在系统档案 [response] 段配 success_values（如 success_values = 0,200），\n"
                "       让「成功值集合」成为该系统的统一口径。\n"
                "  确实只需判断 HTTP 状态码的接口（下载 / 健康检查 / 令牌），\n"
                "  请把用例的 check_business 置 false —— 这是显式声明，不会被误当成漏写。".format(
                    self.style, actual, self.style))

        # 非严格模式（档案显式关掉 require_expected）：保留旧行为，但必须留痕
        if not self._warned:
            self._warned = True
            logger.warning(
                "响应判定配置不完整：风格 '{}' 既无 expected_code 也无 success_values，"
                "当前按 require_expected=false 仅用 HTTP 状态码判成功。"
                "建议补 expected_code 或在档案 [response] 配置 success_values。".format(self.style))
        return True

    def message(self, response):
        """提取错误消息（找不到时返回空串），用于失败提示。"""
        value = self._pick(response, self.message_paths)
        return "" if value is None else str(value)

    def data(self, response):
        """提取业务数据体（data / result / rows ...）。"""
        return self._pick(response, self.data_paths)

    def describe(self):
        """给日志与 Allure 报告展示用的规则摘要。"""
        return {
            "判定风格": self.style,
            "业务码路径": " | ".join(self.code_paths) or "(用 HTTP 状态码)",
            "成功值集合": ",".join(self.success_values) or "(由用例 expected_code 提供)",
        }
