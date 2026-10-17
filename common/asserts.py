# -*- coding: utf-8 -*-
"""
断言增强层（Asserts）
=====================
原框架只有三种断言：HTTP 状态码相等、业务码相等、字段相等。
真实项目里远不够用 —— 中台要校验列表非空、商城要校验金额范围、
政务要校验返回报文里包含指定文案、所有系统都该关注响应耗时。

本模块提供一组**按路径断言**的函数，统一约定：

    路径以「完整响应」为根，与 relation 列写法一致：
        body.msg              响应体里的 msg 字段
        body.data.total       嵌套字段
        body.data.rows.0.id   列表下标
        ""（空）              整个响应体
        code                  HTTP 状态码（response 的顶层键）

失败时抛出 AssertionError，且消息里带上「期望 / 实际 / 响应摘要」，
在 Allure 报告里一眼就能定位。

本模块也是用例 `expects` 字段的执行引擎：op 名字即函数名，
如 `contains:body.msg=操作成功` 会调用这里的 contains()。
"""
import json
import re

from common import base

# 断言算子表：名称 -> (函数, 是否需要期望值)
OPS = {}

# 算子用途说明（用于 `expects` 写错时给出可用清单）
OP_DOC = {
    "equals": "相等（宽松比较：200 与 '200'、true 与 'True' 都算相等）",
    "not_equals": "不相等",
    "contains": "包含子串（字符串）或包含元素（列表）",
    "not_contains": "不包含",
    "startswith": "以指定前缀开头",
    "endswith": "以指定后缀结尾",
    "regex": "匹配正则表达式",
    "type": "类型断言：str/int/float/bool/list/dict/none/number",
    "exists": "字段存在且非 None",
    "not_exists": "字段不存在或为 None",
    "in": "取值在给定集合内（集合用逗号分隔）",
    "not_in": "取值不在给定集合内",
    "gt": "大于（数值比较）",
    "ge": "大于等于",
    "lt": "小于",
    "le": "小于等于",
    "length": "长度等于（字符串 / 列表 / 字典）",
    "empty": "为空（None / '' / [] / {}）",
    "not_empty": "非空",
    "elapsed": "响应耗时不超过指定毫秒数",
    "schema": "响应体符合 JSON Schema（需可选依赖 jsonschema）",
}


def op(name, needs_value=True, aliases=()):
    """把一个函数注册为断言算子（含别名）。"""
    def wrapper(func):
        OPS[name] = (func, needs_value)
        for alias in aliases:
            OPS[alias] = (func, needs_value)
        return func
    return wrapper


# ======================================================================
# 一、取值与消息
# ======================================================================
def value_of(response, path, default=None):
    """
    按路径取响应中的值。

    :param response: 统一响应字典
    :param path:     点号路径；空表示整个响应体
    """
    if response is None:
        return default
    if path in (None, ""):
        return response.get("body")
    value = base.parse_relation(str(path).split("."), response)
    return default if value is None else value


def summary(response, limit=200):
    """响应摘要，用于失败提示（过长时截断，避免报告被刷屏）。"""
    if not response:
        return "(无响应)"
    text = "HTTP {} | body={}".format(response.get("code"), response.get("body"))
    return text if len(text) <= limit else text[:limit] + "...(已截断)"


def _fail(message, response=None, path=None):
    """统一构造失败信息：期望 vs 实际 + 路径 + 响应摘要。"""
    parts = [message]
    if path is not None:
        parts.append("字段路径：{}".format(path or "(整个响应体)"))
    if response is not None:
        parts.append("响应摘要：{}".format(summary(response)))
    raise AssertionError("\n".join(parts))


def _to_number(value, response, path, op_name):
    """把值转成数字，转不了就给出明确失败信息（而不是抛 TypeError）。"""
    try:
        return float(value)
    except (ValueError, TypeError):
        _fail("{} 断言需要数值，但字段实际值为 {!r}（类型 {}）".format(
            op_name, value, type(value).__name__), response, path)


# ======================================================================
# 二、相等类
# ======================================================================
@op("equals", aliases=("eq",))
def equals(response, path, expected, msg=""):
    """相等断言（宽松比较，与业务码判定同一套规则）。"""
    actual = value_of(response, path)
    if not base_equals(actual, expected):
        _fail("{}相等断言失败：期望 {!r}，实际 {!r}".format(msg, expected, actual),
              response, path)
    return True


