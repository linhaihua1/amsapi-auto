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
    5. **敏感信息脱敏**：日志里的口令 / 令牌 / 票据一律打码后才落盘与打印，
       避免真实凭据随日志文件归档、转发、进制品（见 common/mask.py）
    6. **大小轮转与保留**：单个日志文件超过 max_bytes 后自动轮转出 .1/.2 备份，
       并可按 keep_days 清理历史日志，避免长期运行把磁盘写满

用法：
    from utils.logutil import logger
    logger.info("xxx")
"""
import logging
import os
import re
import sys
import time

from common import mask
from config import settings

# 兼容旧引用：历史代码可能 `from utils.logutil import LOG_FORMAT`
# 取值统一来自配置中心（settings.LogConfig），保证「改配置即生效」。
LOG_FORMAT = settings.LogConfig.FORMAT
DATE_FORMAT = settings.LogConfig.DATE_FORMAT

# 根 logger 名称（所有子 logger 均以此为前缀）。取自配置中心，改 conf.ini [log] root_name 即可。
_ROOT_NAME = settings.LogConfig.ROOT_NAME


class SensitiveFilter(logging.Filter):
    """
    日志脱敏过滤器。

    为什么做成 logging Filter 而不是在每处调用点手动脱敏：
        · 一处生效、全框架覆盖，新增日志代码不需要记得脱敏（这是「不遗漏」的关键）
        · 挂在 logger 上而非 handler 上，不改变 handler 数量与轮转行为
        · 脱敏失败时**放行原日志**而不是抛异常 —— 日志组件绝不能拖垮测试执行
    """

    def filter(self, record):
        if not mask.enabled():
            return True
        try:
            if isinstance(record.msg, str):
                record.msg = mask.mask_text(record.msg)
            elif isinstance(record.msg, (dict, list, tuple)):
                record.msg = mask.mask_payload(record.msg)

            # 参数化日志（logger.info("...%s", value)）同样可能带敏感值
            if isinstance(record.args, tuple):
                record.args = tuple(mask.mask_payload(item) for item in record.args)
            elif isinstance(record.args, dict):
                record.args = mask.mask_payload(record.args)
        except Exception:                                  # noqa: BLE001 —— 绝不因脱敏失败而丢日志
            pass
        return True


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


def _make_file_handler():
    """
    创建日志文件 handler。

    超过 max_bytes 时使用 RotatingFileHandler（仍保持「按天 + 追加」的既有约定），
    否则沿用普通 FileHandler —— 行为与改造前完全一致。
    """
    path = _log_file_path()
    max_bytes = int(getattr(settings.LogConfig, "MAX_BYTES", 0) or 0)
    if max_bytes > 0:
        from logging.handlers import RotatingFileHandler
        return RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=int(settings.LogConfig.BACKUP_COUNT or 0),
            encoding="utf-8", mode="a")
    return logging.FileHandler(path, encoding="utf-8", mode="a")


def _date_file_regex():
    """
    依据配置的日志文件名格式生成匹配用的正则。

    用途：只清理「框架自己按天生成的日志」，绝不误删 LOG_DIR 下的人为文件。
    例如格式 %Y_%m_%d -> ^\\d{4}_\\d{2}_\\d{2}\\.log$
    """
    fmt = str(settings.LogConfig.FILE_NAME_FORMAT or "")
    if not fmt:
        return None
    tokens = {"%Y": r"\d{4}", "%m": r"\d{2}", "%d": r"\d{2}",
              "%H": r"\d{2}", "%M": r"\d{2}", "%S": r"\d{2}"}
    pattern = re.escape(fmt)
    for token, regex in tokens.items():
        pattern = pattern.replace(re.escape(token), regex)
    return re.compile(r"^{}\.log(\.\d+)?$".format(pattern))


def _cleanup_old_logs():
    """
    清理超过保留天数的历史日志。

    安全约束：
        · keep_days <= 0 时**不执行任何删除**（默认关闭，避免误删）
        · 只删除文件名完全匹配「按天日志格式（含 .1/.2 轮转备份）」的文件
        · 任何异常都静默忽略，日志清理失败不能影响测试执行
    """
    keep_days = int(getattr(settings.LogConfig, "KEEP_DAYS", 0) or 0)
    if keep_days <= 0:
        return
    matcher = _date_file_regex()
    if matcher is None or not os.path.isdir(settings.LOG_DIR):
        return

    deadline = time.time() - keep_days * 86400
    removed = 0
    try:
        for name in os.listdir(settings.LOG_DIR):
            if not matcher.match(name):
                continue
            path = os.path.join(settings.LOG_DIR, name)
            try:
                if os.path.isfile(path) and os.path.getmtime(path) < deadline:
                    os.remove(path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return

    if removed:
        logging.getLogger(root_name()).info(
            "已清理 {} 个超过 {} 天的历史日志（保留策略可在 conf.ini [log] keep_days 调整）".format(
                removed, keep_days))


def _setup_root():
    """初始化根 logger（仅执行一次）。"""
    root = logging.getLogger(root_name())
    if root.handlers:            # 已初始化过，直接返回，防止重复输出
        return root

    root.setLevel(_to_level(settings.LogConfig.LEVEL))
    formatter = logging.Formatter(settings.LogConfig.FORMAT, settings.LogConfig.DATE_FORMAT)

    # 0) 脱敏过滤器：挂在 logger 上（对所有 handler 生效，且不改变 handler 数量）
    root.addFilter(SensitiveFilter())

    # 1) 控制台输出（级别可单独配置，CI 里常调成 INFO 少刷屏）
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_to_level(settings.LogConfig.CONSOLE_LEVEL))
    console.setFormatter(formatter)
    root.addHandler(console)

    # 2) 文件输出（按天 + 追加；超过 max_bytes 时轮转）；目录不可写时降级为仅控制台
    try:
        file_handler = _make_file_handler()
        file_handler.setLevel(_to_level(settings.LogConfig.LEVEL))
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError as exc:
        root.warning("日志文件创建失败，已降级为仅控制台输出：{}".format(exc))

    # 不再向父 logger 传播，避免与 root 重复打印
    root.propagate = False

    # 3) 历史日志保留策略（keep_days = 0 时不做任何事）
    _cleanup_old_logs()
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
