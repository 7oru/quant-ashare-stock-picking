"""
Full-pipeline artifact writers.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import pandas as pd

from .results_manager import current_git_commit, describe_stock_pool, file_sha256


def create_run_id(roots: Iterable[str | Path], timestamp: Optional[str] = None) -> str:
    """
    Create a run id that is unique across all artifact roots.
    """
    base = timestamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    candidate = base
    suffix = 1
    root_paths = [Path(root) for root in roots]
    while any((root / candidate).exists() for root in root_paths):
        candidate = f"{base}_{suffix:02d}"
        suffix += 1
    return candidate


def write_training_data(
    *,
    output_dir: str | Path,
    csv_path: str | Path,
    ranking: pd.DataFrame,
    allocation: pd.DataFrame,
    backtest_result: Dict[str, object],
    run_id: str,
) -> Dict[str, str]:
    """
    Persist training-ready snapshots from one full pipeline run.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=False)

    stock_pool = pd.read_csv(csv_path, encoding="utf-8-sig")
    ranking_features = ranking.reset_index().rename(columns={"index": "stock_code"})
    allocation_labels = allocation.reset_index().rename(columns={"index": "stock_code"})
    rebalances = backtest_result["rebalances"].copy()
    equity_curve = backtest_result["equity_curve"].reset_index()

    stock_pool_path = output_path / "stock_pool_snapshot.csv"
    ranking_features_path = output_path / "ranking_features.csv"
    allocation_labels_path = output_path / "allocation_labels.csv"
    rebalance_labels_path = output_path / "rebalance_labels.csv"
    equity_labels_path = output_path / "equity_labels.csv"
    metadata_path = output_path / "metadata.json"

    stock_pool.to_csv(stock_pool_path, index=False)
    ranking_features.to_csv(ranking_features_path, index=False)
    allocation_labels.to_csv(allocation_labels_path, index=False)
    rebalances.to_csv(rebalance_labels_path, index=False)
    equity_curve.to_csv(equity_labels_path, index=False)

    metadata = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": current_git_commit(Path(__file__).resolve().parents[1]),
        "stock_pool": describe_stock_pool(csv_path),
        "rows": {
            "stock_pool_snapshot": int(len(stock_pool)),
            "ranking_features": int(len(ranking_features)),
            "allocation_labels": int(len(allocation_labels)),
            "rebalance_labels": int(len(rebalances)),
            "equity_labels": int(len(equity_curve)),
        },
    }
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "stock_pool_snapshot": str(stock_pool_path),
        "ranking_features": str(ranking_features_path),
        "allocation_labels": str(allocation_labels_path),
        "rebalance_labels": str(rebalance_labels_path),
        "equity_labels": str(equity_labels_path),
        "metadata": str(metadata_path),
    }


