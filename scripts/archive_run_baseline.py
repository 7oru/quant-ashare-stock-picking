#!/usr/bin/env python3
"""
Archive compact, reviewable summaries from a completed full-pipeline run.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.results_manager import file_sha256


def main() -> None:
    parser = argparse.ArgumentParser(description="Archive a compact baseline snapshot from a completed run")
    parser.add_argument("--run-id", required=True, help="Run id under results/ and audits/")
    parser.add_argument("--name", default=None, help="Stable baseline folder name. Defaults to the run id")
    parser.add_argument("--output-root", default="docs/baselines", help="Tracked baseline archive root")
    parser.add_argument("--top-n", type=int, default=10, help="Number of primary result rows to archive")
    parser.add_argument("--force", action="store_true", help="Replace an existing baseline folder")
    args = parser.parse_args()

    archive_run_baseline(
        run_id=args.run_id,
        name=args.name or args.run_id,
        output_root=Path(args.output_root),
        top_n=args.top_n,
        force=args.force,
    )


def archive_run_baseline(*, run_id: str, name: str, output_root: Path, top_n: int, force: bool) -> Path:
    results_dir = Path("results") / run_id
    audits_dir = Path("audits") / run_id
    if not results_dir.exists():
        raise FileNotFoundError(f"Missing results directory: {results_dir}")
    if not audits_dir.exists():
        raise FileNotFoundError(f"Missing audits directory: {audits_dir}")

    target_dir = output_root / name
    if target_dir.exists():
        if not force:
            raise FileExistsError(f"Baseline already exists: {target_dir}; pass --force to replace it")
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    manifest_path = results_dir / "run_manifest.json"
    primary_scores_path = results_dir / "ranking_backtest_scores.csv"
    reconciliation_dir = audits_dir / "pipeline_reconcilliation"
    raw_outputs_dir = reconciliation_dir / "raw_outputs"
    backtest_dir = raw_outputs_dir / "backtest"

    required_files = {
        "run_manifest": manifest_path,
        "primary_scores": primary_scores_path,
        "reconciliation_summary": reconciliation_dir / "summary.json",
        "run_checks": reconciliation_dir / "run_checks.csv",
        "backtest_summary": backtest_dir / "backtest_summary.csv",
        "backtest_run_metadata": backtest_dir / "backtest_run_metadata.json",
    }
    optional_files = {
        "ranking_data_sources_json": raw_outputs_dir / "ranking_data_sources.json",
        "ranking_data_sources_csv": raw_outputs_dir / "ranking_data_sources.csv",
    }

    for label, path in required_files.items():
        if not path.exists():
            raise FileNotFoundError(f"Missing required {label}: {path}")

    copied = {}
    for label, path in {**required_files, **optional_files}.items():
        if path.exists():
            copied[label] = _copy_artifact(path, target_dir)

    primary = pd.read_csv(primary_scores_path)
    top_scores_path = target_dir / f"top_{top_n}_ranking_backtest_scores.csv"
    primary.head(top_n).to_csv(top_scores_path, index=False)
    copied[f"top_{top_n}_primary_scores"] = _artifact_record(top_scores_path)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    backtest_summary = pd.read_csv(required_files["backtest_summary"])
    run_checks = pd.read_csv(required_files["run_checks"])
    summary = {
        "schema_version": "1.0",
        "baseline_name": name,
        "run_id": run_id,
        "archived_at": datetime.now().isoformat(timespec="seconds"),
        "source_git_commit": manifest.get("git_commit", ""),
        "as_of_date": manifest.get("as_of_date", ""),
        "stock_pool": manifest.get("stock_pool", {}),
        "checks_passed": bool((run_checks["status"] == "pass").all()),
        "strategy": _summary_row(backtest_summary, "strategy"),
        "universe_equal_weight": _summary_row(backtest_summary, "universe_equal_weight"),
        "artifacts": copied,
    }
    summary_path = target_dir / "baseline_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme_path = target_dir / "README.md"
    readme_path.write_text(_baseline_readme(summary, top_n), encoding="utf-8")

    print(f"Archived baseline: {target_dir}")
    return target_dir


def _copy_artifact(source: Path, target_dir: Path) -> Dict[str, object]:
    destination = target_dir / source.name
    shutil.copy2(source, destination)
    return _artifact_record(destination)


def _artifact_record(path: Path) -> Dict[str, object]:
    record = {
        "path": str(path),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }
    if path.suffix.lower() == ".csv":
        try:
            record["rows"] = int(len(pd.read_csv(path)))
        except Exception:
            record["rows"] = None
    return record


def _summary_row(frame: pd.DataFrame, name: str) -> Dict[str, object]:
    if "name" not in frame.columns:
        return {}
    rows = frame.loc[frame["name"] == name]
    if rows.empty:
        return {}
    row = rows.iloc[0]
    return {key: _json_value(value) for key, value in row.to_dict().items()}


def _json_value(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        return value.item()
    return value


def _baseline_readme(summary: Dict[str, object], top_n: int) -> str:
    strategy = summary.get("strategy", {})
    return (
        f"# Baseline: {summary['baseline_name']}\n\n"
        f"- run_id: `{summary['run_id']}`\n"
        f"- as_of_date: `{summary.get('as_of_date', '')}`\n"
        f"- source_git_commit: `{summary.get('source_git_commit', '')}`\n"
        f"- checks_passed: `{summary.get('checks_passed')}`\n"
        f"- strategy_total_return: `{strategy.get('total_return')}`\n"
        f"- strategy_max_drawdown: `{strategy.get('max_drawdown')}`\n\n"
        f"This folder stores compact, tracked summaries from the ignored run artifact directories. "
        f"The top {top_n} primary rows are in `top_{top_n}_ranking_backtest_scores.csv`.\n"
    )


if __name__ == "__main__":
    main()