@op("not_equals", aliases=("ne",))
def not_equals(response, path, expected, msg=""):
    """不相等断言。"""
    actual = value_of(response, path)
    if base_equals(actual, expected):
        _fail("{}不相等断言失败：期望不等于 {!r}，但实际就是 {!r}".format(msg, expected, actual),
              response, path)
    return True


def base_equals(actual, expected):
    """
    宽松相等：先字符串（忽略大小写与空白）比，再数值比。

    这样 200 与 "200"、"true" 与 True、0 与 "0" 都算相等，
    贴合「Excel 里写 200、接口返回字符串」的常见情况。
    """
    if actual is None or expected is None:
        return actual is None and expected is None
    left, right = str(actual).strip(), str(expected).strip()
    if left.lower() == right.lower():
        return True
    try:
        return float(left) == float(right)
    except (ValueError, TypeError):
        return False


# ======================================================================
# 三、包含类
# ======================================================================
@op("contains", aliases=("has",))
def contains(response, path, expected, msg=""):
    """包含断言：字符串按子串、列表按元素、字典按键。"""
    actual = value_of(response, path)
    if actual is None:
        _fail("{}包含断言失败：字段不存在或为 None".format(msg), response, path)

    if isinstance(actual, (list, tuple, set)):
        ok = any(base_equals(item, expected) for item in actual)
    elif isinstance(actual, dict):
        ok = str(expected) in actual
    else:
        ok = str(expected) in str(actual)

    if not ok:
        _fail("{}包含断言失败：期望包含 {!r}，实际 {!r}".format(msg, expected, actual),
              response, path)
    return True


@op("not_contains", aliases=("not_has",))
def not_contains(response, path, expected, msg=""):
    """不包含断言。"""
    actual = value_of(response, path)
    if isinstance(actual, (list, tuple, set)):
        ok = not any(base_equals(item, expected) for item in actual)
    elif isinstance(actual, dict):
        ok = str(expected) not in actual
    else:
        ok = str(expected) not in str(actual or "")
    if not ok:
        _fail("{}不包含断言失败：实际 {!r} 中出现了 {!r}".format(msg, actual, expected),
              response, path)
    return True


