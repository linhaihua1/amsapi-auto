# -*- coding: utf-8 -*-
"""
敏感信息脱敏层（Mask）
======================
把「口令 / 令牌 / 票据 / 签名 / 会话」等敏感值在**输出侧**统一打码，
使日志文件与 Allure 报告不再保留明文。

为什么需要这一层
----------------
框架为了便于排查，默认以 DEBUG 级别完整打印请求头、查询参数与响应体；
Allure 附件同理。这些内容里包含真实的口令与会话令牌，一旦随构建制品归档、
被转发到群里、或托管在 CI 服务器上，等同于口令外泄 —— 在合规审计中属于高危项。

设计原则（很重要）
------------------
1. **只改「怎么写出来」，不改「怎么发出去」**
   脱敏发生在「日志格式化」与「报告附件生成」这两个输出环节，
   真实请求内容一字不改，业务逻辑零影响（用例、接口对象、断言全部不用动）。
2. **默认开启，可关**
   `[log] mask_sensitive = false` 或 `AMSAPI_MASK_SENSITIVE=false` 可关闭（仅排查时用）。
3. **打码不可还原**
   只保留少量首尾字符，用于判断「是不是同一个令牌」；不做任何可逆变换。
   `[mask] mode = full` 可切换为全遮蔽（连首尾字符也不保留），生产环境建议用它。
4. **不误伤业务字段**
   只有「字段名本身是敏感词」才打码，`status` / `code` / `data` / `total`
   这类业务字段一律原样保留，报告可读性不受影响。

用法
----
    from common import mask

    mask.mask_value("p@ssw0rd")                       # 'p@s****rd'
    mask.mask_mapping({"password": "p@ssw0rd"})       # {'password': 'p@s****rd'}
    mask.mask_text('{"token": "abc123456"}')          # '{"token": "abc****56"}'
    mask.mask_payload(任意 dict / list / str)          # 统一入口
    mask.sanitize_dir(报告目录)                        # 落盘后兜底扫一遍（见文末）
"""
import json
import os
import re

from config import settings

# 打码字符
MASK_CHAR = "*"
# 打码后显示的固定长度（避免从长度反推原值长度）
MASK_MIDDLE = MASK_CHAR * 4

# ----------------------------------------------------------------------
# 一、敏感字段名判定
# ----------------------------------------------------------------------
# 判定规则：把字段名拆成「单词」后逐个比对，因此下面这些写法都能命中：
#     password / pass_word / userPassword / PASSWORD
#     access-ticket / accessTicket / X-Auth-Token（拆出 token）
#     api_key / apiKey / x-api-key
# 之所以不用「子串包含」而用「拆词」，是为了避免 design、assign、tokenizer
# 这类无关字段被误打码 —— 报告里字段被莫名打码比不打码更难排查。
SENSITIVE_WORDS = frozenset({
    "password", "passwd", "pwd", "pass",
    "secret", "secrets",
    "token", "ticket", "authorization", "auth", "session", "cookie",
    "sign", "signature", "salt", "credential", "credentials",
    "cert", "certificate", "passphrase",
})

# 「连写」形式（拆词后仍是单个词，需要单独列出）
SENSITIVE_JOINED = frozenset({
    "apikey", "appkey", "accesskey", "privatekey", "secretkey", "publickey",
    "accesstoken", "refreshtoken", "authtoken", "sessionid", "jsessionid",
    "clientsecret", "appsecret", "accesssecret",
})

# 驼峰转空格：userName -> user Name（后续统一小写拆分）
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
# 非字母数字作为分隔符
_SPLIT_RE = re.compile(r"[^0-9A-Za-z]+")

# 额外的敏感字段名（来自 conf.ini [mask] extra_keys，逗号分隔）
_EXTRA_WORDS_CACHE = {}


def _extra_words():
    """读取配置里追加的敏感字段名（缓存，避免每条日志重复解析配置）。"""
    raw = str(getattr(settings.MaskConfig, "EXTRA_KEYS", "") or "")
    cached = _EXTRA_WORDS_CACHE.get(raw)
    if cached is None:
        cached = frozenset(
            word.strip().lower() for word in re.split(r"[,\s]+", raw) if word.strip())
        _EXTRA_WORDS_CACHE[raw] = cached
    return cached


def key_words(name):
    """把字段名拆成小写单词列表（兼容驼峰、下划线、中划线、点号）。"""
    text = _CAMEL_RE.sub(r"\1 \2", str(name))
    return [word for word in _SPLIT_RE.split(text.lower()) if word]


