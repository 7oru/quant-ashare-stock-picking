"""
Research evidence ledger helpers.
"""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import pandas as pd

from .results_manager import (
    create_timestamped_result_dir,
    current_git_commit,
    describe_stock_pool,
)


def load_candidates_json(path: str | Path) -> Dict[str, Any]:
    """
    Load a candidate payload.

    Accepted shapes:
    - {"title": "...", "notes": "...", "candidates": [...]}
    - [...]
    """
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    if isinstance(payload, list):
        return {"candidates": payload}
    if isinstance(payload, dict):
        payload.setdefault("candidates", [])
        return payload
    raise ValueError("Candidate JSON must be a list or an object with a candidates list")


def candidates_from_stock_pool(csv_path: str | Path) -> List[Dict[str, Any]]:
    """
    Build snapshot candidates from the current stock pool.

    This is a fallback for full-pipeline runs where no LLM evidence payload is
    provided. It preserves the pipeline's stock-pool state without pretending
    that external news sources were supplied.
    """
    stock_pool = pd.read_csv(csv_path, encoding="utf-8-sig")
    candidates = []
    for row in stock_pool.to_dict(orient="records"):
        recommended_logic = str(row.get("recommended_logic", "") or "")
        candidates.append(
            {
                "stock_code": row.get("stock_code", ""),
                "stock_name": row.get("stock_name", ""),
                "decision": "pool_member",
                "sector": row.get("sector", ""),
                "sub_sector": row.get("sub_sector", ""),
                "ai_exposure": row.get("ai_exposure", ""),
                "confidence": "snapshot_only",
                "news_heat": "",
                "upstream_depth": "",
                "supply_chain_path": "",
                "evidence_summary": recommended_logic,
                "rejection_reason": "",
                "evidence": [
                    {
                        "title": "ai_stock_pool.csv snapshot",
                        "url": "",
                        "published_at": "",
                        "source_type": "stock_pool_snapshot",
                        "claim": recommended_logic,
                        "confidence": "snapshot_only",
                    }
                ],
            }
        )
    return candidates


def create_research_ledger(
    *,
    news_window_start: str,
    news_window_end: str,
    stock_pool_path: str = "ai_stock_pool.csv",
    output_root: str = "audits",
    title: str = "",
    notes: str = "",
    candidates: Optional[List[Dict[str, Any]]] = None,
    timestamp: Optional[str] = None,
) -> Dict[str, str]:
    """
    Create a folder-based research ledger.
    """
    candidates = candidates or []
    ledger_dir = create_timestamped_result_dir(output_root, timestamp=timestamp)
    created_at = datetime.now().isoformat(timespec="seconds")

    ledger = {
        "schema_version": "1.0",
        "title": title,
        "created_at": created_at,
        "generated_by": "ai-upstream-stock-research",
        "git_commit": current_git_commit(Path(__file__).resolve().parents[1]),
        "news_window": {
            "start": news_window_start,
            "end": news_window_end,
        },
        "stock_pool": describe_stock_pool(stock_pool_path),
        "summary": _summary(candidates),
        "notes": notes,
        "candidates": candidates,
    }

    ledger_path = ledger_dir / "ledger.json"
    candidates_path = ledger_dir / "candidates.csv"
    sources_path = ledger_dir / "sources.csv"
    notes_path = ledger_dir / "notes.md"

    ledger_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _write_candidates_csv(candidates_path, candidates)
    _write_sources_csv(sources_path, candidates)
    _write_notes(notes_path, title, news_window_start, news_window_end, notes)

    return {
        "ledger_dir": str(ledger_dir),
        "ledger": str(ledger_path),
        "candidates": str(candidates_path),
        "sources": str(sources_path),
        "notes": str(notes_path),
    }


def _summary(candidates: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    rows = list(candidates)
    decisions = [str(row.get("decision", "watchlist")).lower() for row in rows]
    return {
        "candidate_count": len(rows),
        "accepted_count": decisions.count("accepted"),
        "rejected_count": decisions.count("rejected"),
        "watchlist_count": decisions.count("watchlist"),
        "pool_member_count": decisions.count("pool_member"),
    }


def _write_candidates_csv(path: Path, candidates: List[Dict[str, Any]]) -> None:
    fields = [
        "stock_code",
        "stock_name",
        "decision",
        "sector",
        "sub_sector",
        "ai_exposure",
        "confidence",
        "news_heat",
        "upstream_depth",
        "supply_chain_path",
        "evidence_summary",
        "rejection_reason",
        "source_count",
        "source_urls",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            evidence = _evidence_items(candidate)
            writer.writerow(
                {
                    "stock_code": candidate.get("stock_code", ""),
                    "stock_name": candidate.get("stock_name", ""),
                    "decision": candidate.get("decision", "watchlist"),
                    "sector": candidate.get("sector", ""),
                    "sub_sector": candidate.get("sub_sector", ""),
                    "ai_exposure": candidate.get("ai_exposure", ""),
                    "confidence": candidate.get("confidence", ""),
                    "news_heat": candidate.get("news_heat", ""),
                    "upstream_depth": candidate.get("upstream_depth", ""),
                    "supply_chain_path": _join_path(candidate.get("supply_chain_path", "")),
                    "evidence_summary": candidate.get("evidence_summary", ""),
                    "rejection_reason": candidate.get("rejection_reason", ""),
                    "source_count": len(evidence),
                    "source_urls": ";".join(str(item.get("url", "")) for item in evidence if item.get("url")),
                }
            )


def _write_sources_csv(path: Path, candidates: List[Dict[str, Any]]) -> None:
    fields = [
        "stock_code",
        "stock_name",
        "source_title",
        "source_url",
        "published_at",
        "source_type",
        "claim",
        "confidence",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            for source in _evidence_items(candidate):
                writer.writerow(
                    {
                        "stock_code": candidate.get("stock_code", ""),
                        "stock_name": candidate.get("stock_name", ""),
                        "source_title": source.get("title", ""),
                        "source_url": source.get("url", ""),
                        "published_at": source.get("published_at", ""),
                        "source_type": source.get("source_type", ""),
                        "claim": source.get("claim", ""),
                        "confidence": source.get("confidence", ""),
                    }
                )


def _write_notes(path: Path, title: str, start: str, end: str, notes: str) -> None:
    lines = [
        f"# {title or 'Research Ledger'}",
        "",
        f"- News window: {start} to {end}",
        "- Canonical file: `ledger.json`",
        "- Candidate index: `candidates.csv`",
        "- Source index: `sources.csv`",
        "",
        "## Notes",
        "",
        notes or "",
    ]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _evidence_items(candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = candidate.get("evidence") or candidate.get("evidence_items") or []
    return evidence if isinstance(evidence, list) else []


def _join_path(value: Any) -> str:
    if isinstance(value, list):
        return " -> ".join(str(item) for item in value)
    return str(value or "")
