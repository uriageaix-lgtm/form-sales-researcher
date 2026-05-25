"""ロギングの共通設定。

コンソールとログファイルの両方に出力する。
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_LOGGER_NAME = "form_sales_researcher"


def setup_logger(log_path: str | None = None, verbose: bool = False) -> logging.Logger:
    """ロガーを初期化して返す。

    Args:
        log_path: ログファイルの保存先。None ならファイル出力しない。
        verbose: True なら DEBUG レベルまで出す。
    """
    logger = logging.getLogger(_LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    logger.addHandler(console)

    if log_path:
        path = Path(log_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(fmt)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """既に初期化済みのロガーを取得する。"""
    return logging.getLogger(_LOGGER_NAME)
