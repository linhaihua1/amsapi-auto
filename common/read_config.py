# -*- coding: utf-8 -*-
"""
INI 配置读取工具
================
薄封装 configparser，提供带默认值与类型转换的读取能力。
"""
import configparser
import os

# 缺省值哨兵：用于区分「未传 default」与「显式传 default=None」
# 原实现用 `default is not None` 判断，导致 default=None（期望缺省返回 None）时仍抛 KeyError
_MISS = object()


class ReadConfig:
    @staticmethod
    def get_config(file_path, section, option, default=_MISS):
        """
        读取 ini 配置项。

        :param file_path: ini 文件路径
        :param section:   段名
        :param option:    键名
        :param default:   缺省值；不传且配置不存在时抛 KeyError（显式传 None 则返回 None）
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"配置文件不存在：{file_path}")

        # interpolation=None：配置值里可能含 % 或 ${}（日志格式、签名盐、URL 编码），
        # 关闭插值才不会把它们当成插值语法而报错
        cf = configparser.ConfigParser(interpolation=None)
        cf.read(file_path, encoding="utf-8")

        if cf.has_section(section) and cf.has_option(section, option):
            return cf.get(section, option)

        if default is not _MISS:
            return default
        raise KeyError(f"配置项缺失：section='{section}', option='{option}' ({file_path})")

    @staticmethod
    def get_section(file_path, section):
        """读取整段配置，返回 dict。"""
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"配置文件不存在：{file_path}")
        cf = configparser.ConfigParser(interpolation=None)
        cf.read(file_path, encoding="utf-8")
        return dict(cf[section]) if cf.has_section(section) else {}


if __name__ == "__main__":
    # 自测：读取主配置文件的报告类型
    from common.project_path import Path
    print(ReadConfig.get_config(Path.conf_path, "report", "report_type", default="allure"))
