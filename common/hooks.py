# -*- coding: utf-8 -*-
"""
请求 / 响应钩子层（Hooks）与签名加密工具
=========================================
财务、政务、商城类系统普遍会在请求上加一层「业务协议」：签名、时间戳防重放、
报文加解密。这些逻辑放在框架主体里会污染核心链路，放在每个用例里又会大量重复。
本模块提供**可插拔钩子**，由系统适配档案的 [hooks] 段声明挂载点。

两个挂载阶段：

    before_request   请求发出前 —— 常用于 注入时间戳/随机数、计算并写入签名、加密报文字段
    after_response   响应收到后 —— 常用于 解密响应字段、校验响应签名

钩子就是一个普通函数，入参出参都是同一个上下文字典：

    def my_hook(ctx):
        ctx["headers"]["X-Trace"] = "1"
        return ctx

上下文字段：
    before_request : method / url / headers / cookies / payload / location / case / profile
    after_response : response / case / profile

内置常用钩子（用工厂函数生成后注册到档案里即可）：

    make_timestamp_nonce_hook()   注入时间戳与随机串，防重放
    make_sign_hook()              对请求参数排序拼串后摘要，写入报文字段或请求头
    make_aes_hook()               用 AES 加密指定字段（需可选依赖 cryptography）
    make_decrypt_response_hook()  用 AES 解密响应中的指定字段

密码学能力全部走**可选依赖**：没装 cryptography 时，相关函数会给出明确提示，
其余功能不受影响，CI 也不会因此失败。
"""
import base64
import hashlib
import hmac
import importlib
import json
import random
import string
import time

from utils.logutil import logger

# 挂载阶段常量
STAGE_BEFORE = "before_request"
STAGE_AFTER = "after_response"


