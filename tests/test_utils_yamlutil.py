# -*- coding: utf-8 -*-
"""
单元测试：utils/yamlutil.py（YAML 用例读写层）
=============================================
覆盖两种文件结构、默认字段补全、非法项跳过、标签筛选与目录不存在等分支。
"""
import os

from config import settings
from utils.yamlutil import YAML_SUFFIX, read_cases, read_yaml


# ======================================================================
# 一、单文件读取
# ======================================================================
class TestReadYaml:
    def test_read_cases_key_form(self, tmp_path):
        f = tmp_path / "a.yaml"
        f.write_text("cases:\n  - title: A\n", encoding="utf-8")
        assert read_yaml(str(f)) == {"cases": [{"title": "A"}]}

    def test_read_list_form(self, tmp_path):
        f = tmp_path / "a.yaml"
        f.write_text("- title: A\n", encoding="utf-8")
        assert read_yaml(str(f)) == [{"title": "A"}]

    def test_empty_file_returns_empty_dict(self, tmp_path):
        f = tmp_path / "a.yaml"
        f.write_text("", encoding="utf-8")
        assert read_yaml(str(f)) == {}

    def test_chinese_content(self, tmp_path):
        f = tmp_path / "a.yaml"
        f.write_text("cases:\n  - title: 登录系统\n", encoding="utf-8")
        assert read_yaml(str(f))["cases"][0]["title"] == "登录系统"


# ======================================================================
# 二、目录批量读取
# ======================================================================
class TestReadCases:
    def test_missing_directory_returns_empty(self, tmp_path):
        assert read_cases(str(tmp_path / "not_exist")) == []

    def test_default_directory_from_settings(self):
        """默认目录取自 settings，且真实用例目录可读。"""
        assert os.path.isdir(settings.CASES_DIR)
        assert len(read_cases()) >= 1

    def test_reads_all_yaml_files(self, yaml_dir):
        cases = read_cases(yaml_dir)
        assert {c["title"] for c in cases} == {"登录系统", "字典查询"}

    def test_non_yaml_file_ignored(self, yaml_dir):
        """同一目录下的 .txt 不应被当成用例。"""
        cases = read_cases(yaml_dir)
        assert all(c["__source__"].endswith(YAML_SUFFIX) for c in cases)

    def test_empty_yaml_contributes_nothing(self, yaml_dir):
        assert all(c["__source__"] != "empty.yaml" for c in read_cases(yaml_dir))

    def test_source_recorded(self, yaml_dir):
        cases = read_cases(yaml_dir)
        login = [c for c in cases if c["title"] == "登录系统"][0]
        assert login["__source__"] == "a-login.yaml"

    def test_isdel_defaults_to_one(self, yaml_dir):
        """YAML 用例不写 isdel 时默认参与执行。"""
        cases = read_cases(yaml_dir)
        assert [c["isdel"] for c in cases if c["title"] == "登录系统"] == [1]

    def test_explicit_isdel_kept(self, yaml_dir):
        cases = read_cases(yaml_dir)
        assert [c["isdel"] for c in cases if c["title"] == "字典查询"] == [0]

    def test_invalid_item_skipped(self, yaml_dir):
        """列表里混入非字典项应被跳过，而不是让整个文件失败。"""
        cases = read_cases(yaml_dir)
        assert len(cases) == 2

    def test_files_loaded_in_name_order(self, yaml_dir):
        """无 depends 时按文件名升序加载（有 depends 时才做依赖重排，见第四节）。"""
        assert [c["title"] for c in read_cases(yaml_dir)] == ["登录系统", "字典查询"]

    def test_tag_filter(self, yaml_dir):
        cases = read_cases(yaml_dir, tags="smoke")
        assert [c["title"] for c in cases] == ["登录系统"]

    def test_tag_filter_regression(self, yaml_dir):
        cases = read_cases(yaml_dir, tags="regression")
        assert [c["title"] for c in cases] == ["字典查询"]

    def test_tag_filter_no_match(self, yaml_dir):
        assert read_cases(yaml_dir, tags="not-exist") == []

    def test_no_filter_returns_all(self, yaml_dir):
        assert len(read_cases(yaml_dir, tags=None)) == 2

    def test_case_fields_preserved(self, yaml_dir):
        case = read_cases(yaml_dir)[0]
        assert case["url"] == "/v1/users/login"
        assert case["method"] == "get"
        assert case["relation"] == "ticket=body.data.ticket"
        assert case["expected_code"] == 200


