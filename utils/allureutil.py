# -*- coding: utf-8 -*-
"""
Allure 报告工具层
=================
统一封装 Allure 的常用能力，让接口层与用例层不必到处写 `import allure` 的细节：

    attach_request       把请求要素（方法/地址/头/参数/体）附加到报告
    attach_response      把响应（状态码/耗时/响应体）附加到报告
    attach_text/json     附加自定义内容
    step(title)          步骤上下文（未安装 allure 时自动退化为空上下文）
    write_environment    写入报告「环境」页信息

安全说明（重要）：
    报告会被归档、被转发、被托管到 CI 服务器，因此**写入报告前一律先脱敏** ——
    口令 / 令牌 / 票据在报告里以打码形式呈现（见 common/mask.py）。
    只影响「报告里怎么显示」，不影响真实发出的请求内容。

兼容性说明：
    未安装 allure-pytest 时，本模块所有方法自动降级为空操作，
    框架仍可正常运行，不会因为缺少 Allure 而报错。
"""
import contextlib
import json
import os

from common import mask
from config import settings

try:
    import allure
except ImportError:                 # 未安装时降级
    allure = None

# Allure 是否可用（供上层判断，如需在报告中标记降级信息）
ALLURE_AVAILABLE = allure is not None

# 单个附件最大字符数：防止超大响应体拖慢报告渲染。
# 取值来自配置中心（conf.ini [report] max_attach_len / AMSAPI_ALLURE_MAX_ATTACH_LEN），
# 不再写死在代码里。
MAX_ATTACH_LEN = settings.ReportConfig.MAX_ATTACH_LEN


# ----------------------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------------------
def _to_text(content):
    """把任意内容转为可读文本，超长自动截断。"""
    if isinstance(content, (dict, list)):
        try:
            text = json.dumps(content, ensure_ascii=False, indent=2)
        except (TypeError, ValueError):
            text = str(content)
    else:
        text = str(content)

    if len(text) > MAX_ATTACH_LEN:
        text = "{}\n\n...（内容过长已截断，原始长度 {} 字符）".format(text[:MAX_ATTACH_LEN], len(text))
    return text


# ----------------------------------------------------------------------
# 附件
# ----------------------------------------------------------------------
def attach_text(name, content):
    """附加纯文本附件（写入前脱敏）。"""
    if ALLURE_AVAILABLE:
        allure.attach(_to_text(mask.mask_payload(content)), name=name,
                      attachment_type=allure.attachment_type.TEXT)


def attach_json(name, content):
    """附加 JSON 附件（在报告中带语法高亮；写入前脱敏）。"""
    if ALLURE_AVAILABLE:
        allure.attach(_to_text(mask.mask_payload(content)), name=name,
                      attachment_type=allure.attachment_type.JSON)


def attach_request(method, url, headers=None, params=None, body=None):
    """
    把一次请求的关键信息附加到报告，便于失败时快速定位。

    请求头里的 Authorization / Cookie、参数与请求体里的口令与令牌
    会先经脱敏再写入报告。

    :param method:  http 方法
    :param url:     完整请求地址
    :param headers: 请求头
    :param params:  query 参数
    :param body:    请求体
    """
    if not ALLURE_AVAILABLE:
        return

    headers = mask.mask_payload(headers) if headers else headers
    params = mask.mask_payload(params) if params else params
    body = mask.mask_payload(body) if body else body

    sections = ["{} {}".format(str(method).upper(), url)]
    if headers:
        sections.append("\n【请求头】\n{}".format(_to_text(headers)))
    if params:
        sections.append("\n【查询参数】\n{}".format(_to_text(params)))
    if body:
        sections.append("\n【请求体】\n{}".format(_to_text(body)))

    attach_text("请求信息", "\n".join(sections))


def attach_response(response):
    """
    把统一响应字典附加到报告（响应体先脱敏）。

    :param response: RequestSend.send() 的返回值
    """
    if not ALLURE_AVAILABLE or not isinstance(response, dict):
        return

    summary = (
        "状态码：{}\n"
        "耗时：{} ms\n"
        "请求地址：{}\n"
        "请求方法：{}"
    ).format(
        response.get("code"),
        response.get("elapsed"),
        response.get("url"),
        response.get("method"),
    )
    attach_text("响应信息", summary)
    attach_json("响应体", response.get("body"))


# ----------------------------------------------------------------------
# 步骤
# ----------------------------------------------------------------------
def step(title):
    """
    步骤上下文，用于在报告中形成可折叠的步骤树。

    用法：
        with step("登录"):
            api.login(...)

    未安装 allure 时返回空上下文，调用方无需改动。
    """
    if ALLURE_AVAILABLE:
        return allure.step(title)
    return contextlib.nullcontext()


# ----------------------------------------------------------------------
# 环境信息
# ----------------------------------------------------------------------
def write_environment(results_dir, env):
    """
    写入 Allure 结果目录下的 environment.properties，报告中「环境」页可见。

    :param results_dir: allure 结果目录
    :param env:         环境信息字典
    """
    if not results_dir:
        return
    try:
        os.makedirs(results_dir, exist_ok=True)
        path = os.path.join(results_dir, "environment.properties")
        with open(path, "w", encoding="utf-8") as fp:
            for key, value in env.items():
                fp.write("{}={}\n".format(key, value))
    except OSError:
        pass