def is_sensitive_key(name):
    """
    判断字段名是否属于敏感字段。

    :param name: 字段名，如 password / access-ticket / userToken
    :return: bool
    """
    if name is None:
        return False
    words = key_words(name)
    if not words:
        return False

    extra = _extra_words()
    for word in words:
        if word in SENSITIVE_WORDS or word in extra:
            return True

    # 连写形式（apiKey 拆成 api + key，需要拼回整体再比一次）
    joined = "".join(words)
    if joined in SENSITIVE_JOINED or joined in extra:
        return True
    # 去掉常见前缀后再比：myApiKey -> apikey
    for prefix in ("my", "the", "x"):
        if joined.startswith(prefix) and joined[len(prefix):] in SENSITIVE_JOINED:
            return True
    return False


def clear_cache():
    """清空配置缓存（改了 [mask] extra_keys 或单元测试需要隔离状态时调用）。"""
    _EXTRA_WORDS_CACHE.clear()


# ----------------------------------------------------------------------
# 二、打码
# ----------------------------------------------------------------------
def mask_value(value):
    """
    对敏感值打码。

    规则（[mask] mode 控制）：
        partial（默认）  保留前 3 / 后 2 个字符，中间以 **** 替代
        full             全部替换为 ****（生产环境建议）

    :param value: 原始值（任意类型，统一转字符串）
    :return: 打码后的字符串
    """
    if value is None:
        return value
    text = value if isinstance(value, str) else str(value)
    if not text:
        return text

    mode = str(getattr(settings.MaskConfig, "MODE", "partial") or "partial").strip().lower()
    if mode == "full":
        return MASK_MIDDLE

    keep_prefix = max(0, int(getattr(settings.MaskConfig, "KEEP_PREFIX", 3) or 0))
    keep_suffix = max(0, int(getattr(settings.MaskConfig, "KEEP_SUFFIX", 2) or 0))
    if len(text) <= keep_prefix + keep_suffix:
        return MASK_MIDDLE
    return "{}{}{}".format(text[:keep_prefix], MASK_MIDDLE, text[-keep_suffix:])


def mask_mapping(data):
    """
    递归地对比对结构（dict / list）打码。

    两条规则同时生效：
        · 字段名敏感的项 → 整个值打码（password / token / secret ...）
        · 字段名不敏感的字符串 → 按**文本规则**脱敏

    第二条是必需的：口令经常以「文本形式」藏在非敏感字段的值里，例如
        {"msg": "认证失败 password=abc123"}
    只按键名打码会整条漏过去 —— 而这份 dict 会被日志 Filter 与 Allure
    附件直接落盘，是最典型的明文泄漏形态。

    结构保持 dict / list 不变，因此 _to_text() 的 JSON 缩进展示不受影响。
    脱敏关闭时（[log] mask_sensitive = false）原样返回。
    """
    if not enabled():
        return data
    if isinstance(data, dict):
        masked = {}
        for key, value in data.items():
            if is_sensitive_key(key):
                masked[key] = mask_value(value)
            elif isinstance(value, str):
                masked[key] = mask_text(value)
            else:
                masked[key] = mask_mapping(value)
        return masked
    if isinstance(data, (list, tuple)):
        return [mask_mapping(item) for item in data]
    if isinstance(data, str):
        return mask_text(data)
    return data


# ----------------------------------------------------------------------
# 三、文本脱敏（用于已被 .format() 拼成字符串的日志内容）
# ----------------------------------------------------------------------
# 匹配 `字段名 = 值` / `字段名: 值`（值可以是带引号的字符串）。
# 字段名两侧允许带引号：日志里常见 dict / JSON 的原样打印，
# 形如 `{'password': 'xxx'}` 与 `{"token": "xxx"}` —— 不处理引号就会整条漏掉。
#
# 值的字符集**必须排除 URL 分隔符**（? & #）：
# 形如 `.../login?username=demo_user&password=demo_password` 的请求地址，
# 若值能吃掉 `&`，`username=demo_user&password=demo_password` 会被当成一个整体
# 挂在「非敏感的 username」名下，真正的口令就整条漏过去了。
_KV_RE = re.compile(
    r"(?P<name>[\"']?[A-Za-z_][\w\-.]*[\"']?)"
    r"(?P<sep>\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s,;)\]}\"'&?#]+)"
)

# 匹配裸令牌串（Bearer xxx / Basic xxx）
# 分隔符单独成组：替换时原样保留空格，否则输出会变成 `Bearerabc****56`，
# 既难读也无法再被下游按 `Bearer <token>` 解析。
_TOKEN_RE = re.compile(
    r"\b(Bearer|Basic|Token)(\s+)([A-Za-z0-9\-._~+/=]{6,})", re.IGNORECASE)

# 认证方案名：它们本身不是秘密，真正的秘密是紧随其后的令牌。
# 若不单独识别，`Authorization: Bearer xxx` 会被按「Bearer」这个短值打码，
# 而把真正的令牌原样留在后面 —— 这是最容易漏掉的一种形态。
_AUTH_SCHEMES = frozenset({"bearer", "basic", "token", "digest", "oauth", "apikey", "api-key"})

