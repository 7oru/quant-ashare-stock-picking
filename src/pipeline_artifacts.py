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
    backtest_as_of_date = _backtest_as_of_date(backtest_result)
    ranking_as_of_date = _frame_as_of_date(ranking, backtest_as_of_date)
    allocation_as_of_date = _frame_as_of_date(allocation, ranking_as_of_date)
    ranking_features = ranking.reset_index().rename(columns={"index": "stock_code"})
    allocation_labels = allocation.reset_index().rename(columns={"index": "stock_code"})
    rebalances = backtest_result["rebalances"].copy()
    equity_curve = backtest_result["equity_curve"].reset_index()

    stock_pool = _ensure_as_of_date(stock_pool, ranking_as_of_date)
    ranking_features = _ensure_as_of_date(ranking_features, ranking_as_of_date)
    allocation_labels = _ensure_as_of_date(allocation_labels, allocation_as_of_date)
    rebalances = _ensure_as_of_date(rebalances, "signal_date")
    equity_curve = _ensure_as_of_date(equity_curve, "date")

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
        "as_of_date": ranking_as_of_date,
        "ranking_as_of_date": ranking_as_of_date,
        "backtest_as_of_date": backtest_as_of_date,
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


def write_merged_scores(
    *,
    output_dir: str | Path,
    ranking: pd.DataFrame,
    allocation: pd.DataFrame,
    backtest_result: Dict[str, object],
) -> Dict[str, str]:
    """
    Write the primary result: ranking and backtest evidence merged by stock.

    Sorting is by backtesting_score descending, then by latest ranking ascending.
    Non-selected stocks keep blank backtest fields and sort after selected names.
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    ranking_frame = ranking.reset_index().rename(columns={"index": "stock_code"})
    allocation_frame = allocation[["target_weight", "position_value", "recommendation"]].reset_index()
    allocation_frame = allocation_frame.rename(columns={"index": "stock_code"})
    merged = ranking_frame.merge(allocation_frame, on="stock_code", how="left")
    backtest_as_of_date = _backtest_as_of_date(backtest_result)
    ranking_as_of_date = _frame_as_of_date(ranking, backtest_as_of_date)
    merged = _ensure_as_of_date(merged, ranking_as_of_date)
    if "backtest_as_of_date" not in merged.columns:
        insert_at = 1 if "as_of_date" in merged.columns else 0
        merged.insert(insert_at, "backtest_as_of_date", backtest_as_of_date)

    rebalances = backtest_result["rebalances"]
    if not rebalances.empty and "stock_code" in rebalances.columns:
        aggregations = {
            "signal_date": "count",
            "rank": "mean",
            "target_weight": "mean",
            "composite_score": "mean",
        }
        if "holding_return" in rebalances.columns:
            aggregations["holding_return"] = "mean"
        if "weighted_contribution" in rebalances.columns:
            aggregations["weighted_contribution"] = "sum"

        backtest_scores = rebalances.groupby("stock_code").agg(aggregations).reset_index()
        backtest_scores = backtest_scores.rename(
            columns={
                "signal_date": "backtest_selected_count",
                "rank": "backtest_avg_rank",
                "target_weight": "backtest_avg_weight",
                "composite_score": "backtest_avg_signal_score",
                "holding_return": "backtest_avg_holding_return",
                "weighted_contribution": "backtest_total_contribution",
            }
        )
        if "backtest_avg_holding_return" in backtest_scores.columns:
            backtest_scores["backtesting_score"] = backtest_scores["backtest_avg_holding_return"] * 100
        else:
            backtest_scores["backtesting_score"] = backtest_scores["backtest_avg_signal_score"]
        merged = merged.merge(backtest_scores, on="stock_code", how="left")
    else:
        merged["backtesting_score"] = pd.NA
        merged["backtest_selected_count"] = 0

    if "backtest_selected_count" in merged.columns:
        merged["backtest_selected_count"] = merged["backtest_selected_count"].fillna(0).astype(int)

    merged["_backtesting_sort"] = pd.to_numeric(merged["backtesting_score"], errors="coerce").fillna(-1e18)
    merged["_ranking_sort"] = pd.to_numeric(merged["rank"], errors="coerce").fillna(1e18)
    merged = merged.sort_values(
        ["_backtesting_sort", "_ranking_sort"],
        ascending=[False, True],
    ).drop(columns=["_backtesting_sort", "_ranking_sort"])
    merged.insert(0, "result_rank", range(1, len(merged) + 1))

    output_file = output_path / "ranking_backtest_scores.csv"
    merged.to_csv(output_file, index=False)
    return {"merged_scores": str(output_file)}


def write_reconciliation_data(
    *,
    output_dir: str | Path,
    csv_path: str | Path,
    run_id: str,
    research_paths: Dict[str, str],
    raw_output_dir: str | Path,
    primary_result_paths: Dict[str, str],
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
    output_path.mkdir(parents=True, exist_ok=True)

    stock_pool = pd.read_csv(csv_path, encoding="utf-8-sig")
    ranking_codes = set(ranking.index)
    allocation_codes = set(allocation.index)
    rebalances = backtest_result["rebalances"]
    rebalance_codes = set(rebalances["stock_code"]) if "stock_code" in rebalances.columns else set()

    stock_reconciliation = stock_pool.copy()
    stock_reconciliation = _ensure_as_of_date(stock_reconciliation, _backtest_as_of_date(backtest_result))
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
    pd.DataFrame(checks).pipe(_ensure_as_of_date, _backtest_as_of_date(backtest_result)).to_csv(checks_path, index=False)

    artifact_paths = {
        **{f"primary_{key}": value for key, value in primary_result_paths.items()},
        **{f"research_{key}": value for key, value in research_paths.items()},
        **{f"backtest_{key}": value for key, value in backtest_paths.items()},
        **{f"training_{key}": value for key, value in training_paths.items()},
    }
    raw_path = Path(raw_output_dir)
    for file_path in sorted(raw_path.rglob("*")):
        if file_path.is_file():
            artifact_key = file_path.relative_to(raw_path).with_suffix("").as_posix().replace("/", "_")
            artifact_paths[f"raw_{artifact_key}"] = str(file_path)

    manifest_path = output_path / "file_manifest.csv"
    manifest = _file_manifest_rows(artifact_paths)
    pd.DataFrame(manifest).pipe(_ensure_as_of_date, _backtest_as_of_date(backtest_result)).to_csv(manifest_path, index=False)

    summary_path = output_path / "summary.json"
    summary = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": _backtest_as_of_date(backtest_result),
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
    raw_output_dir: str | Path,
    primary_result_paths: Dict[str, str],
    backtest_paths: Dict[str, str],
    training_paths: Dict[str, str],
    reconciliation_paths: Dict[str, str],
) -> str:
    """
    Write a top-level manifest tying all folders together.
    """
    target = Path(output_path)
    ranking_as_of_date = _primary_result_as_of_date(primary_result_paths) or _manifest_as_of_date(backtest_paths)
    backtest_as_of_date = _manifest_as_of_date(backtest_paths)
    manifest = {
        "schema_version": "1.0",
        "run_id": run_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": ranking_as_of_date,
        "ranking_as_of_date": ranking_as_of_date,
        "backtest_as_of_date": backtest_as_of_date,
        "git_commit": current_git_commit(Path(__file__).resolve().parents[1]),
        "stock_pool": describe_stock_pool(csv_path),
        "primary_results": primary_result_paths,
        "folders": {
            "results": str(target.parent),
            "llm_research": str(Path(research_paths["ledger_dir"])),
            "raw_outputs": str(Path(raw_output_dir)),
            "training_data": str(Path(next(iter(training_paths.values()))).parent),
            "pipeline_reconcilliation": str(Path(next(iter(reconciliation_paths.values()))).parent),
        },
        "artifacts": {
            "primary_results": primary_result_paths,
            "research": research_paths,
            "backtest": backtest_paths,
            "training": training_paths,
            "reconciliation": reconciliation_paths,
        },
    }
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
                "as_of_date": datetime.now().date().isoformat(),
                "artifact": name,
                "path": str(path),
                "sha256": file_sha256(path),
                "bytes": path.stat().st_size,
                "rows": row_count,
            }
        )
    return rows


def _ensure_as_of_date(frame: pd.DataFrame, source: str) -> pd.DataFrame:
    output = frame.copy()
    if "as_of_date" in output.columns:
        return output
    if source in output.columns:
        values = pd.to_datetime(output[source], errors="coerce").dt.strftime("%Y-%m-%d")
        output.insert(0, "as_of_date", values.fillna(""))
    else:
        output.insert(0, "as_of_date", source)
    return output


def _frame_as_of_date(frame: pd.DataFrame, fallback: str) -> str:
    attr_value = frame.attrs.get("as_of_date") if hasattr(frame, "attrs") else None
    if attr_value:
        return str(attr_value)
    if "as_of_date" in frame.columns:
        values = frame["as_of_date"].dropna()
        if not values.empty:
            return str(values.iloc[0])
    return fallback


def _backtest_as_of_date(backtest_result: Dict[str, object]) -> str:
    equity_curve = backtest_result.get("equity_curve")
    if isinstance(equity_curve, pd.DataFrame) and not equity_curve.empty:
        try:
            return pd.Timestamp(equity_curve.index.max()).strftime("%Y-%m-%d")
        except Exception:
            pass
    return datetime.now().date().isoformat()


def _manifest_as_of_date(backtest_paths: Dict[str, str]) -> str:
    summary_path = Path(backtest_paths.get("summary", ""))
    if summary_path.exists():
        try:
            summary = pd.read_csv(summary_path)
            if "as_of_date" in summary.columns and not summary.empty:
                return str(summary["as_of_date"].dropna().iloc[0])
        except Exception:
            pass
    return datetime.now().date().isoformat()


def _primary_result_as_of_date(primary_result_paths: Dict[str, str]) -> Optional[str]:
    primary_path = Path(primary_result_paths.get("merged_scores", ""))
    if primary_path.exists():
        try:
            primary = pd.read_csv(primary_path, nrows=1)
            if "as_of_date" in primary.columns and not primary.empty:
                values = primary["as_of_date"].dropna()
                if not values.empty:
                    return str(values.iloc[0])
        except Exception:
            pass
    return None
