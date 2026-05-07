"""
临时数据缓存
Temporary cache for expensive AkShare pulls
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd


class TmpDataCache:
    """
    将 AkShare 拉取结果缓存到 /tmp，默认 24 小时内复用。
    """

    def __init__(self, base_dir: Optional[str] = None, max_age_seconds: int = 24 * 60 * 60):
        self.base_dir = Path(base_dir or os.environ.get(
            "QUANT_ASHARE_CACHE_DIR",
            "/tmp/quant_ashare_stock_picking_cache",
        ))
        self.max_age_seconds = max_age_seconds

    def get_or_fetch_dataframe(
        self,
        namespace: str,
        key: Dict[str, Any],
        fetcher: Callable[[], pd.DataFrame],
    ) -> Tuple[pd.DataFrame, bool, Path]:
        """
        返回 DataFrame、是否命中缓存、缓存文件路径。
        """
        cached = self.get_dataframe(namespace, key)
        cache_path = self.path_for(namespace, key)
        if cached is not None:
            return cached, True, cache_path

        data = fetcher()
        if data is not None and not data.empty:
            self.set_dataframe(namespace, key, data)
        return data, False, cache_path

    def get_dataframe(self, namespace: str, key: Dict[str, Any]) -> Optional[pd.DataFrame]:
        cache_path = self.path_for(namespace, key)
        if not cache_path.exists() or self._is_expired(cache_path):
            return None

        try:
            return pd.read_pickle(cache_path)
        except Exception:
            return None

    def set_dataframe(self, namespace: str, key: Dict[str, Any], data: pd.DataFrame) -> Path:
        cache_path = self.path_for(namespace, key)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = cache_path.with_suffix(".tmp")
        data.to_pickle(temp_path)
        temp_path.replace(cache_path)
        return cache_path

    def path_for(self, namespace: str, key: Dict[str, Any]) -> Path:
        key_payload = json.dumps(key, sort_keys=True, ensure_ascii=False, default=str)
        digest = hashlib.sha256(key_payload.encode("utf-8")).hexdigest()[:24]
        return self.base_dir / namespace / f"{digest}.pkl"

    def _is_expired(self, cache_path: Path) -> bool:
        return time.time() - cache_path.stat().st_mtime > self.max_age_seconds