# 递归进「值内部还是结构」的最大深度。
# 场景：Excel 的 request_body 是 JSON 字符串，repr 后变成
#   `'request_body': '{"password": "xxx"}'`
# 敏感字段藏在第二层甚至第三层（如 `'payload': '{"user": {"password": "x"}}'`）。
# 限制深度是为了防止异常输入（超长嵌套）拖慢日志输出。
_MAX_DEPTH = 4

_OPEN_TO_CLOSE = {"{": "}", "[": "]"}


def _balanced_spans(text):
    """
    找出文本中**最外层**的成对括号区间（只认 `{}` 与 `[]`），返回 [(start, end)]。

    为什么需要它（这是明文泄漏的真正根因）：
        Excel 数据源里的 `request_body` 是一段 JSON **字符串**，被 repr 后形如
            'request_body': '{"username": "demo_user", "password": "demo_password"}'
        顶层 `_KV_RE` 会把 `'{"username": ...}'` 整体当作 `request_body` 的一个值，
        而 `request_body` 本身不是敏感词 —— 于是内层的 `password` 再没有机会被检查，
        明文就这样漏进了 Allure 报告。YAML 的 `request_body` 是 dict（键值对平铺），
        不触发这个形态，所以问题长期没有被发现。
        解决办法：值内部如果还是一段结构，就必须继续往里看。
    """
    spans = []
    stack = []
    for index, char in enumerate(text):
        if char in _OPEN_TO_CLOSE:
            stack.append((char, index))
        elif char in ("}", "]") and stack:
            opener, start = stack[-1]
            if _OPEN_TO_CLOSE[opener] == char:
                stack.pop()
                if not stack:                    # 栈空 = 这一段是最外层
                    spans.append((start, index + 1))
    return spans


def _mask_quoted(raw):
    """对可能带引号的值打码，并保留原引号形状（便于阅读）。"""
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in ("'", '"'):
        return "{}{}{}".format(raw[0], mask_value(raw[1:-1]), raw[-1])
    return mask_value(raw)


def _mask_children(text, depth):
    """
    对文本里每个最外层 `{}` / `[]` 片段的内容递归脱敏，再把结果拼回原位。

    只替换**确实发生变化**的片段，因此对「已打过码」的文本重复调用是幂等的，
    `sanitize_dir()` 多跑几遍也不会把结果越改越乱。
    """
    if depth >= _MAX_DEPTH:
        return text
    spans = _balanced_spans(text)
    if not spans:
        return text

    pieces = []
    position = 0
    for start, end in spans:
        inner = text[start + 1:end - 1]
        masked_inner = mask_text(inner, depth + 1)
        if masked_inner == inner:
            continue
        pieces.append(text[position:start + 1])
        pieces.append(masked_inner)
        position = end - 1
    if not pieces:
        return text
    pieces.append(text[position:])
    return "".join(pieces)


def mask_text(text, _depth=0):
    """
    对一段已拼装好的文本脱敏。

    用途：日志里的消息很多时候是 `logger.info("headers = {}".format(headers))`
    这样提前拼好的字符串（甚至是 dict 的 repr），无法再从结构上判定，
    因此必须按 `字段名 = 值` 的形态做文本级替换。

    处理顺序（缺一不可）：
        1. 顶层「字段名: 值」替换 —— 覆盖 `password=xxx`、`{"token": "xxx"}`
        2. 递归进入每个 `{}` / `[]` 片段 —— 覆盖「值是字符串、结构藏在值里」
           （Excel 数据源的典型形态，见 `_balanced_spans` 的说明）
        3. 裸令牌兜底 —— 覆盖 `Bearer xxx` 这种没有字段名的形态

    :param text:   原文本
    :param _depth: 内部递归深度（外部调用不要传）
    :return: 脱敏后的文本；脱敏关闭时原样返回
    """
    if not enabled():
        return text
    if text is None:
        return text
    if not isinstance(text, str):
        text = str(text)
    if not text:
        return text

    pieces = []
    position = 0
    for match in _KV_RE.finditer(text):
        if not is_sensitive_key(match.group("name")):
            continue
        raw_value = match.group("value")
        # 形如 `Authorization: Bearer <token>`：方案名不是秘密，先跳过，
        # 让紧随其后的令牌被下面的令牌扫描处理（否则只会把 "Bearer" 打码）
        if raw_value.strip("\"'").lower() in _AUTH_SCHEMES:
            continue
        # 已经是打过码的值：跳过，避免二次打码把结果改得越来越长
        if MASK_MIDDLE in raw_value:
            continue
        pieces.append(text[position:match.start("value")])
        pieces.append(_mask_quoted(raw_value))
        position = match.end("value")
    pieces.append(text[position:])
    masked = "".join(pieces)

    # 第二轮：值内部仍是结构的，继续往里钻（Excel 的 request_body 走这条路）
    masked = _mask_children(masked, _depth)

    # 兜底：裸令牌串（如 Authorization 值被单独打印、URL 里带 token 参数）
    return _TOKEN_RE.sub(
        lambda m: "{}{}{}".format(m.group(1), m.group(2), mask_value(m.group(3))),
        masked)


