# -*- coding: utf-8 -*-
"""
接口层基类（API Object 基类）
=============================
PO（Page Object）思想在接口测试中的落地：用例层只关心「调哪个接口、期望什么」，
HTTP 细节（URL 组装、参数序列化、变量替换、认证、签名、关联提取、断言）全部收敛在这里。

BaseApi 提供 8 项统一能力：

    1. URL 组装      —— 相对路径拼主域名、支持域名别名（网关 + 多服务的微服务系统）
    2. 参数化        —— 请求前把 ${var} 替换为全局变量池中的真实值
    3. 认证          —— 按系统适配档案自动附加令牌（Bearer / Basic / API Key / Cookie / OAuth2）
    4. 协议钩子      —— 请求前签名、时间戳防重放、报文加密；响应后解密
    5. 统一请求      —— 复用 RequestSend（含 session、超时、证书校验、编码、XML/JSON/文本）
    6. 关联提取      —— 把响应中的关键字段写入全局变量池，供后续接口引用
    7. 统一断言      —— 业务成功判定（风格可配）+ HTTP 状态码 + 21 种字段级断言
    8. 用例生命周期  —— setup / teardown 前后置步骤、depends 依赖、分页抓取

「一套框架适配多个系统」的开关在 `config/systems/<系统>.ini`，
见 common/profile.py 与 docs/08-系统适配指南.md。

扩展方式：
    class LoginApi(BaseApi):
        def login(self, username, password):
            return self.request("post", "/v1/users/login",
                                data={"username": username, "password": password})
"""
from common import asserts
from common import base
from common.exceptions import CaseDataError, CaseSkipped
from common.profile import load_profile
from common.variable import GlobalVar
from utils import allureutil
from utils.logutil import logger
from utils.requestsutil import RequestSend

# 用例执行状态在变量池里的键前缀（供 depends 判断）
CASE_STATUS_PREFIX = "__case_status__:"

# 后置清理失败的登记前缀。
# 用途：teardown 失败不能改变用例结论（否则「清理接口挂了」会被误报成「业务有问题」），
# 但也绝不能无声吞掉 —— 那意味着脏数据已经在被测系统里躺着了。
# 这里登记到变量池，由会话收尾统一汇总告警。
TEARDOWN_FAIL_PREFIX = "__teardown_failed__:"


def _has_header(headers, name):
    """请求头里是否已存在某个键（大小写不敏感）。"""
    target = str(name).lower()
    return any(str(key).lower() == target for key in (headers or {}))


def _case_label(case):
    """用例的展示名：优先 id，其次 title，两者都没有时用「该用例」。"""
    label = case.get("id") or case.get("title") if isinstance(case, dict) else None
    return "用例 {!r} ".format(label) if label else "该用例"


