"""
结果输出目录管理
Result output directory helpers
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional


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
