# -*- coding: utf-8 -*-
"""
基础解析层
==========
负责「参数化」的三件事：
    1. find()            从数据中正则找出所有 ${var} 占位符名
    2. relace()          把 ${var} 替换成全局变量池中的真实值
    3. parse_relation()  按 'a.b.c' 路径从响应 JSON 中取出目标值（关联提取）

原实现依赖 DynamicParam 类属性，现改为统一走 common.variable.GlobalVar。
"""
import ast
import json
import re
from string import Template

from common.variable import GlobalVar

# 匹配 ${xxx} 占位符
PATTERN = re.compile(r"\$\{(.*?)\}")


def find(data):
    """
    从 data（dict / str）中找出所有 ${var} 占位符名称。

    :return: 占位符名列表；无匹配返回 None（兼容旧逻辑）
    """
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False)
    if not isinstance(data, str):
        return None
    result = PATTERN.findall(data)
    return result or None


def _dumps(data):
    """dict / list 统一转字符串，其余原样返回。"""
    if isinstance(data, (dict, list)):
        return json.dumps(data, ensure_ascii=False)
    return data


def relace(ori_data, replace_data=None):
    """
    将 ori_data 中的 ${var} 用 replace_data 或全局变量池中的值替换。

    :param ori_data:     原始数据（dict / list / str）
    :param replace_data: 替换字典；不传则自动从 GlobalVar 取值
    :return: 替换后的字符串（dict/list 输入时为 JSON 字符串）
    """
    ori_str = _dumps(ori_data)

    if replace_data is None:
        names = find(ori_str) or []
        replace_data = {name: GlobalVar.get(name, "") for name in names}

    # 值统一转 str，避免 Template 处理非字符串时报错
    safe_map = {str(k): "" if v is None else str(v) for k, v in replace_data.items()}
    return Template(ori_str).safe_substitute(safe_map)


def relace_obj(ori_data, replace_data=None):
    """relace 的 JSON 版：直接返回 Python 对象（dict/list）。"""
    text = relace(ori_data, replace_data)
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def parse_relation(var, res_data):
    """
    按路径逐层获取嵌套 JSON 的值。

    :param var:      路径列表，如 ['data', 'ticket']；元素可为 int 表示列表下标
    :param res_data: 响应数据
    :return: 目标值；路径不存在返回 None

    注意：不修改入参 var（原实现用 del var[0] 会污染调用方列表）。
    """
    if not var:
        return res_data
    cur = res_data
    for key in var:
        if cur is None:
            return None
        try:
            if isinstance(cur, (list, tuple)):
                cur = cur[int(key)]
            elif isinstance(cur, dict):
                cur = cur.get(key)
            else:
                return None
        except (IndexError, ValueError, TypeError):
            return None
    return cur


def parse_expression(expr, res_data):
    """
    解析关联表达式：`ticket=body.data.ticket`
    -> ("ticket", <值>)

    支持列表下标：`first=body.data.rows.0.name`
    """
    if "=" not in expr:
        raise ValueError(f"关联表达式格式错误，应为 name=path 形式：{expr}")
    name, path = expr.split("=", 1)
    value = parse_relation(path.strip().split("."), res_data)
    return name.strip(), value


def safe_loads(text, default=None):
    """
    安全地把字符串解析成 Python 对象（不执行任何代码）。

    用于替代原框架中对 Excel 内容直接 eval() 的做法，消除代码注入风险。
    优先按 JSON 解析，失败再尝试字面量解析（兼容 "{'a': 1}" 这种单引号写法）。

    :param text:    待解析内容，可为 str / dict / list，其它类型原样返回
    :param default: 解析失败时的返回值
    """
    if text is None:
        return default
    if isinstance(text, (dict, list, int, float, bool)):
        return text

    s = str(text).strip()
    if not s:
        return default

    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError, TypeError):
        return default


