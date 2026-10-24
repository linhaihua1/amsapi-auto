# -*- coding: utf-8 -*-
"""
单元测试：utils/logutil.py（日志工具层）
=======================================
重点是「单例不重复挂 handler」——原实现重复 import 会导致日志重复输出，
这里用可观测的 handler 数量来锁定该行为。
"""
import logging
import os

from utils import logutil
from utils.logutil import SensitiveFilter, get_logger, logger


def _own_handlers():
    """
    只取「框架自己挂的」handler。

    pytest 的 logging 插件会把自身的 LogCaptureHandler 等挂到所有已存在的
    logger 上，因此必须过滤掉，否则断言会被测试环境干扰。
    """
    return [h for h in logging.getLogger(logutil._ROOT_NAME).handlers
            if not type(h).__module__.startswith("_pytest")]


class TestLogUtil:
    def test_default_logger_name(self):
        assert logger.name == logutil._ROOT_NAME

    def test_get_logger_with_name(self):
        child = get_logger("demo")
        assert child.name == "{}.demo".format(logutil._ROOT_NAME)

    def test_handlers_not_duplicated(self):
        """重复调用不应重复挂 handler。"""
        before = len(_own_handlers())
        for _ in range(5):
            get_logger()
        assert len(_own_handlers()) == before == 2        # 控制台 + 文件

    def test_has_console_and_file_handler(self):
        handlers = _own_handlers()
        assert any(isinstance(h, logging.StreamHandler) and
                   not isinstance(h, logging.FileHandler) for h in handlers)
        assert any(isinstance(h, logging.FileHandler) for h in handlers)

    def test_file_handler_appends(self):
        """日志文件必须是追加模式，避免覆盖当天已写入的内容。"""
        file_handlers = [h for h in _own_handlers()
                         if isinstance(h, logging.FileHandler)]
        assert file_handlers
        assert file_handlers[0].mode == "a"

    def test_log_file_name_is_dated(self):
        file_handlers = [h for h in _own_handlers()
                         if isinstance(h, logging.FileHandler)]
        name = os.path.basename(file_handlers[0].baseFilename)
        assert len(name) == 14                            # YYYY_MM_DD.log
        assert name.endswith(".log")

    def test_log_file_written_into_log_dir(self):
        file_handlers = [h for h in _own_handlers()
                         if isinstance(h, logging.FileHandler)]
        # 用 normpath 归一后比较：LOG_DIR 可能由环境变量以正斜杠形式传入，
        # 直接字符串比较会把「路径写法不同」误判成「目录不对」
        assert (os.path.normpath(os.path.dirname(file_handlers[0].baseFilename))
                == os.path.normpath(logutil.settings.LOG_DIR))

    def test_propagate_disabled(self):
        """不应向父 logger 传播，否则会与 root 重复打印。"""
        assert logging.getLogger(logutil._ROOT_NAME).propagate is False

    def test_write_does_not_raise(self):
        """日志调用本身不应抛异常（内容含中文与特殊字符）。"""
        logger.info("单元测试日志：中文内容 %s", "ok")
        logger.debug("debug 级别")


# ======================================================================
# 脱敏过滤器（SensitiveFilter）—— 明文泄漏的最后一道防线
# ----------------------------------------------------------------------
# 为什么单独测这一层：日志是**落盘产物**，会随 CI 工件被打包、被转发。
# 口令一旦进了日志文件，事后无法回收。过滤器挂在 logger 上而不是每个调用点，
# 就是为了「新增日志代码不需要记得脱敏」，因此它的每个分支都必须有效。
# ======================================================================
def _record(msg, args=None):
    return logging.LogRecord("demo", logging.INFO, __file__, 1, msg, args, None)


class TestSensitiveFilter:
    def test_masks_plain_message(self):
        record = _record("登录口令 password=Secret123")
        assert SensitiveFilter().filter(record) is True
        assert "Secret123" not in record.msg

    def test_masks_dict_message(self):
        """直接打印响应体是常见写法（logger.info(resp_dict)）。"""
        record = _record({"msg": "认证失败 password=Secret123"})
        SensitiveFilter().filter(record)
        assert "Secret123" not in str(record.msg)

    def test_masks_positional_args(self):
        """
        参数化日志是性能推荐写法，也最容易成为漏点：
        口令在 record.args 里，而 record.msg 只是个占位符。
        """
        record = _record("响应 %s", ({"msg": "password=Secret123"},))
        SensitiveFilter().filter(record)
        assert "Secret123" not in str(record.args)

    def test_masks_mapping_args(self):
        """%(name)s 映射参数（logging 会把单元素 dict 解包进 record.args）。"""
        record = logging.LogRecord("demo", logging.INFO, __file__, 1,
                                   "%(body)s", ({"body": "token=Secret123"},), None)
        assert isinstance(record.args, dict)          # logging 已解包成映射
        SensitiveFilter().filter(record)
        assert "Secret123" not in str(record.args)

    def test_masked_text_is_still_loggable(self):
        """脱敏后仍必须能正常 format 出字符串（不能因为改了 msg 就崩）。"""
        record = _record("headers = %s", ({"password": "Secret123"},))
        SensitiveFilter().filter(record)
        assert "Secret123" not in record.getMessage()

    def test_disabled_keeps_original(self):
        """关闭开关是排查问题时的逃生门，必须真的原样输出。"""
        from config import settings
        settings.MaskConfig.ENABLED = False
        try:
            record = _record("password=Secret123")
            assert SensitiveFilter().filter(record) is True
            assert record.msg == "password=Secret123"
        finally:
            settings.MaskConfig.ENABLED = True

    def test_mask_failure_never_drops_log(self, monkeypatch):
        """脱敏自己炸了也只能放行原日志 —— 丢日志比泄漏更难查。"""
        from common import mask as mask_module
        monkeypatch.setattr(mask_module, "mask_text",
                            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
        record = _record("password=Secret123")
        assert SensitiveFilter().filter(record) is True
        assert record.msg == "password=Secret123"
