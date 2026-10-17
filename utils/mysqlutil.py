# -*- coding: utf-8 -*-
"""
MySQL 工具层（可选）
====================
用作「可选数据源」与「结果落库」通道，默认不启用。
只有 config/conf.ini 中 run.data_source = mysql 时才会被真正调用。

相比原框架的改进：
    1. 惰性连接：原实现在模块导入时就 connect，装了框架但没起数据库会直接崩；
       现在改为按需连接，未使用 MySQL 的环境不受影响
    2. 修正原 `cursor=pymysql.cursors.DictCursor` 的参数名错误（应为 cursorclass）
    3. 支持参数化查询（args），避免 SQL 注入
    4. 支持 with 语法，自动关闭连接
    5. pymysql 未安装时给出友好提示，不影响其它层导入
    6. 提供 validate_db_config()：真实使用方在连接前显式校验配置是否填全，
       缺项时给出可操作指引，而不是甩出 pymysql 的连接裸栈
"""
from common.exceptions import ConfigError
from config import settings
from utils.logutil import logger

try:
    import pymysql
except ImportError:            # 未安装 pymysql 时不阻塞其它模块导入
    pymysql = None


# 建立有效连接必须提供的最小配置项（password 允许为空，如本地免密实例）
DB_REQUIRED_KEYS = ("host", "user", "database")


def validate_db_config(config=None):
    """
    校验 MySQL 连接配置是否完整，缺项时抛出可操作的 ConfigError。

    为什么单独抽成模块级函数，而不是塞进 MysqlUtil.connect()：
        MysqlUtil 是「低层连接封装」，其职责就是把一个 config 交给 pymysql；
        单测与替身场景本来就允许用不完整配置去验证「连接参数怎么传」。
        而「配置填没填全」属于配置层职责，应由真实使用方显式调用本函数判定。

    :param config: 待校验的配置字典；不传则取 settings.DB_CONFIG
    :return: True（校验通过）
    :raise ConfigError: 缺少 host / user / database 中任意一项
    """
    config = dict(config or settings.DB_CONFIG)
    missing = [key for key in DB_REQUIRED_KEYS
               if not str(config.get(key) or "").strip()]
    if missing:
        raise ConfigError(
            "MySQL 数据源未配置（缺少：{}）。\n"
            "  方式一：在 config/conf.ini 的 [db] 段填写 host / user / password / database\n"
            "  方式二：注入环境变量 AMSAPI_DB_HOST / AMSAPI_DB_USER / "
            "AMSAPI_DB_PASSWORD / AMSAPI_DB_NAME（CI 推荐）\n"
            "  若本次并不需要 MySQL，把 conf.ini 的 [run] data_source 改回 excel 或 yaml 即可。".format(
                ", ".join(missing)))
    return True


class MysqlUtil:
    """MySQL 连接与执行封装。"""

    def __init__(self, config=None):
        self.config = dict(config or settings.DB_CONFIG)
        self.db = None
        self.cursor = None

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------
    def connect(self):
        """建立连接（幂等，已连接则直接返回）。"""
        if pymysql is None:
            raise RuntimeError("未安装 pymysql，无法使用 MySQL 数据源，请执行：pip install pymysql")
        if not self.is_connected:
            # 注意：这里不做「配置是否填全」的校验 —— 那是 validate_db_config()
            # 的职责，由真实使用方（utils/readmysql.py、testcase 层）在连接前调用。
            self.db = pymysql.connect(cursorclass=pymysql.cursors.DictCursor, **self.config)
            self.cursor = self.db.cursor()
            logger.debug("MySQL 已连接：{}:{}/{}".format(
                self.config.get("host"), self.config.get("port"), self.config.get("database")))
        return self.db

    @property
    def is_connected(self):
        return self.db is not None and getattr(self.db, "open", False)

    def _ensure(self):
        self.connect()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    def get_fetchone(self, sql, args=None):
        """执行查询并返回单条记录（dict）。"""
        self._ensure()
        self.cursor.execute(sql, args)
        return self.cursor.fetchone()

    def get_fetchall(self, sql, args=None):
        """执行查询并返回全部记录（list[dict]）。"""
        self._ensure()
        self.cursor.execute(sql, args)
        return self.cursor.fetchall()

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    def sql_execute(self, sql, args=None):
        """
        执行增删改语句，成功返回受影响行数，失败回滚并返回 False。
        """
        self._ensure()
        try:
            rows = self.cursor.execute(sql, args)
            self.db.commit()
            return rows
        except Exception as exc:
            self.db.rollback()
            logger.error("SQL 执行失败，已回滚：{} | {}".format(sql, exc))
            return False

    # ------------------------------------------------------------------
    # 收尾
    # ------------------------------------------------------------------
    def close(self):
        """关闭游标与连接。"""
        try:
            if self.cursor is not None:
                self.cursor.close()
        finally:
            if self.db is not None:
                self.db.close()
            self.cursor = None
            self.db = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False
