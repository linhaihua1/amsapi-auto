# -*- coding: utf-8 -*-
"""
YAML 用例读写工具层
===================
YAML 用例相比 Excel 的优势：支持嵌套结构、易读易 diff、便于版本管理。

目录约定：data/cases/*.yaml
单个文件结构（二选一）：

    # 形式一：带 cases 键
    cases:
      - title: 登录系统
        url: /v1/users/login
        method: get
        request_body: {...}
        relation: ticket=body.data.ticket
        expected_code: 200

    # 形式二：文件本身就是用例列表
    - title: 登录系统
      ...
"""
import os

import yaml

from common import base
from config import settings
from utils.logutil import logger

YAML_SUFFIX = (".yaml", ".yml")


def read_yaml(path):
    """读取单个 YAML 文件，返回 Python 对象；空文件返回 {}。"""
    with open(path, "r", encoding="utf-8") as fp:
        data = yaml.safe_load(fp)
    return data if data is not None else {}


def _split_depends(raw):
    """把 depends 字段拆成 id 列表（兼容中文逗号）。"""
    text = str(raw or "").replace("，", ",")
    return [item.strip() for item in text.split(",") if item.strip()]


def _order_by_depends(cases):
    """
    按 depends 关系稳定重排用例，保证「被依赖的用例一定排在依赖它的用例之前」。

    起因：用例按**文件名字母序**加载，于是 `admin.yaml`（依赖 `login.yaml` 的 1001）
    会排在 `login.yaml` 前面执行，导致 admin 的用例因「依赖尚未执行」被整体跳过 ——
    这不是用例写错了，而是加载顺序没考虑依赖关系。

    算法：按原顺序遍历，遇到带 depends 的用例时，**先递归放入它依赖的用例**再放入自己。
    这样：
        · 不写 depends 的用例集，顺序与以往**完全一致**（零影响）
        · 只有真正存在依赖时才会调整顺序，且调整幅度最小
        · 依赖关系存在环时不做任何调整并告警，避免死循环

    :param cases: read_cases 收集到的用例列表
    :return: 重排后的用例列表
    """
    if len(cases) < 2:
        return cases

    # id -> 原索引（同 id 重复时以第一条为准）
    index_of = {}
    for index, case in enumerate(cases):
        case_id = case.get("id")
        if case_id not in (None, "") and str(case_id) not in index_of:
            index_of[str(case_id)] = index

    # 依赖方索引 -> 需要先行执行的用例索引列表；只认本批次内存在的 id
    # （依赖批次外的 id 保持原语义：执行时由 check_depends 判定为「未执行」而跳过）
    deps = {}
    for index, case in enumerate(cases):
        need = []
        for key in _split_depends(case.get("depends")):
            target = index_of.get(key)
            if target is not None and target != index:
                need.append(target)
        if need:
            deps[index] = need

    if not deps:                       # 全部用例都没有有效依赖：保持原序
        return cases

    ordered, placed, visiting, cyclic = [], set(), set(), []

    def place(index):
        """递归放入「自己及自己的全部前置」。"""
        if index in placed:
            return
        if index in visiting:          # 环：记录并中断本次递归
            cyclic.append(str(cases[index].get("id")))
            return
        visiting.add(index)
        for target in deps.get(index, ()):
            place(target)
        visiting.discard(index)
        if index not in placed:
            placed.add(index)
            ordered.append(index)

    for index in range(len(cases)):
        place(index)

    if cyclic:
        logger.warning("YAML 用例存在循环依赖，已按原文件顺序执行：{}".format(
            ", ".join(sorted(set(cyclic)))))
        return cases

    return [cases[index] for index in ordered]


def read_cases(directory=None, tags=None):
    """
    读取目录下所有 YAML 用例，扁平化为用例列表。

    :param directory: 用例目录，默认 data/cases
    :param tags:      标签筛选（字符串或列表）；命中任意一个即返回。
                      为空表示不筛选。对应用例中的 `tags` 字段。
    :return: [ {title, url, method, ...}, ... ]，每条附加 __source__ 来源文件名

    执行顺序：按文件名升序加载后，再按 depends 关系做一次稳定重排，
    保证「被依赖的用例」先执行（详见 _order_by_depends）。
    """
    directory = directory or settings.CASES_DIR
    cases = []

    if not os.path.isdir(directory):
        logger.warning("YAML 用例目录不存在：{}".format(directory))
        return cases

    for name in sorted(os.listdir(directory)):
        if not name.lower().endswith(YAML_SUFFIX):
            continue

        path = os.path.join(directory, name)
        doc = read_yaml(path)

        # 兼容 {cases: [...]} 与 直接列表 两种写法
        items = doc.get("cases") if isinstance(doc, dict) else doc
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                logger.warning("跳过非法用例（非字典）：{} 第 {} 条".format(name, index + 1))
                continue
            item.setdefault("isdel", 1)                 # YAML 用例默认参与执行
            item["__source__"] = name                    # 记录来源，便于排查
            cases.append(item)

    # 标签筛选：CI/CD 冒烟测试即通过此参数只取核心用例
    if base.parse_tags(tags):
        cases = [c for c in cases if base.match_tags(c.get("tags"), tags)]

    # 依赖重排：必须在标签筛选之后 —— 被筛掉的用例不参与依赖链，
    # 否则会出现「为了满足依赖而把一条本不该执行的用例排进来」的错觉
    cases = _order_by_depends(cases)

    logger.info("从 {} 读取到 {} 条 YAML 用例".format(directory, len(cases)))
    return cases


if __name__ == "__main__":
    for case in read_cases():
        print(case.get("title"), case.get("url"))
