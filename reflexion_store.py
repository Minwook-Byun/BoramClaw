from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


_WORD_RE = re.compile(r"[0-9A-Za-z가-힣_]+")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _tokens(text: str) -> set[str]:
    return {m.group(0).lower() for m in _WORD_RE.finditer(text or "") if len(m.group(0)) >= 2}


class ReflexionStore:
    def __init__(self, *, workdir: str, file_path: str = "logs/reflexion_cases.jsonl", max_records: int = 5000) -> None:
        self.workdir = Path(workdir).resolve()
        target = Path(file_path)
        if not target.is_absolute():
            target = (self.workdir / target).resolve()
        self.path = target
        self.max_records = max(100, int(max_records))

    def _read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists() or not self.path.is_file():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return []
        rows: list[dict[str, Any]] = []
        for line in lines[-self.max_records :]:
            text = line.strip()
            if not text:
                continue
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                rows.append(parsed)
        return rows

    def _append(self, row: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")

    def add_case(
        self,
        *,
        kind: str,
        input_text: str,
        outcome: str,
        fix: str = "",
        source: str = "runtime",
        severity: str = "info",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = {
            "ts": _utc_now(),
            "type": "case",
            "kind": (kind or "unknown").strip(),
            "source": (source or "runtime").strip(),
            "severity": (severity or "info").strip(),
            "input": (input_text or "").strip(),
            "outcome": (outcome or "").strip(),
            "fix": (fix or "").strip(),
            "metadata": metadata or {},
        }
        self._append(row)
        return row

    def add_feedback(self, *, text: str, source: str = "user") -> dict[str, Any]:
        row = {
            "ts": _utc_now(),
            "type": "feedback",
            "source": source,
            "text": (text or "").strip(),
        }
        self._append(row)
        return row

    def latest(self, count: int = 10) -> list[dict[str, Any]]:
        c = max(1, min(int(count), 200))
        return self._read_all()[-c:]

    def query(self, text: str, top_k: int = 5) -> list[dict[str, Any]]:
        rows = self._read_all()
        q = _tokens(text)
        if not q:
            return rows[-max(1, min(int(top_k), 50)) :]
        scored: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            joined = " ".join(
                [
                    str(row.get("kind", "")),
                    str(row.get("input", "")),
                    str(row.get("outcome", "")),
                    str(row.get("fix", "")),
                    str(row.get("text", "")),
                ]
            )
            t = _tokens(joined)
            if not t:
                continue
            overlap = len(q.intersection(t))
            if overlap <= 0:
                continue
            score = overlap / max(len(q), 1)
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        result: list[dict[str, Any]] = []
        for score, row in scored[: max(1, min(int(top_k), 50))]:
            result.append({"score": round(float(score), 4), **row})
        return result

    def status(self) -> dict[str, Any]:
        rows = self._read_all()
        type_counter: Counter[str] = Counter()
        kind_counter: Counter[str] = Counter()
        for row in rows:
            row_type = str(row.get("type", "")).strip() or "unknown"
            type_counter[row_type] += 1
            kind = str(row.get("kind", "")).strip()
            if kind:
                kind_counter[kind] += 1
        return {
            "path": str(self.path),
            "records": len(rows),
            "types": dict(type_counter),
            "top_kinds": [{"kind": k, "count": c} for k, c in kind_counter.most_common(5)],
        }


def append_self_heal_feedback(*, workdir: str, payload: dict[str, Any], file_path: str = "logs/self_heal_feedback.jsonl") -> None:
    root = Path(workdir).resolve()
    target = Path(file_path)
    if not target.is_absolute():
        target = (root / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    row = {"ts": _utc_now(), **payload}
    with target.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(row, ensure_ascii=False) + "\n")