# ======================================================================
# 三、依赖排序（depends 跨文件时也要先跑前置）
# ======================================================================
class TestOrderByDepends:
    """
    用例按文件名字母序加载，若「被依赖的用例」所在文件排在后面
    （如 admin.yaml 依赖 login.yaml 的 id），依赖方会先执行而被跳过。
    这里锁定「按 depends 稳定重排」的行为。
    """

    @staticmethod
    def _write(directory, name, text):
        (directory / name).write_text(text, encoding="utf-8")

    def test_dependency_moved_before_dependent(self, tmp_path):
        """a 开头文件里的用例依赖 z 开头文件里的用例时，z 会被提到 a 之前。"""
        self._write(tmp_path, "a-admin.yaml",
                    "cases:\n"
                    "  - id: 2\n"
                    "    title: 依赖登录的接口\n"
                    "    url: /admin/x\n"
                    "    method: get\n"
                    "    depends: 1\n")
        self._write(tmp_path, "z-login.yaml",
                    "cases:\n"
                    "  - id: 1\n"
                    "    title: 登录\n"
                    "    url: /v1/users/login\n"
                    "    method: get\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["登录", "依赖登录的接口"]

    def test_no_depends_keeps_name_order(self, tmp_path):
        """没有任何 depends 时，顺序与按文件名升序完全一致。"""
        self._write(tmp_path, "a.yaml", "cases:\n  - title: A\n    url: /a\n    method: get\n")
        self._write(tmp_path, "b.yaml", "cases:\n  - title: B\n    url: /b\n    method: get\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["A", "B"]

    def test_multi_level_dependency(self, tmp_path):
        """链式依赖 1 <- 2 <- 3 时，执行顺序应为 1、2、3。"""
        self._write(tmp_path, "all.yaml",
                    "cases:\n"
                    "  - id: 3\n"
                    "    title: 第三步\n"
                    "    url: /c\n"
                    "    method: get\n"
                    "    depends: 2\n"
                    "  - id: 2\n"
                    "    title: 第二步\n"
                    "    url: /b\n"
                    "    method: get\n"
                    "    depends: 1\n"
                    "  - id: 1\n"
                    "    title: 第一步\n"
                    "    url: /a\n"
                    "    method: get\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["第一步", "第二步", "第三步"]

    def test_sibling_order_kept(self, tmp_path):
        """一条用例的多个依赖按 depends 的书写顺序排入。"""
        self._write(tmp_path, "all.yaml",
                    "cases:\n"
                    "  - id: 9\n"
                    "    title: 汇总\n"
                    "    url: /z\n"
                    "    method: get\n"
                    "    depends: 7,8\n"
                    "  - id: 8\n"
                    "    title: 乙\n"
                    "    url: /b\n"
                    "    method: get\n"
                    "  - id: 7\n"
                    "    title: 甲\n"
                    "    url: /a\n"
                    "    method: get\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["甲", "乙", "汇总"]

    def test_unknown_dependency_id_ignored(self, tmp_path):
        """depends 指向本批次不存在的 id 时不做重排（执行期由 check_depends 判为跳过）。"""
        self._write(tmp_path, "b.yaml",
                    "cases:\n"
                    "  - id: 2\n"
                    "    title: 依赖外部用例\n"
                    "    url: /b\n"
                    "    method: get\n"
                    "    depends: 404\n")
        self._write(tmp_path, "a.yaml", "cases:\n  - title: A\n    url: /a\n    method: get\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["A", "依赖外部用例"]

    def test_circular_dependency_keeps_original_order(self, tmp_path):
        """循环依赖不应死循环：保持原序返回，并由日志告警。"""
        self._write(tmp_path, "c.yaml",
                    "cases:\n"
                    "  - id: 1\n"
                    "    title: 甲\n"
                    "    url: /a\n"
                    "    method: get\n"
                    "    depends: 2\n"
                    "  - id: 2\n"
                    "    title: 乙\n"
                    "    url: /b\n"
                    "    method: get\n"
                    "    depends: 1\n")
        assert [c["title"] for c in read_cases(str(tmp_path))] == ["甲", "乙"]