@op("startswith")
def startswith(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not str(actual or "").startswith(str(expected)):
        _fail("{}前缀断言失败：期望以 {!r} 开头，实际 {!r}".format(msg, expected, actual),
              response, path)
    return True


@op("endswith")
def endswith(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not str(actual or "").endswith(str(expected)):
        _fail("{}后缀断言失败：期望以 {!r} 结尾，实际 {!r}".format(msg, expected, actual),
              response, path)
    return True


@op("regex", aliases=("match",))
def regex(response, path, pattern, msg=""):
    """正则匹配断言（使用 search，即"包含匹配"）。"""
    actual = value_of(response, path)
    if re.search(str(pattern), str(actual or "")) is None:
        _fail("{}正则断言失败：期望匹配 {!r}，实际 {!r}".format(msg, pattern, actual),
              response, path)
    return True


# ======================================================================
# 四、存在与类型
# ======================================================================
@op("exists", needs_value=False, aliases=("present",))
def exists(response, path, msg=""):
    """字段存在且不为 None。"""
    if value_of(response, path) is None:
        _fail("{}存在性断言失败：字段不存在或为 None".format(msg), response, path)
    return True


@op("not_exists", needs_value=False, aliases=("absent",))
def not_exists(response, path, msg=""):
    """字段不存在或为 None。"""
    if value_of(response, path) is not None:
        _fail("{}存在性断言失败：期望字段不存在，实际有值 {!r}".format(
            msg, value_of(response, path)), response, path)
    return True


# 类型名 -> 判定函数；number 表示 int/float 都算
TYPE_CHECKS = {
    "str": lambda v: isinstance(v, str),
    "string": lambda v: isinstance(v, str),
    "int": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "float": lambda v: isinstance(v, float),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "bool": lambda v: isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "list": lambda v: isinstance(v, list),
    "array": lambda v: isinstance(v, list),
    "dict": lambda v: isinstance(v, dict),
    "object": lambda v: isinstance(v, dict),
    "none": lambda v: v is None,
    "null": lambda v: v is None,
}


@op("type", aliases=("type_is",))
def type_is(response, path, expected, msg=""):
    """
    类型断言。

    兼容一种常见情况：接口把数字以字符串返回（"18"）时，
    若期望 number 但实际是纯数字字符串，也判为通过并给出提示，
    避免因为服务端序列化差异把用例误判为失败。
    """
    actual = value_of(response, path)
    checker = TYPE_CHECKS.get(str(expected).strip().lower())
    if checker is None:
        _fail("不支持的类型名 {!r}，可选：{}".format(expected, ", ".join(sorted(TYPE_CHECKS))),
              response, path)

    if checker(actual):
        return True

    # 数字字符串兜底：期望 number/int/float 而实际是纯数字字符串
    if str(expected).strip().lower() in ("number", "int", "float") \
            and isinstance(actual, str) and re.fullmatch(r"-?\d+(\.\d+)?", actual.strip()):
        return True

    _fail("{}类型断言失败：期望 {}，实际 {!r}（{}）".format(
        msg, expected, actual, type(actual).__name__), response, path)


# ======================================================================
# 五、集合与数值
# ======================================================================
@op("in")
def in_(response, path, expected, msg=""):
    """取值在给定集合内；集合支持列表或 'a,b,c' 字符串。"""
    actual = value_of(response, path)
    allowed = expected if isinstance(expected, (list, tuple, set)) \
        else [item.strip() for item in str(expected).split(",") if item.strip()]
    if not any(base_equals(actual, item) for item in allowed):
        _fail("{}集合断言失败：期望取值属于 {}，实际 {!r}".format(
            msg, list(allowed), actual), response, path)
    return True


@op("not_in")
def not_in(response, path, expected, msg=""):
    """取值不在给定集合内。"""
    actual = value_of(response, path)
    allowed = expected if isinstance(expected, (list, tuple, set)) \
        else [item.strip() for item in str(expected).split(",") if item.strip()]
    if any(base_equals(actual, item) for item in allowed):
        _fail("{}集合断言失败：期望取值不属于 {}，实际 {!r}".format(
            msg, list(allowed), actual), response, path)
    return True


@op("gt")
def gt(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not _to_number(actual, response, path, "大于") > _to_number(expected, response, path, "大于"):
        _fail("{}大于断言失败：期望 > {}，实际 {}".format(msg, expected, actual), response, path)
    return True


@op("ge")
def ge(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not _to_number(actual, response, path, "大于等于") >= _to_number(expected, response, path, "大于等于"):
        _fail("{}大于等于断言失败：期望 >= {}，实际 {}".format(msg, expected, actual), response, path)
    return True


@op("lt")
def lt(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not _to_number(actual, response, path, "小于") < _to_number(expected, response, path, "小于"):
        _fail("{}小于断言失败：期望 < {}，实际 {}".format(msg, expected, actual), response, path)
    return True


@op("le")
def le(response, path, expected, msg=""):
    actual = value_of(response, path)
    if not _to_number(actual, response, path, "小于等于") <= _to_number(expected, response, path, "小于等于"):
        _fail("{}小于等于断言失败：期望 <= {}，实际 {}".format(msg, expected, actual), response, path)
    return True


@op("length", aliases=("len",))
def length(response, path, expected, msg=""):
    """长度断言（字符串 / 列表 / 字典）。"""
    actual = value_of(response, path)
    try:
        actual_len = len(actual)
    except TypeError:
        _fail("{}长度断言需要可求长度的值，实际 {!r}（{}）".format(
            msg, actual, type(actual).__name__), response, path)
    if not base_equals(actual_len, expected):
        _fail("{}长度断言失败：期望 {}，实际 {}（值={!r}）".format(
            msg, expected, actual_len, actual), response, path)
    return True


@op("empty", needs_value=False)
def empty(response, path, msg=""):
    """为空断言：None / '' / [] / {} 都算空。"""
    actual = value_of(response, path)
    if actual not in (None, "", [], {}):
        _fail("{}空值断言失败：期望为空，实际 {!r}".format(msg, actual), response, path)
    return True


@op("not_empty", needs_value=False, aliases=("notempty",))
def not_empty(response, path, msg=""):
    """非空断言。"""
    actual = value_of(response, path)
    if actual in (None, "", [], {}):
        _fail("{}非空断言失败：字段为空".format(msg), response, path)
    return True


# ======================================================================
# 六、性能与结构
# ======================================================================
@op("elapsed")
def elapsed(response, path=None, expected=None, msg=""):
    """
    响应耗时断言（毫秒）。

    路径参数在此算子中无意义，为与其它算子统一签名而保留。
    """
    limit = expected if expected is not None else path
    actual = (response or {}).get("elapsed")
    if actual is None:
        _fail("{}耗时断言失败：响应中没有 elapsed 字段".format(msg), response)
    if float(actual) > float(limit):
        _fail("{}耗时断言失败：期望不超过 {} ms，实际 {} ms".format(msg, limit, actual), response)
    return True


@op("schema")
def schema(response, path, expected, msg=""):
    """
    JSON Schema 校验（需可选依赖 jsonschema）。

    未安装 jsonschema 时给出明确的安装提示，而不是静默跳过 ——
    否则"配置了校验却什么都没校验"是最危险的。
    """
    try:
        import jsonschema
    except ImportError:
        _fail("JSON Schema 校验需要可选依赖 jsonschema，安装后即可使用：\n"
              "    pip install jsonschema")

    data = value_of(response, path)
    rules = expected
    if isinstance(rules, str):
        try:
            rules = json.loads(rules)
        except json.JSONDecodeError as exc:
            _fail("Schema 定义不是合法 JSON：{}".format(exc))

    try:
        jsonschema.validate(data, rules)
    except jsonschema.ValidationError as exc:
        _fail("{}JSON Schema 校验失败：{}（出错位置：{}）".format(
            msg, exc.message, "/".join(str(item) for item in exc.path)), response, path)
    return True


# ======================================================================
# 七、数据库断言（可选，需 pymysql）
# ======================================================================
def db_equals(sql, expected, args=None, column=None, msg=""):
    """
    查库并断言结果 —— 财务 / ERP 常见「接口写入后与库中数据核对」。

    :param sql:    查询 SQL（建议用 %s 参数化，避免注入）
    :param expected: 期望值
    :param args:   SQL 参数
    :param column: 取哪一列的值；为空时：单列取该列，多列则取整行
    :return: True
    """
    from utils.mysqlutil import MysqlUtil

    with MysqlUtil() as mysql:
        if column:
            row = mysql.get_fetchone(sql, args)
            actual = row.get(column) if isinstance(row, dict) else row
        else:
            row = mysql.get_fetchone(sql, args)
            if isinstance(row, dict) and len(row) == 1:
                actual = next(iter(row.values()))
            else:
                actual = row

    if not base_equals(actual, expected):
        raise AssertionError(
            "{}数据库断言失败：期望 {!r}，实际 {!r}\n  SQL：{}".format(msg, expected, actual, sql))
    return True


def db_count(sql, expected, args=None, msg=""):
    """查库并断言行数（常用于「新建的单据只应有一条」这类校验）。"""
    from utils.mysqlutil import MysqlUtil

    with MysqlUtil() as mysql:
        rows = mysql.get_fetchall(sql, args)
    actual = len(rows or [])
    if not base_equals(actual, expected):
        raise AssertionError("{}数据库行数断言失败：期望 {}，实际 {}\n  SQL：{}".format(
            msg, expected, actual, sql))
    return True


# ======================================================================
# 八、算子调度（供用例 expects 字段使用）
# ======================================================================
def run_op(name, response, path, value=None, msg=""):
    """
    执行一个断言算子。

    :param name:  算子名（见 OPS / OP_DOC）
    :param response: 统一响应字典
    :param path:  字段路径
    :param value: 期望值（exists / empty 这类算子不需要）
    :raises AssertionError: 算子不存在，或断言失败
    """
    key = str(name).strip().lower()
    entry = OPS.get(key)
    if entry is None:
        raise AssertionError("未知断言算子 '{}'。可用算子：\n  {}".format(
            name, "\n  ".join("{} —— {}".format(k, v) for k, v in sorted(OP_DOC.items()))))

    func, needs_value = entry
    if needs_value:
        return func(response, path, value, msg)
    return func(response, path, msg)


def op_names():
    """全部可用的断言算子名（去重，供文档与校验使用）。"""
    return sorted(OP_DOC)
