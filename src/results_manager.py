"""
结果输出目录管理
Result output directory helpers
"""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd


def create_timestamped_result_dir(base_dir: str = "results", timestamp: Optional[str] = None) -> Path:
    """
    创建 results/<timestamp> 形式的输出目录。

    如果同一秒内重复运行导致目录已存在，会自动追加 _01, _02 等后缀。
    """
    base_path = Path(base_dir)
    run_timestamp = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = base_path / run_timestamp

    if run_dir.exists():
        suffix = 1
        while True:
            candidate = base_path / f"{run_timestamp}_{suffix:02d}"
            if not candidate.exists():
                run_dir = candidate
                break
            suffix += 1

    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def file_sha256(path: str | Path) -> str:
    """
    Return the SHA-256 hash for a local file.
    """
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def current_git_commit(cwd: str | Path = ".") -> Optional[str]:
    """
    Best-effort current git commit hash for run metadata.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(cwd),
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    commit = result.stdout.strip()
    return commit or None


def describe_stock_pool(csv_path: str | Path, stock_info: Optional[pd.DataFrame] = None) -> dict:
    """
    Flat stock-pool metadata suitable for CSV/JSON run configs.
    """
    path = Path(csv_path)
    if stock_info is None:
        stock_info = pd.read_csv(path)

    columns = list(stock_info.columns)
    if stock_info.index.name and stock_info.index.name not in columns:
        columns = [stock_info.index.name, *columns]

    return {
        "stock_pool_path": str(path),
        "stock_pool_sha256": file_sha256(path),
        "stock_pool_rows": int(len(stock_info)),
        "stock_pool_columns": "|".join(str(column) for column in columns),
    }