def to_bool(value, default=False):
    """把 '1'/'true'/'yes'/'on' 之类的值转成布尔。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on", "y")


# ----------------------------------------------------------------------
# 标签（用例分类，用于冒烟筛选等场景）
# ----------------------------------------------------------------------
def parse_tags(value):
    """
    把标签字段统一解析为字符串列表。

    兼容多种写法：
        "smoke"                -> ["smoke"]
        "smoke,core"           -> ["smoke", "core"]
        ["smoke", "core"]      -> ["smoke", "core"]
        None / "" / []         -> []
    """
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    # 兼容中文逗号与空格分隔
    text = str(value).replace("，", ",").replace("、", ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def match_tags(case_tags, wanted):
    """
    判断用例标签是否命中筛选条件（命中任意一个即算匹配）。

    :param case_tags: 用例自身的标签（字符串或列表）
    :param wanted:    期望标签（字符串或列表）；为空表示不做筛选，一律通过
    :return: bool
    """
    wanted_list = parse_tags(wanted)
    if not wanted_list:
        return True                      # 未指定筛选条件，全部放行
    return bool(set(parse_tags(case_tags)) & set(wanted_list))


# ----------------------------------------------------------------------
# XML 解析与构造（政务 / 财务 / 老 ERP 系统大量使用 XML 报文）
#
# 用标准库 xml.etree 实现，不引入第三方依赖，保证内网环境也能用。
# ----------------------------------------------------------------------
# 元素属性前缀与文本键名（与 xmltodict 等主流库保持一致的约定，便于迁移）
ATTR_PREFIX = "@"
TEXT_KEY = "#text"


def _should_convert(text):
    """判断字符串是否该转成数值。带前导 0 的编号（如 '0012'）保持字符串，避免丢前导零。"""
    return re.fullmatch(r"-?(0|[1-9]\d*)", text) or re.fullmatch(r"-?(0|[1-9]\d*)?\.\d+", text)


def _convert(text):
    """把 XML 文本转成合适类型：整数 / 浮点 / 原字符串。"""
    text = text.strip()
    if not text or not _should_convert(text):
        return text.strip()
    try:
        return int(text)
    except ValueError:
        return float(text)


def _tag_name(tag):
    """去掉命名空间前缀：'{http://x}code' -> 'code'。"""
    return str(tag).rsplit("}", 1)[-1]


def _element_to_obj(element):
    """递归把一个 Element 转成 dict / 标量。"""
    children = list(element)
    attrs = {"{}{}".format(ATTR_PREFIX, _tag_name(k)): v for k, v in element.attrib.items()}
    text = (element.text or "").strip()

    # 叶子节点：有属性就带上属性，否则直接给标量
    if not children:
        if attrs:
            if text:
                attrs[TEXT_KEY] = _convert(text)
            return attrs
        return _convert(text)

    result = dict(attrs)
    for child in children:
        name = _tag_name(child.tag)
        value = _element_to_obj(child)
        if name in result:
            # 同名子元素出现多次 -> 聚合成列表
            if not isinstance(result[name], list):
                result[name] = [result[name]]
            result[name].append(value)
        else:
            result[name] = value

    # 既有子元素又有纯文本的混合内容，把文本挂到 #text
    if text:
        result[TEXT_KEY] = _convert(text)
    return result


def xml_to_dict(text):
    """
    把 XML 文本解析成嵌套字典。

    约定（与主流 XML 库一致，便于使用者迁移）：
        子元素      -> 同名键；同名多次出现时聚合为 list
        元素属性    -> "@属性名"
        元素文本    -> "#text"
        数字文本    -> 自动转 int / float（带前导 0 的编号保持字符串）
        命名空间    -> 自动剥离（'{ns}code' -> 'code'，适配 SOAP 报文）

    :param text: XML 文本（str / bytes）
    :return: dict；解析失败返回 None（调用方据此回退为纯文本）
    """
    if text is None:
        return None
    if not isinstance(text, (str, bytes)):
        return None

    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return None

    return {_tag_name(root.tag): _element_to_obj(root)}


def dict_to_xml(data, root="root", declaration=False, encoding="utf-8"):
    """
    把字典构造成 XML 文本（xml_to_dict 的逆操作），用于给 XML 接口造报文。

    支持 @属性 与 #text 约定，可与 xml_to_dict 往返转换。

    :param data:        字典；单键 {"根名": {...}} 时自动以该键为根标签
    :param root:        根标签名（data 为多键字典时使用）
    :param declaration: 是否输出 <?xml version="1.0"?> 声明
    :param encoding:    声明里使用的编码名
    """
    import xml.etree.ElementTree as ET

    def fill(element, value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key.startswith(ATTR_PREFIX):
                    element.set(key[len(ATTR_PREFIX):], "" if item is None else str(item))
                elif key == TEXT_KEY:
                    element.text = "" if item is None else str(item)
                elif isinstance(item, list):
                    for one in item:
                        child = ET.SubElement(element, str(key))
                        fill(child, one)
                else:
                    child = ET.SubElement(element, str(key))
                    fill(child, item)
        else:
            element.text = "" if value is None else str(value)

    if isinstance(data, dict) and len(data) == 1 and root == "root":
        root_name, payload = next(iter(data.items()))
    else:
        root_name, payload = root, data

    top = ET.Element(str(root_name))
    fill(top, payload)

    if declaration:
        return '<?xml version="1.0" encoding="{}"?>'.format(encoding) + \
               ET.tostring(top, encoding="unicode")
    return ET.tostring(top, encoding="unicode")