def write_reconciliation_data(
    *,
    output_dir: str | Path,
    csv_path: str | Path,
    run_id: str,
    research_paths: Dict[str, str],
    ranking_dir: str | Path,
    backtest_paths: Dict[str, str],
    training_paths: Dict[str, str],
    ranking: pd.DataFrame,
    allocation: pd.DataFrame,
    backtest_result: Dict[str, object],
) -> Dict[str, str]:
    """
    Write run reconciliation files.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=False)

    stock_pool = pd.read_csv(csv_path, encoding="utf-8-sig")
    ranking_codes = set(ranking.index)
    allocation_codes = set(allocation.index)
    rebalances = backtest_result["rebalances"]
    rebalance_codes = set(rebalances["stock_code"]) if "stock_code" in rebalances.columns else set()

    stock_reconciliation = stock_pool.copy()
    stock_reconciliation["in_ranking"] = stock_reconciliation["stock_code"].isin(ranking_codes)
    stock_reconciliation["in_allocation"] = stock_reconciliation["stock_code"].isin(allocation_codes)
    stock_reconciliation["in_backtest_rebalances"] = stock_reconciliation["stock_code"].isin(rebalance_codes)
    stock_reconciliation_path = output_path / "stock_reconciliation.csv"
    stock_reconciliation.to_csv(stock_reconciliation_path, index=False)

    checks = [
        _check("stock_pool_rows", len(stock_pool), len(stock_pool) > 0),
        _check("ranking_rows", len(ranking), len(ranking) > 0),
        _check("allocation_rows", len(allocation), len(allocation) > 0),
        _check("backtest_equity_rows", len(backtest_result["equity_curve"]), len(backtest_result["equity_curve"]) > 0),
        _check("backtest_rebalance_rows", len(rebalances), len(rebalances) > 0),
        _check("training_files", len(training_paths), len(training_paths) > 0),
        _check("research_ledger_files", len(research_paths), len(research_paths) > 0),
    ]
    checks_path = output_path / "run_checks.csv"
    pd.DataFrame(checks).to_csv(checks_path, index=False)

    artifact_paths = {
        **{f"research_{key}": value for key, value in research_paths.items()},
        **{f"backtest_{key}": value for key, value in backtest_paths.items()},
        **{f"training_{key}": value for key, value in training_paths.items()},
    }
    ranking_path = Path(ranking_dir)
    for file_path in sorted(ranking_path.glob("*")):
        if file_path.is_file():
            artifact_paths[f"ranking_{file_path.stem}"] = str(file_path)

    manifest_path = output_path / "file_manifest.csv"
    manifest = _file_manifest_rows(artifact_paths)
    pd.DataFrame(manifest).to_csv(manifest_path, index=False)

    summary_path = output_path / "summary.json"
    summary = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": current_git_commit(Path(__file__).resolve().parents[1]),
        "stock_pool": describe_stock_pool(csv_path),
        "checks_passed": all(row["status"] == "pass" for row in checks),
        "artifact_count": len(manifest),
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return {
        "stock_reconciliation": str(stock_reconciliation_path),
        "run_checks": str(checks_path),
        "file_manifest": str(manifest_path),
        "summary": str(summary_path),
    }


def write_run_manifest(
    *,
    output_path: str | Path,
    run_id: str,
    csv_path: str | Path,
    research_paths: Dict[str, str],
    ranking_dir: str | Path,
    backtest_paths: Dict[str, str],
    training_paths: Dict[str, str],
    reconciliation_paths: Dict[str, str],
) -> str:
    """
    Write a top-level manifest tying all folders together.
    """
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "git_commit": current_git_commit(Path(__file__).resolve().parents[1]),
        "stock_pool": describe_stock_pool(csv_path),
        "folders": {
            "research_ledger": str(Path(research_paths["ledger_dir"])),
            "ranking": str(Path(ranking_dir)),
            "backtest": str(Path(next(iter(backtest_paths.values()))).parent),
            "training_data": str(Path(next(iter(training_paths.values()))).parent),
            "reconciliation": str(Path(next(iter(reconciliation_paths.values()))).parent),
        },
        "artifacts": {
            "research": research_paths,
            "backtest": backtest_paths,
            "training": training_paths,
            "reconciliation": reconciliation_paths,
        },
    }
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return str(target)


def _check(name: str, value: int | float | str, passed: bool) -> Dict[str, object]:
    return {
        "check": name,
        "value": value,
        "status": "pass" if passed else "fail",
    }


def _file_manifest_rows(paths: Dict[str, str]) -> List[Dict[str, object]]:
    rows = []
    for name, path_value in sorted(paths.items()):
        path = Path(path_value)
        if not path.exists() or not path.is_file():
            continue
        row_count = ""
        if path.suffix.lower() == ".csv":
            try:
                row_count = len(pd.read_csv(path))
            except Exception:
                row_count = ""
        rows.append(
            {
                "artifact": name,
                "path": str(path),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
                "rows": row_count,
            }
        )
    return rows
