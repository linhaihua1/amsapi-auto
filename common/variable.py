# -*- coding: utf-8 -*-
"""
全局变量池
==========
替代原框架中 `setattr(DynamicParam, name, val)` 的类属性 hack。

用途：接口之间的参数关联传递。
    用例 A 提取 ticket  ->  GlobalVar.set("ticket", "xxx")
    用例 B 引用 ${ticket} ->  GlobalVar.get("ticket")

支持点号路径读写，例如 GlobalVar.set("user.id", 1) / GlobalVar.get("user.id")。
"""
import threading


class GlobalVar:
    _store = {}
    _lock = threading.RLock()

    # ---------------- 基础读写 ----------------
    @classmethod
    def set(cls, key, value):
        """写入变量。key 支持 'a.b.c' 形式的层级路径。"""
        with cls._lock:
            cls._store[key] = value
        return value

    @classmethod
    def get(cls, key, default=None):
        """读取变量，不存在返回 default。"""
        with cls._lock:
            if key in cls._store:
                return cls._store[key]
            # 尝试按点号路径逐层取值
            cur = cls._store
            try:
                for part in str(key).split("."):
                    cur = cur[part]
                return cur
            except (KeyError, TypeError):
                return default

    @classmethod
    def update(cls, mapping):
        """批量写入，mapping 为 dict。"""
        with cls._lock:
            cls._store.update(mapping or {})

    @classmethod
    def has(cls, key):
        return cls.get(key, default=_MISS) is not _MISS

    @classmethod
    def all(cls):
        with cls._lock:
            return dict(cls._store)

    @classmethod
    def clear(cls):
        """每个测试会话开始前清空，避免用例间脏数据。"""
        with cls._lock:
            cls._store.clear()


_MISS = object()
