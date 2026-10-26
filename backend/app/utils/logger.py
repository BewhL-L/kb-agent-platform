"""
统一日志配置
- 控制台彩色输出 + 可选文件输出
- 所有模块统一通过 get_logger(__name__) 获取 logger
"""
import logging
import sys

from ..config import settings

# 日志格式
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def _configure_root_logger() -> None:
    """只配置一次 root logger"""
    global _configured
    if _configured:
        return

    level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
    root = logging.getLogger("app")
    root.setLevel(level)
    root.propagate = False

    # 避免重复添加 handler
    if not root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_LOG_FORMAT, _DATE_FORMAT))
        root.addHandler(handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """获取统一命名的 logger"""
    _configure_root_logger()
    # 传入的 name 可能是 __name__（app.xxx），统一归到 app 下
    if not name.startswith("app"):
        name = f"app.{name}"
    return logging.getLogger(name)
