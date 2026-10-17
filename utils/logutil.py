# -*- coding: utf-8 -*-
"""
日志工具层
==========
特性：
    1. 全局单例，重复 import 不会重复挂 handler（原实现会重复输出）
    2. 同时输出到「控制台」与「按天日志文件」
    3. 文件以追加模式写入，避免覆盖当天已有日志
    4. **级别 / 格式 / 文件名 / logger 名全部可配置**（conf.ini 的 [log] 段 +
       AMSAPI_LOG_* 环境变量），本文件不再写死任何一项

用法：
    from utils.logutil import logger
    logger.info("xxx")
"""
import logging
import os
import sys

from config import settings

# 兼容旧引用：历史代码可能 `from utils.logutil import LOG_FORMAT`
# 取值统一来自配置中心（settings.LogConfig），保证「改配置即生效」。
LOG_FORMAT = settings.LogConfig.FORMAT
DATE_FORMAT = settings.LogConfig.DATE_FORMAT

# 根 logger 名称（所有子 logger 均以此为前缀）。取自配置中心，改 conf.ini [log] root_name 即可。
_ROOT_NAME = settings.LogConfig.ROOT_NAME


def _to_level(value, default=logging.DEBUG):
    """把配置里的级别字符串转成 logging 常量；非法值回退默认级别。"""
    if isinstance(value, int):
        return value
    level = logging.getLevelName(str(value).strip().upper())
    return level if isinstance(level, int) else default


def root_name():
    """当前 logger 根名称（等价于 _ROOT_NAME，供外部按需读取）。"""
    return _ROOT_NAME


def _log_file_path():
    """当天日志文件的完整路径（文件名格式可配置）。"""
    return os.path.join(settings.LOG_DIR, settings.LogConfig.file_name())


def _setup_root():
    """初始化根 logger（仅执行一次）。"""
    root = logging.getLogger(root_name())
    if root.handlers:            # 已初始化过，直接返回，防止重复输出
        return root

    root.setLevel(_to_level(settings.LogConfig.LEVEL))
    formatter = logging.Formatter(settings.LogConfig.FORMAT, settings.LogConfig.DATE_FORMAT)

    # 1) 控制台输出（级别可单独配置，CI 里常调成 INFO 少刷屏）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_to_level(settings.LogConfig.CONSOLE_LEVEL))
    console.setFormatter(formatter)
    root.addHandler(console)

    # 2) 文件输出（按天，追加模式）；目录不可写时降级为仅控制台，不影响测试执行
    try:
        file_handler = logging.FileHandler(_log_file_path(), encoding="utf-8", mode="a")
        file_handler.setLevel(_to_level(settings.LogConfig.LEVEL))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("日志文件创建失败，已降级为仅控制台输出：{}".format(exc))

    # 不再向父 logger 传播，避免与 root 重复打印
    root.propagate = False
    return root


def get_logger(name=None):
    """
    获取 logger。

    :param name: 子模块名，可选。传了会得到 <root_name>.<name> 的 logger
    """
    _setup_root()
    base = root_name()
    return logging.getLogger(base if not name else "{}.{}".format(base, name))


# 默认 logger，直接 `from utils.logutil import logger` 即可使用
logger = get_logger()


if __name__ == "__main__":
    logger.debug("debug 级别日志")
    logger.info("info 级别日志")
    logger.warning("warning 级别日志")
    logger.error("error 级别日志")
    print("日志文件：{}".format(_log_file_path()))