# ======================================================================
# 一、钩子注册表
# ======================================================================
def split_top_level(text, sep=","):
    """
    按**顶层**分隔符切分字符串，忽略括号内部的分隔符。

    必要性：钩子声明允许带 JSON 参数，其内部本身就有逗号，
    例如 `common.hooks:make_sign_hook({"salt": "a", "upper": true})`，
    朴素地按逗号切会把一条声明劈成两半。
    """
    parts, current, depth = [], [], 0
    for char in str(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth = max(0, depth - 1)
        if char == sep and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return [item.strip() for item in parts if item.strip()]


def _resolve_callable(text):
    """
    把 "包.模块:函数名"（或 "包.模块.函数名"）解析成对象。

    只负责「找到它」，不做工厂是否已调用的校验 —— 因为调用工厂时也走这里。
    """
    if ":" in text:
        module_path, _, func_name = text.partition(":")
    else:
        module_path, _, func_name = text.rpartition(".")

    if not module_path or not func_name:
        raise ValueError("钩子声明格式错误，应为 '包.模块:函数名'：{}".format(text))

    module = importlib.import_module(module_path)
    return getattr(module, func_name)


def load_hook(spec):
    """
    把钩子声明解析成可调用对象。支持三种写法：

        common.hooks:my_hook                          直接引用已有函数
        common.hooks:make_sign_hook()                 调用工厂（不带参数，括号必须有）
        common.hooks:make_sign_hook({"salt": "abc"})  调用工厂并传 JSON 参数

    :param spec: 声明字符串，或可调用对象本身
    :return: 可调用对象；spec 为空时返回 None
    """
    if spec is None or spec == "":
        return None
    if callable(spec):
        return spec

    text = str(spec).strip()
    if not text:
        return None

    # 带参数的工厂写法：功能名 + JSON 参数对象
    if text.endswith(")") and "(" in text:
        head, _, tail = text.partition("(")
        factory = _resolve_callable(head.strip())
        if factory is None:
            raise ValueError("钩子工厂解析为空：{}".format(spec))

        args_text = tail[:tail.rfind(")")].strip() if ")" in tail else tail.strip()
        if args_text:
            try:
                kwargs = json.loads(args_text)
            except json.JSONDecodeError as exc:
                raise ValueError("钩子参数不是合法 JSON：{}（{}）".format(args_text, exc))
            if not isinstance(kwargs, dict):
                raise ValueError("钩子参数必须是 JSON 对象：{}".format(args_text))
        else:
            kwargs = {}
        return factory(**kwargs)

    func = _resolve_callable(text)

    # 工厂函数必须「调用后」才是一个钩子。直接引用会拿到工厂本身，
    # 运行期表现为「钩子返回了一个函数而不是上下文」这种极难定位的错误，
    # 所以这里提前拦住并给出可照抄的写法。
    if callable(func) and str(getattr(func, "__name__", "")).startswith("make_"):
        raise ValueError(
            "钩子工厂需要调用后才生效（漏写括号了），请照下面任一形式书写：\n"
            "    {0}()                  不带参数\n"
            "    {0}({{\"salt\": \"xxx\"}})   带 JSON 参数".format(text))

    return func


class HookRegistry:
    """
    钩子注册表。按顺序执行，前一个钩子的产出会传给下一个，
    因此多个钩子可以「先加密再签名」这样串起来。
    """

    def __init__(self, before=None, after=None):
        self._before = []
        self._after = []
        for item in self._to_list(before):
            hook = load_hook(item)
            if hook:
                self._before.append(hook)
        for item in self._to_list(after):
            hook = load_hook(item)
            if hook:
                self._after.append(hook)

    @staticmethod
    def _to_list(value):
        """
        钩子声明支持：单个、逗号分隔字符串、列表三种写法。

        切分走 split_top_level，保证带 JSON 参数的声明不会被参数里的逗号劈开。
        """
        if value is None or value == "":
            return []
        if isinstance(value, (list, tuple)):
            return [item for item in value if item]
        return split_top_level(str(value))

    def add_before(self, hook):
        """追加一个前置钩子（可传函数或 '包.模块:函数名'）。"""
        resolved = load_hook(hook)
        if resolved:
            self._before.append(resolved)
        return self

    def add_after(self, hook):
        """追加一个后置钩子。"""
        resolved = load_hook(hook)
        if resolved:
            self._after.append(resolved)
        return self

    def run_before(self, ctx):
        """依次执行前置钩子；单个钩子抛异常时记录日志后向上抛，避免静默走错报文。"""
        for hook in self._before:
            ctx = hook(ctx) or ctx
        return ctx

    def run_after(self, ctx):
        """依次执行后置钩子。"""
        for hook in self._after:
            ctx = hook(ctx) or ctx
        return ctx

    @property
    def before_hooks(self):
        return list(self._before)

    @property
    def after_hooks(self):
        return list(self._after)

    def describe(self):
        """给日志 / 报告展示的摘要。"""
        def name_of(func):
            return getattr(func, "__name__", str(func))

        return {
            "请求前钩子": ", ".join(name_of(h) for h in self._before) or "(无)",
            "响应后钩子": ", ".join(name_of(h) for h in self._after) or "(无)",
        }


# ======================================================================
# 二、摘要与签名工具（纯标准库，无需额外依赖）
# ======================================================================
def digest(text, alg="md5", key=None):
    """
    计算摘要。

    :param text: 待摘要的文本（非字符串会先转字符串）
    :param alg:  md5 | sha1 | sha256 | sha512 | hmac-md5 | hmac-sha256
    :param key:  HMAC 密钥（hmac-* 系列必填）
    :return: 十六进制摘要字符串（小写）
    """
    raw = text if isinstance(text, bytes) else str(text).encode("utf-8")
    name = str(alg or "md5").strip().lower()

    if name.startswith("hmac-"):
        real = name.split("-", 1)[1]
        secret = (key if isinstance(key, bytes) else str(key or "").encode("utf-8"))
        return hmac.new(secret, raw, getattr(hashlib, real)).hexdigest()
    return hashlib.new(name, raw).hexdigest()


def sign_sorted(params, salt="", alg="md5", upper=False, exclude=(),
                join="&", kv_sep="=", skip_empty=True):
    """
    最常见的签名算法：把参数按 key 升序拼成 k1=v1&k2=v2，拼接盐值后摘要。

    政务、财务、商城系统九成以上的签名都是这个套路，差别只在
    排序规则、是否跳空值、拼接符、是否大写这几个细节上，故全部做成参数。

    :param params:     请求参数字典
    :param salt:       盐值 / 密钥（追加在拼接串末尾）
    :param alg:        摘要算法，见 digest()
    :param upper:      摘要是否转大写
    :param exclude:    参与签名时要排除的字段（如 sign 自身）
    :param join/kv_sep: 拼接符
    :param skip_empty: 是否跳过值为空的字段
    :return: 签名字符串
    """
    exclude_set = {str(item).strip() for item in (exclude or ())}
    items = []
    for key in sorted(params or {}):
        if key in exclude_set:
            continue
        value = params[key]
        if skip_empty and (value is None or value == ""):
            continue
        if isinstance(value, (dict, list)):
            # 嵌套结构统一按紧凑 JSON 参与签名，避免不同语言序列化差异
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        items.append("{}{}{}".format(key, kv_sep, value))

    text = join.join(items) + str(salt or "")
    result = digest(text, alg=alg)
    return result.upper() if upper else result


# ======================================================================
# 三、内置钩子工厂
# ======================================================================
def make_timestamp_nonce_hook(fields=("timestamp", "nonce"), ts_unit="s",
                              nonce_len=16, ts_digits=None):
    """
    生成「时间戳 + 随机串」注入钩子，用于防重放校验。

    :param fields:    (时间戳字段名, 随机串字段名)
    :param ts_unit:   时间戳单位：s（秒）/ ms（毫秒）
    :param nonce_len: 随机串长度
    :param ts_digits: 时间戳位数；给出时会截取末 N 位（部分系统要求 10 位或 13 位）
    """
    ts_field, nonce_field = (fields or ("timestamp", "nonce"))[:2]

    def _now():
        value = int(time.time() * (1000 if str(ts_unit).lower() == "ms" else 1))
        if ts_digits:
            value = int(str(value)[-int(ts_digits):])
        return value

    def hook(ctx):
        payload = ctx.get("payload")
        # 只有字典类型的报文才注入；原始报文（XML/文本）由使用方自行处理
        if isinstance(payload, dict):
            payload[ts_field] = _now()
            payload[nonce_field] = "".join(
                random.choice(string.ascii_lowercase + string.digits) for _ in range(nonce_len))
        return ctx

    hook.__name__ = "inject_timestamp_nonce"
    return hook


def make_sign_hook(field="sign", salt="", alg="md5", upper=False, exclude=("sign",),
                   target="payload", header="Sign"):
    """
    生成「请求签名」钩子：对报文参数排序拼串后摘要，写入报文字段或请求头。

    :param field:  签名写入报文的字段名（target=payload 时生效）
    :param salt:   盐值 / 密钥
    :param alg:    摘要算法
    :param upper:  摘要是否大写
    :param exclude: 不参与签名的字段（默认排除 sign 自身）
    :param target: payload（写进请求报文）| header（写进请求头）
    :param header: target=header 时的请求头名
    """
    def hook(ctx):
        payload = ctx.get("payload")
        if not isinstance(payload, dict):
            return ctx
        value = sign_sorted(payload, salt=salt, alg=alg, upper=upper, exclude=exclude)
        if str(target).lower() == "header":
            ctx.setdefault("headers", {})[header] = value
        else:
            payload[field] = value
        return ctx

    hook.__name__ = "sign_request"
    return hook


def mask_sensitive(params, fields=("password", "passwd", "pwd", "token", "secret",
                                   "sign", "access_token", "refresh_token"),
                   placeholder="******"):
    """
    把敏感字段替换成占位符（返回新字典，不改原数据）。

    用于把请求报文写进日志或报告前的脱敏，避免测试账号口令、令牌被明文留档。
    """
    if not isinstance(params, dict):
        return params
    lower_fields = {str(item).lower() for item in fields}
    result = {}
    for key, value in params.items():
        if str(key).lower() in lower_fields:
            result[key] = placeholder
        elif isinstance(value, dict):
            result[key] = mask_sensitive(value, fields, placeholder)
        else:
            result[key] = value
    return result


# ======================================================================
# 四、加解密钩子（可选依赖 cryptography，未安装时给出明确提示）
# ======================================================================
CRYPTO_HINT = ("本功能需要可选依赖 cryptography，安装后即可使用：\n"
               "    pip install cryptography\n"
               "未安装不影响框架其它能力（签名、时间戳、响应判定均可正常使用）。")


def _load_crypto():
    """惰性导入 cryptography；未安装时返回 None。"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        return Cipher, algorithms, modes
    except ImportError:
        return None


def crypto_available():
    """cryptography 是否可用（供文档与自检展示）。"""
    return _load_crypto() is not None


def _pkcs7_pad(raw, block=16):
    """PKCS7 填充（AES 分组长度固定 16 字节）。"""
    pad = block - len(raw) % block
    return raw + bytes([pad]) * pad


def _pkcs7_unpad(raw):
    """去掉 PKCS7 填充。"""
    return raw[:-raw[-1]] if raw else raw


def aes_encrypt(plain, key, iv=None, mode="ECB", b64=True):
    """
    AES 加密（默认 ECB + PKCS7，输出 base64）。

    财务 / 商城 / 政务系统里最常见的就是「AES/ECB/PKCS5Padding，密钥 16 位，结果 base64」。

    :param plain: 明文（字符串或 bytes）
    :param key:   密钥（16/24/32 字节，字符串会按 utf-8 编码）
    :param iv:    CBC/GCM 模式下的初始向量
    :param mode:  ECB | CBC
    :param b64:   是否把密文做 base64（部分系统要求直接给 hex 或原始字节）
    """
    crypto = _load_crypto()
    if crypto is None:
        raise RuntimeError("AES 加密不可用：\n" + CRYPTO_HINT)
    Cipher, algorithms, modes = crypto

    key_bytes = key if isinstance(key, bytes) else str(key).encode("utf-8")
    raw = plain if isinstance(plain, bytes) else str(plain).encode("utf-8")
    raw = _pkcs7_pad(raw)

    name = str(mode or "ECB").upper()
    if name == "CBC":
        iv_bytes = iv if isinstance(iv, bytes) else str(iv or "").encode("utf-8")
        cipher_mode = modes.CBC(iv_bytes)
    else:
        cipher_mode = modes.ECB()

    encryptor = Cipher(algorithms.AES(key_bytes), cipher_mode).encryptor()
    result = encryptor.update(raw) + encryptor.finalize()
    return base64.b64encode(result).decode("ascii") if b64 else result


def aes_decrypt(cipher_text, key, iv=None, mode="ECB", b64=True):
    """AES 解密，与 aes_encrypt 对称。"""
    crypto = _load_crypto()
    if crypto is None:
        raise RuntimeError("AES 解密不可用：\n" + CRYPTO_HINT)
    Cipher, algorithms, modes = crypto

    key_bytes = key if isinstance(key, bytes) else str(key).encode("utf-8")
    raw = base64.b64decode(cipher_text) if b64 else cipher_text

    name = str(mode or "ECB").upper()
    if name == "CBC":
        iv_bytes = iv if isinstance(iv, bytes) else str(iv or "").encode("utf-8")
        cipher_mode = modes.CBC(iv_bytes)
    else:
        cipher_mode = modes.ECB()

    decryptor = Cipher(algorithms.AES(key_bytes), cipher_mode).decryptor()
    result = _pkcs7_unpad(decryptor.update(raw) + decryptor.finalize())
    return result.decode("utf-8", errors="replace")


def make_aes_hook(key, fields=("data",), iv=None, mode="ECB", alg_field=None):
    """
    生成「请求报文字段加密」钩子：把 payload 中指定字段的 JSON 串加密后回填。

    :param key:       密钥
    :param fields:    需要加密的字段名
    :param iv:        CBC 模式的初始向量
    :param mode:      ECB | CBC
    :param alg_field: 若给出，会在报文里额外写入加密算法标识（部分系统要求）
    """
    def hook(ctx):
        payload = ctx.get("payload")
        if not isinstance(payload, dict):
            return ctx
        for name in fields:
            if name in payload:
                plain = payload[name]
                if not isinstance(plain, str):
                    plain = json.dumps(plain, ensure_ascii=False, separators=(",", ":"))
                payload[name] = aes_encrypt(plain, key, iv=iv, mode=mode)
        if alg_field:
            payload[alg_field] = "AES/{}".format(str(mode).upper())
        return ctx

    hook.__name__ = "encrypt_request"
    return hook


def make_decrypt_response_hook(key, fields=("data",), iv=None, mode="ECB",
                              drop_fields=()):
    """
    生成「响应字段解密」钩子：把响应体中的密文字段解密回原文。

    :param fields:      需要解密的响应体字段（相对 response["body"]）
    :param drop_fields: 解密后要删除的冗余字段（如 sign、encryptType）
    """
    def hook(ctx):
        response = ctx.get("response") or {}
        body = response.get("body")
        if not isinstance(body, dict):
            return ctx
        for name in fields:
            value = body.get(name)
            if isinstance(value, str) and value:
                try:
                    body[name] = aes_decrypt(value, key, iv=iv, mode=mode)
                except Exception as exc:                       # 解密失败不该让整条用例静默变红
                    logger.warning("响应字段 {} 解密失败：{}".format(name, exc))
        for name in drop_fields:
            body.pop(name, None)
        return ctx

    hook.__name__ = "decrypt_response"
    return hook


def rsa_sign(text, private_key_pem, alg="sha256"):
    """
    RSA 私钥签名（返回 base64），政务 / 财务系统用于报文防篡改。

    :param text:            待签文本
    :param private_key_pem: PEM 格式私钥（字符串或 bytes）
    :param alg:             sha256 | sha1 | sha512
    """
    try:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding
    except ImportError:
        raise RuntimeError("RSA 签名不可用：\n" + CRYPTO_HINT)

    key_bytes = (private_key_pem if isinstance(private_key_pem, bytes)
                 else str(private_key_pem).encode("utf-8"))
    private_key = serialization.load_pem_private_key(key_bytes, password=None)
    signature = private_key.sign(
        str(text).encode("utf-8"),
        padding.PKCS1v15(),
        getattr(hashes, str(alg).upper())(),
    )
    return base64.b64encode(signature).decode("ascii")


def make_token_response_hook(token_path="body.data.token", var_name="token"):
    """
    生成「响应令牌自动入池」钩子：把响应里的令牌写入全局变量池。

    这样后续用例用 `${token}` 即可引用，无需在数据里再配一次 relation
    —— 对「登录接口只在档案里声明一次」的场景很有用。
    """
    from common import base
    from common.variable import GlobalVar

    def hook(ctx):
        response = ctx.get("response") or {}
        value = base.parse_relation(str(token_path).split("."), response)
        if value is not None:
            GlobalVar.set(var_name, value)
            logger.info("【认证】从响应提取 {} = {}".format(var_name, value))
        return ctx

    hook.__name__ = "capture_token"
    return hook