class BaseApi:
    """所有接口对象的基类。"""

    def __init__(self, base_url=None, headers=None, timeout=None, session=None,
                 profile=None, auth=None, cookies=None):
        """
        :param base_url: 业务域名；不传则取系统适配档案（再回退全局配置 RunConfig.BASE_URL）
        :param headers:  该业务模块的公共请求头（会被单个请求的 headers 覆盖）
        :param timeout:  超时时间（秒）
        :param session:  复用的 requests.Session
        :param profile:  系统适配档案；不传则按 conf.ini 的 [env] system 自动加载
        :param auth:     认证策略；不传则用档案里声明的
        :param cookies:  该业务模块的公共 Cookie（会被单个请求的 cookies 覆盖）
        """
        self.profile = profile or load_profile()
        self.auth = auth or self.profile.auth

        # 域名：显式传入 > 档案（档案内部再让 CI 注入的域名优先）
        self.base_url = (base_url or self.profile.effective_base_url or "").rstrip("/")

        # 请求头：档案里声明的是系统级公共头，构造函数传入的是模块级的，后者优先
        self.common_headers = dict(self.profile.headers)
        self.common_headers.update(headers or {})

        # Cookie：档案 [cookies] 段声明的是系统级会话/租户标识（很多政务、ERP 系统靠它区分上下文），
        # 构造函数传入的是模块级的，后者优先。合并后的结果每次请求都会带上，用例仍可用
        # cookies 参数单独覆盖某一个键。
        self.common_cookies = dict(self.profile.cookies)
        self.common_cookies.update(cookies or {})

        self.timeout = timeout or self.profile.timeout
        self.client = RequestSend(timeout=self.timeout, session=session,
                                  encoding=self.profile.encoding,
                                  response_format=self.profile.response_format)
        self.res = None            # 最近一次请求的响应，断言与提取都基于它
        self._current_case = None  # 正在执行的用例（供钩子读取上下文）
        # 最近一条用例的后置清理失败信息（空列表表示清理正常）。
        # 失败不改变用例结论，但会登记到变量池，由会话收尾汇总告警 —— 脏数据必须可见。
        self.teardown_errors = []

    # ==================================================================
    # 一、URL 组装
    # ==================================================================
    def _full_url(self, path, host=None):
        """
        解析出完整地址。

        绝对地址原样返回；相对路径拼主域名；`别名:/path` 或 host 参数走档案的 [hosts] 映射。
        """
        path = str(path)
        if path.lower().startswith(("http://", "https://")):
            return path
        # 把实例域名作为兜底传进档案解析，保证 BaseApi(base_url=...) 的显式指定依然生效
        return self.profile.resolve_url(path, host=host, default_base=self.base_url)

    # ==================================================================
    # 二、参数化（${var} -> 全局变量池）
    # ==================================================================
    @staticmethod
    def resolve(data):
        """
        把数据中的 ${var} 占位符替换为全局变量池的值，并还原为 Python 对象。
        没有占位符时原样返回，避免无谓的序列化开销。
        """
        if data is None:
            return None
        if base.find(data):                 # 存在 ${var} 才做替换
            return base.relace_obj(data)
        return data

    # ==================================================================
    # 三、认证与钩子
    # ==================================================================
    def _apply_auth(self, method, headers, cookies, payload):
        """
        附加认证信息。

        令牌可能放在请求头、Cookie 或 query 参数上，因此三处都要能注入。
        当数据本身就走 query（GET 等）时，认证参数会合并进 payload，
        避免出现「认证参数把用例参数覆盖掉」的问题。

        :return: (headers, cookies, payload, extra_params)
        """
        auth_params = {}
        self.auth.apply(headers, cookies, auth_params)
        if not auth_params:
            return headers, cookies, payload, None

        location = RequestSend.body_location(method, headers)
        if location == "params":
            # 用例自身声明的参数优先级更高，放在后面合并
            merged = dict(auth_params)
            if isinstance(payload, dict):
                merged.update(payload)
            elif payload is None:
                pass
            else:
                return headers, cookies, payload, auth_params
            return headers, cookies, merged, None
        return headers, cookies, payload, auth_params

    def _apply_before_hooks(self, method, url, headers, cookies, payload):
        """执行请求前钩子（签名 / 时间戳 / 加密）。未配置钩子时零开销直接返回。"""
        if not self.profile.hooks.before_hooks:
            return headers, cookies, payload

        ctx = {
            "method": str(method).upper(),
            "url": url,
            "headers": headers,
            "cookies": cookies,
            "payload": payload,
            "location": RequestSend.body_location(method, headers),
            "case": self._current_case,
            "profile": self.profile,
        }
        ctx = self.profile.hooks.run_before(ctx)
        return (ctx.get("headers", headers),
                ctx.get("cookies", cookies),
                ctx.get("payload", payload))

    def _apply_after_hooks(self, response):
        """执行响应后钩子（解密 / 校验）。未配置钩子时零开销直接返回。"""
        if not self.profile.hooks.after_hooks:
            return response

        ctx = {"response": response, "case": self._current_case, "profile": self.profile}
        ctx = self.profile.hooks.run_after(ctx)
        return ctx.get("response", response)

    # ==================================================================
    # 四、统一请求
    # ==================================================================
    def request(self, method, path, data=None, headers=None, cookies=None, host=None, **kwargs):
        """
        发送一次接口请求。

        :param method:  http 方法
        :param path:    接口路径或完整 url；支持 `别名:/path` 指定域名
        :param data:    请求数据（dict 或 json/xml 字符串），挂载位置自动判断
        :param headers: 本次请求头，会与模块公共请求头合并
        :param cookies: cookie 字典
        :param host:    域名别名（对应档案 [hosts] 段）
        :return: 统一响应字典（见 utils.requestsutil）
        """
        # 路径里也可能带 ${var}（如 /v1/goods/${gid}），必须与报文体一样在请求前完成替换，
        # 否则 RESTful 风格「先造数据拿到 id、再按 id 查详情」的链路会带着占位符发出去。
        url = self._full_url(self.resolve(path), host)

        # 合并请求头：公共头 <- 入参头；随后统一做变量替换
        merged_headers = dict(self.common_headers)
        merged_headers.update(base.safe_loads(headers, {}) or {})
        merged_headers = self.resolve(merged_headers) or {}

        payload = self.resolve(base.safe_loads(data, data))

        # Cookie：公共 Cookie（档案 [cookies] + 构造函数传入）<- 本次请求传入；
        # 合并后再做变量替换，使档案里也能写 ${var}（令牌类 Cookie 常来自登录接口）
        cookie_jar = dict(self.common_cookies)
        cookie_jar.update(base.safe_loads(cookies, {}) or {})
        cookie_jar = self.resolve(cookie_jar) or {}

        # 认证（令牌进请求头 / Cookie / query）
        merged_headers, cookie_jar, payload, extra_params = self._apply_auth(
            method, merged_headers, cookie_jar, payload)

        # 协议钩子：签名、时间戳、加密必须在「认证之后、发送之前」
        merged_headers, cookie_jar, payload = self._apply_before_hooks(
            method, url, merged_headers, cookie_jar, payload)

        logger.info("【请求】{} {}".format(str(method).upper(), url))

        # 把请求要素附加到 Allure 报告，失败时可快速定位入参。
        # 挂载位置复用请求层的判定规则，保证「报告展示」与「实际发出」永远一致
        # （例如 DELETE 带 JSON 体时应显示为请求体，而不是查询参数）。
        payload_name = RequestSend.body_location(method, merged_headers)
        if payload_name == "params":
            allureutil.attach_request(method, url, headers=merged_headers, params=payload)
        else:
            allureutil.attach_request(method, url, headers=merged_headers, body=payload)

        send_kwargs = dict(kwargs)
        if extra_params:
            send_kwargs["params"] = extra_params

        self.res = self.client.send(
            url, method,
            data=payload,
            headers=merged_headers or None,
            cookies=cookie_jar or None,
            **send_kwargs
        )

        # 响应后钩子（解密等）需要在断言与提取之前执行
        self.res = self._apply_after_hooks(self.res)

        # 把响应附加到 Allure 报告
        allureutil.attach_response(self.res)
        return self.res

    # ==================================================================
    # 五、关联提取（响应 -> 全局变量池）
    # ==================================================================
    def extract(self, relation):
        """
        按关联表达式从响应中提取变量并写入全局变量池。

        路径以「完整响应」为根（与 Excel 中 relation 列写法一致），例如：
            ticket=body.data.ticket   ->   res["body"]["data"]["ticket"]
            uid=body.data.user.id

        :param relation: 形如 "ticket=body.data.ticket,uid=body.data.user.id"
        :return: 本次提取到的 {变量名: 值}
        """
        if not relation or str(relation).strip().lower() in ("none", "null", ""):
            return {}

        # 以完整响应（含 code / body）为解析根，与 Excel 中的 relation 写法保持一致
        root = self.res if self.res else None
        extracted = {}

        for expr in str(relation).split(","):
            expr = expr.strip()
            if not expr:
                continue
            name, value = base.parse_expression(expr, root)
            GlobalVar.set(name, value)
            extracted[name] = value
            logger.info("【关联】{} = {}".format(name, value))

        return extracted

    # ==================================================================
    # 六、统一断言
    # ==================================================================
    def check_status(self, expected_code):
        """断言 HTTP 状态码。"""
        actual = self.res["code"] if self.res else None
        # 先判空再比较：未取得响应时应给出清晰的断言失败，而不是 int(None) 的 TypeError
        assert actual is not None and int(actual) == int(expected_code), \
            "HTTP 状态码断言失败：期望 {}，实际 {}（请确认请求是否已成功发出）".format(
                expected_code, actual)
        return True

    def check_success(self, expected=None, msg=""):
        """
        按**系统适配档案**的规则断言「业务成功」。

        这是替代 check_business_code 的通用断言：
            档案 [response] style = status  -> 断言 body.status == expected（与原行为一致）
            档案 [response] style = code    -> 断言 body.code == expected
            档案 [response] style = success -> 断言 body.success 为真（expected 可留空）

        :param expected: 期望业务码；留空则用档案声明的「成功值集合」判断
        """
        spec = self.profile.response
        if spec.is_success(self.res, expected):
            return True

        actual = spec.actual_code(self.res)
        message = spec.message(self.res)
        raise AssertionError(
            "{}业务断言失败：期望 {}，实际 {}（风格={}）\n"
            "  服务端消息：{}\n"
            "  响应摘要：{}".format(
                msg,
                expected if expected not in (None, "") else "成功（{}）".format(
                    ",".join(spec.success_values) or "HTTP 通过"),
                actual, spec.style,
                message or "(无)",
                asserts.summary(self.res)))

    def check_business_code(self, expected_code=200, path="status"):
        """
        断言业务状态码（默认取 body.status）。

        保留此方法是为了兼容存量用例；新增用例建议改用 check_success()，
        由系统适配档案决定去哪个字段取业务码，换系统时无需改用例。
        """
        body = self.body if isinstance(self.body, dict) else {}
        actual = body.get(path)
        assert actual is not None and int(actual) == int(expected_code), \
            "业务状态码断言失败：期望 {}，实际 {}（响应体={}）".format(expected_code, actual, body)
        return True

    def check_json(self, json_path, expected):
        """
        断言响应中任意路径的值。

        路径同样以「完整响应」为根，故响应体字段需写成 body.xxx。

        :param json_path: 点号路径，如 "body.data.ticket"、"body.status"
        :param expected:  期望值
        """
        actual = base.parse_relation(str(json_path).split("."), self.res)
        assert actual == expected, \
            "字段断言失败：{} 期望 {}，实际 {}".format(json_path, expected, actual)
        return True

    # ------------------------------------------------------------------
    # 字段级断言（21 种，实现见 common/asserts.py）
    # ------------------------------------------------------------------
    def assert_equals(self, path, expected, msg=""):
        """字段值相等（宽松比较：200 与 '200'、true 与 'True' 都算相等）。"""
        return asserts.equals(self.res, path, expected, msg)

    def assert_not_equals(self, path, expected, msg=""):
        """字段值不相等。"""
        return asserts.not_equals(self.res, path, expected, msg)

    def assert_contains(self, path, expected, msg=""):
        """包含子串（字符串）、元素（列表）或键（字典）。"""
        return asserts.contains(self.res, path, expected, msg)

    def assert_not_contains(self, path, expected, msg=""):
        """不包含。"""
        return asserts.not_contains(self.res, path, expected, msg)

    def assert_startswith(self, path, expected, msg=""):
        """字符串以指定前缀开头。"""
        return asserts.startswith(self.res, path, expected, msg)

    def assert_endswith(self, path, expected, msg=""):
        """字符串以指定后缀结尾。"""
        return asserts.endswith(self.res, path, expected, msg)

    def assert_regex(self, path, pattern, msg=""):
        """字段值匹配正则（包含匹配）。"""
        return asserts.regex(self.res, path, pattern, msg)

    def assert_type(self, path, expected, msg=""):
        """类型断言：str/int/float/bool/list/dict/none/number。"""
        return asserts.type_is(self.res, path, expected, msg)

    def assert_exists(self, path, msg=""):
        """字段存在且不为 None。"""
        return asserts.exists(self.res, path, msg)

    def assert_not_exists(self, path, msg=""):
        """字段不存在或为 None。"""
        return asserts.not_exists(self.res, path, msg)

    def assert_in(self, path, expected, msg=""):
        """字段取值在给定集合内（'a,b,c' 或列表）。"""
        return asserts.in_(self.res, path, expected, msg)

    def assert_not_in(self, path, expected, msg=""):
        """字段取值不在给定集合内。"""
        return asserts.not_in(self.res, path, expected, msg)

    def assert_gt(self, path, expected, msg=""):
        """大于（数值比较）。"""
        return asserts.gt(self.res, path, expected, msg)

    def assert_ge(self, path, expected, msg=""):
        """大于等于。"""
        return asserts.ge(self.res, path, expected, msg)

    def assert_lt(self, path, expected, msg=""):
        """小于。"""
        return asserts.lt(self.res, path, expected, msg)

    def assert_le(self, path, expected, msg=""):
        """小于等于。"""
        return asserts.le(self.res, path, expected, msg)

    def assert_length(self, path, expected, msg=""):
        """长度等于（字符串 / 列表 / 字典）。"""
        return asserts.length(self.res, path, expected, msg)

    def assert_empty(self, path, msg=""):
        """为空（None / '' / [] / {}）。"""
        return asserts.empty(self.res, path, msg)

    def assert_not_empty(self, path, msg=""):
        """非空。"""
        return asserts.not_empty(self.res, path, msg)

    def assert_elapsed(self, max_ms, msg=""):
        """响应耗时不超过指定毫秒数。"""
        return asserts.elapsed(self.res, None, max_ms, msg)

    def assert_schema(self, schema, path=None, msg=""):
        """响应体符合 JSON Schema（需可选依赖 jsonschema）。"""
        return asserts.schema(self.res, path, schema, msg)

    def assert_op(self, name, path=None, value=None, msg=""):
        """
        按算子名执行断言 —— 用例 expects 字段的底层入口。

        :param name: 见 common.asserts.OP_DOC（equals / contains / gt / elapsed ...）
        """
        return asserts.run_op(name, self.res, path, value, msg)

    # ==================================================================
    # 七、用例生命周期
    # ==================================================================
    def check_expects(self, expects):
        """
        批量执行断言。

        支持两种写法（可混用）：

            YAML / JSON：列表
                expects:
                  - op: contains
                    path: body.msg
                    value: 操作成功
                  - op: gt
                    path: body.data.total
                    value: 0

            表格简写：`op:路径=期望值` 用分号分隔
                contains:body.msg=操作成功; gt:body.data.total=0; elapsed=3000

        注意：简写里 `=` 只按**第一个**切分，因此期望值本身可以带等号。
        """
        items = self._as_expects(expects)
        if not items:
            return True
        for item in items:
            logger.info("【断言】{} {} {}".format(
                item["op"], item.get("path") or "", item.get("value", "")))
            self.assert_op(item["op"], item.get("path"), item.get("value"), item.get("msg", ""))
        return True

    @staticmethod
    def _as_expects(expects):
        """把 expects 的多种写法统一成 [{'op','path','value','msg'}]。"""
        if expects in (None, "", []):
            return []

        # 字符串：优先当 JSON 解析，失败再按简写语法拆
        if isinstance(expects, str):
            text = expects.strip()
            if not text:
                return []
            if text[0] in "[{":
                parsed = base.safe_loads(text, None)
                if parsed is not None:
                    return BaseApi._as_expects(parsed)
            results = []
            for chunk in text.split(";"):
                chunk = chunk.strip()
                if not chunk:
                    continue
                left, has_value, value = chunk.partition("=")
                op, _, path = left.partition(":")
                results.append({
                    "op": op.strip(),
                    "path": path.strip() or None,
                    "value": value if has_value else None,
                })
            return results

        # 字典：单条断言
        if isinstance(expects, dict):
            if not expects:                    # 空字典等价于「不做断言」
                return []
            return [{
                "op": expects.get("op") or expects.get("断言"),
                "path": expects.get("path") or expects.get("路径"),
                "value": expects.get("value") if "value" in expects else expects.get("值"),
                "msg": expects.get("msg", ""),
            }]

        # 列表：递归展开每一项
        if isinstance(expects, (list, tuple)):
            results = []
            for item in expects:
                results.extend(BaseApi._as_expects(item))
            return results

        return []

    def check_depends(self, case):
        """
        检查用例依赖：depends 里列出的用例必须都已执行且通过。

        :raises CaseSkipped: 依赖未执行或未通过 —— 用例层应转为 pytest.skip，
                             因为「前置没成功」不等于「本用例的实现有问题」。
        """
        raw = (case or {}).get("depends")
        if not raw:
            return True

        text = str(raw).replace("，", ",")
        for case_id in [item.strip() for item in text.split(",") if item.strip()]:
            status = GlobalVar.get(CASE_STATUS_PREFIX + case_id, None)
            if status is None:
                raise CaseSkipped(
                    "依赖的用例 id={} 尚未执行，无法确认前置条件（请检查用例顺序或 depends 配置）"
                    .format(case_id))
            if status != "pass":
                raise CaseSkipped("依赖的用例 id={} 执行未通过，本用例跳过".format(case_id))
        return True

    @staticmethod
    def record_case_status(case, is_pass):
        """登记用例执行结果，供后续用例的 depends 判断。"""
        case_id = (case or {}).get("id")
        if case_id in (None, ""):
            return
        GlobalVar.set(CASE_STATUS_PREFIX + str(case_id), "pass" if is_pass else "fail")

    @staticmethod
    def _as_steps(steps):
        """把 setup / teardown 的多种写法统一成列表。"""
        if steps in (None, "", [], {}):
            return []
        if isinstance(steps, str):
            parsed = base.safe_loads(steps.strip(), None)
            if parsed is not None and parsed != steps:
                return BaseApi._as_steps(parsed)
            return [steps]                     # 形如 "post /v1/x" 的单步简写
        if isinstance(steps, dict):
            return [steps]
        if isinstance(steps, (list, tuple)):
            return [item for item in steps if item]
        return []

    def run_steps(self, steps, label="步骤"):
        """
        执行一组前置 / 后置步骤（造数据、清理数据）。

        每一步与一条用例同构，支持 url / method / headers / cookies /
        request_body / content_type / host / relation。

        :param steps: 步骤列表；也支持 "post /v1/x" 这样的单步简写
        :param label: 日志里的分组名
        :return: 各步骤的响应列表
        """
        responses = []
        for index, step in enumerate(self._as_steps(steps), 1):
            if isinstance(step, str):
                parts = step.split(None, 1)
                if len(parts) < 2:
                    logger.warning("{}第 {} 步格式无法识别，已跳过：{}".format(label, index, step))
                    continue
                step = {"method": parts[0], "url": parts[1]}

            logger.info("【{}】第 {} 步：{} {}".format(
                label, index, step.get("method"), step.get("url")))
            self._do_request(step)
            self.extract(step.get("relation") or step.get("extract"))
            responses.append(self.res)
        return responses

    def _do_request(self, case):
        """按一条用例数据发起请求（不含断言）。"""
        headers = base.safe_loads(case.get("headers"), {}) or {}

        # Content-Type：用例显式声明 > 系统档案默认值。
        # 表格里既可以用 content_type，也兼容原有的 request_type 列。
        content_type = (case.get("content_type") or case.get("request_type")
                        or self.profile.content_type)
        if content_type and not _has_header(headers, "Content-Type"):
            headers["Content-Type"] = str(content_type)

        self.request(
            case.get("method"),
            case.get("url"),
            data=base.safe_loads(case.get("request_body"), None),
            headers=headers,
            cookies=base.safe_loads(case.get("cookies"), {}),
            host=case.get("host"),
        )
        return self.res

    @staticmethod
    def _validate_case(case):
        """
        校验用例数据是否「至少能发出一次请求」。

        为什么要在发请求之前拦住：
            空用例或漏填 url / method 时，若直接往下走，会分别表现为
            「请求发出去了但业务断言失败」和「int(None) 的 TypeError」，
            两者都和真实原因（数据写错了）毫无关系。提前用明确的错误信息
            把问题定位到「哪一列没填」，比让使用者顺着堆栈猜要省事得多。

        :raise CaseDataError: 用例为空、非字典、缺 url 或 method
        """
        if not isinstance(case, dict):
            raise CaseDataError(
                "用例数据必须是字典，实际为 {}：{!r}。\n"
                "  请检查数据源读取逻辑，或该行用例是否被错误地写成了字符串。".format(
                    type(case).__name__, case))
        if not case:
            raise CaseDataError(
                "用例数据为空（{}）。一条可执行用例至少需要 url 与 method 两个字段：\n"
                "  Excel：在 test_case_list 表对应行填 D 列 url、E 列 method；\n"
                "  YAML ：在 -- 分隔的用例块里写 url: /xxx 与 method: get。")
        if not str(case.get("url") or "").strip():
            raise CaseDataError(
                "{}缺少 url，无法发出请求。\n"
                "  Excel：检查 D 列 url；YAML：检查 url: 字段。\n"
                "  当前用例内容：{!r}".format(_case_label(case), case))
        if not str(case.get("method") or "").strip():
            raise CaseDataError(
                "{}缺少 method（如 get / post），无法发出请求。\n"
                "  Excel：检查 E 列 method；YAML：检查 method: 字段。\n"
                "  当前用例内容：{!r}".format(_case_label(case), case))

    def run_case(self, case):
        """
        按一条用例数据执行完整生命周期：前置 -> 请求 -> 关联 -> 断言 -> 后置清理。

        :param case: 用例字典
        :return: 统一响应字典

        识别字段（除前四个为原有字段外，其余都是新增能力，不写即不生效）：
            url / method / headers / cookies / request_body / relation   原有
            host           域名别名（对应档案 [hosts]）
            content_type   覆盖默认请求体类型（也兼容 request_type 列）
            expects        断言列表（简写或结构化，见 check_expects）
            setup          前置步骤（造数据）
            teardown       后置步骤（清理数据，**断言失败也会执行**）
            depends        依赖的用例 id，逗号分隔
            check_business 是否做业务码断言，默认 true；令牌/下载/健康检查类接口可置 false
            id             用例编号（depends 与结果登记都靠它）
        """
        case = case or {}
        self._current_case = case
        self.teardown_errors = []

        # 清掉上一条用例的响应：被 depends 跳过的用例不会发请求，
        # 若沿用旧响应，结果回写会把「上一条的响应 + 失败标记」记到本用例头上，
        # 排查时会被彻底带偏。置 None 后，被跳过的用例不留下任何执行痕迹。
        self.res = None

        # 依赖不满足时抛 CaseSkipped，由用例层转成 pytest.skip
        self.check_depends(case)

        # 数据完整性校验（缺 url / method 直接报明确错误，见方法注释）
        self._validate_case(case)

        main_res = None          # 主请求的响应（用例响应）；没发出则保持 None
        is_pass = False
        try:
            # 前置步骤也放在 try 内：若第 2 步失败，第 1 步造的数据已经落到对方系统里，
            # 必须让 finally 里的 teardown 照常执行，否则脏数据无人清理、也无人知晓。
            self.run_steps(case.get("setup"), label="前置")

            self._do_request(case)
            main_res = self.res
            self.extract(case.get("relation") or case.get("extract"))
            self.check_expects(case.get("expects"))
            # 业务成功判定：期望值来自数据的 expected_code，判定风格来自系统档案。
            # 放在这里而不是各驱动里，是为了让 Excel / YAML / MySQL 三个数据源
            # 共用同一套判定规则 —— 换系统只改档案，三个驱动都不用动。
            #
            # check_business 为假时跳过业务码断言：令牌接口、文件下载、健康检查
            # 这类接口不遵循业务码信封，用 expects + HTTP 状态码判定更合适。
            if base.to_bool(case.get("check_business"), True):
                self.check_success(case.get("expected_code"))
            is_pass = True
            return main_res
        finally:
            self.record_case_status(case, is_pass)

            # 后置清理必须执行，即使断言失败 —— 否则造出来的脏数据会污染
            # 后续用例，以及下一次构建。清理本身的异常只记日志，不掩盖原始失败；
            # 但会登记下来供会话收尾汇总（静默吞掉 = 脏数据无人知，这是更危险的失败）。
            try:
                self.run_steps(case.get("teardown"), label="后置清理")
            except Exception as exc:                       # noqa: BLE001
                self.teardown_errors.append(str(exc))
                case_id = case.get("id")
                if case_id not in (None, ""):
                    GlobalVar.set(TEARDOWN_FAIL_PREFIX + str(case_id), str(exc))
                logger.error("后置清理步骤执行失败（不影响用例结论，但可能残留脏数据）：{}".format(exc))
            finally:
                # 把「用例本身的响应」放回去：teardown 又发了请求，会把 self.res 换成
                # 清理接口的响应，而用例层回写结果（Excel 的 response 列）与报告附件
                # 读的都是 self.res —— 不还原就会记成一段与业务毫无关系的清理响应。
                # 主请求压根没发出时（setup 失败）保持 None，不留下误导性的半成品。
                self.res = main_res
                self._current_case = None

    # ==================================================================
    # 八、分页抓取（中台 / 商城的列表接口）
    # ==================================================================
    def paginate(self, path, method="get", data=None, headers=None, host=None,
                 page_field="page", size_field="pageSize", start=1, size=20,
                 max_pages=100, data_path=None, stop=None, **kwargs):
        """
        翻页抓取列表接口的全部数据。

        :param data_path: 每页列表在响应中的路径（默认用档案的 data_path 候选）
        :param stop:      回调 (page_items, response) -> bool；返回 True 提前结束。
                          默认在「本页条数少于 size」时结束
        :param max_pages: 安全阀，防止服务端不翻页导致死循环
        :return: 汇总后的列表
        """
        collected = []
        page = int(start)

        for _ in range(int(max_pages)):
            payload = dict(base.safe_loads(data, {}) or {})
            if page_field:
                payload[page_field] = page
            if size_field:
                payload[size_field] = size

            self.request(method, path, data=payload, headers=headers, host=host, **kwargs)

            # 分页是框架内部动作，没有「用例期望码」的上下文，
            # 因此显式放开 fail-closed 检查：只用档案的成功值集合 / HTTP 状态码判断。
            if not self.profile.response.is_success(self.res, strict=False):
                raise AssertionError(
                    "分页抓取第 {} 页失败：{}".format(page, asserts.summary(self.res)))

            items = None
            if data_path:
                items = base.parse_relation(str(data_path).split("."), self.res)
            if items is None:
                items = self.profile.response.data(self.res)
            if items is None:
                logger.warning("分页抓取第 {} 页未找到列表数据，已停止".format(page))
                break

            if not isinstance(items, list):
                items = [items]
            collected.extend(items)
            logger.info("【分页】第 {} 页取到 {} 条，累计 {} 条".format(
                page, len(items), len(collected)))

            if stop is not None:
                if stop(items, self.res):
                    break
            elif len(items) < int(size):
                break

            page += 1

        return collected

    # ==================================================================
    # 便捷属性
    # ==================================================================
    @property
    def body(self):
        """最近一次响应的响应体。"""
        return self.res["body"] if self.res else None

    @property
    def code(self):
        """最近一次响应的 HTTP 状态码。"""
        return self.res["code"] if self.res else None

    @property
    def data(self):
        """最近一次响应的业务数据体（按档案配置的路径提取）。"""
        return self.profile.response.data(self.res)

    @property
    def business_code(self):
        """最近一次响应的实际业务码（按档案配置的风格提取）。"""
        return self.profile.response.actual_code(self.res)

    @property
    def message(self):
        """最近一次响应的服务端消息。"""
        return self.profile.response.message(self.res)

    @property
    def elapsed(self):
        """最近一次响应耗时（毫秒）。"""
        return self.res.get("elapsed") if self.res else None

    @property
    def teardown_failed(self):
        """
        最近一条用例的后置清理是否失败。

        失败意味着「用例结论可能是通过的，但被测系统里可能残留了脏数据」，
        用例层据此在报告中显式提示，避免清理失败被静默吞掉。
        """
        return bool(self.teardown_errors)