def mask_payload(data):
    """
    统一入口：按类型选择结构化脱敏或文本脱敏。

    :param data: dict / list / str / 其它
    :return: 脱敏后的同类型对象（dict / list 结构保持不变）
    """
    if not enabled():
        return data
    if isinstance(data, (dict, list, tuple)):
        return mask_mapping(data)
    if isinstance(data, str):
        return mask_text(data)
    return data


def enabled():
    """脱敏是否开启（读配置中心，运行期可被环境变量覆盖）。"""
    return bool(getattr(settings.MaskConfig, "ENABLED", True))


def dumps(data, **kwargs):
    """
    把对象转成便于阅读的 JSON 文本并脱敏 —— 报告附件里最常用的一个组合。

    解析失败时回退为 str()，保证「打印不出来」这种小事不会拖垮一条用例。
    """
    try:
        text = json.dumps(mask_mapping(data), ensure_ascii=False, **kwargs)
    except (TypeError, ValueError):
        text = str(mask_mapping(data))
    return text


# ----------------------------------------------------------------------
# 四、落盘后兜底脱敏（安全网）
# ----------------------------------------------------------------------
# 为什么除了「写入时脱敏」还需要「落盘后再扫一遍」：
#   Allure 官方 pytest 插件会把 `@pytest.mark.parametrize` 的**每一个参数**
#   自动写成报告参数。框架用 `@pytest.mark.parametrize("case", CASES)` 传整条用例数据，
#   于是 result.json 里会出现：
#       "parameters": [{"name": "case",
#                       "value": "{'username': 'demo_user', 'password': 'demo_password'}"}]
#   这条路径由第三方插件直接落盘，不经过框架的 attach_*，只能在结果生成后统一兜一次。
#   需要处理的产物后缀（报告原始数据 / 附件 / 渲染结果 / 日志）。
_TEXT_SUFFIXES = (".json", ".txt", ".xml", ".html", ".htm", ".csv", ".properties")


def _mask_every_string(obj):
    """递归地把结构里**所有**字符串按文本规则脱敏（敏感键则强打码）。"""
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, dict):
        return {
            key: (mask_value(value) if is_sensitive_key(key)
                  else _mask_every_string(value))
            for key, value in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [_mask_every_string(item) for item in obj]
    return obj


def sanitize_file(path):
    """
    对单个产物文件做落盘后脱敏：JSON 按结构处理，其余按文本处理。

    :param path: 文件绝对路径
    :return: True = 内容确实被改写；False = 无需改写或读取失败
    """
    try:
        with open(path, "r", encoding="utf-8") as fp:
            original = fp.read()
    except (OSError, UnicodeDecodeError):
        return False
    if not original:
        return False

    masked = None
    if os.path.splitext(path)[1].lower() == ".json":
        try:
            masked = json.dumps(_mask_every_string(json.loads(original)),
                                ensure_ascii=False)
        except ValueError:                       # 非合法 JSON，退回文本处理
            masked = None
    if masked is None:
        masked = mask_text(original)

    if masked == original:
        return False
    try:
        with open(path, "w", encoding="utf-8", newline="") as fp:
            fp.write(masked)
    except OSError:
        return False
    return True


def sanitize_dir(root, suffixes=_TEXT_SUFFIXES):
    """
    对目录（含子目录）下的产物文件统一脱敏 —— 报告与日志的**最后一道防线**。

    这是「兜底」而非「唯一」手段：正常情况下日志经 `SensitiveFilter`、
    附件经 `allureutil.attach_*` 就已经打过码；本函数负责把第三方插件直接落盘的
    内容（如 allure-pytest 写出的 parametrize 参数）与未来新增的输出路径一并覆盖。
    因此可以安全地对整个 `report/` 目录调用，重复执行无副作用。

    :param root:     目录绝对路径（不存在则直接返回 0）
    :param suffixes: 需要处理的文件后缀
    :return: 被改写的文件数
    """
    if not enabled():
        return 0
    if not root or not os.path.isdir(root):
        return 0

    suffixes = tuple(suffixes)
    changed = 0
    for base, _dirs, files in os.walk(root):
        for name in files:
            if not name.lower().endswith(suffixes):
                continue
            try:
                if sanitize_file(os.path.join(base, name)):
                    changed += 1
            except Exception:                    # 单文件异常不得影响整轮会话
                continue
    return changed
