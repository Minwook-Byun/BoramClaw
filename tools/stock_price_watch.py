from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import urllib.parse
import urllib.request
from typing import Any


__version__ = "1.0.0"

TOOL_SPEC = {
    "name": "stock_price_watch",
    "description": "Fetch current stock price and check whether target threshold is reached.",
    "version": "1.0.0",
    "input_schema": {
        "type": "object",
        "properties": {
            "ticker": {"type": "string", "description": "Ticker symbol, e.g. SOXX"},
            "target_price": {"type": "number", "description": "Target price"},
            "direction": {"type": "string", "enum": ["above", "below"], "default": "above"},
        },
        "required": ["ticker"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _fetch_quote(ticker: str) -> dict[str, Any]:
    query = urllib.parse.urlencode({"symbols": ticker})
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?{query}"
    req = urllib.request.Request(url, headers={"User-Agent": "boramclaw-stock-price-watch"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    result = payload.get("quoteResponse", {}).get("result", [])
    if not isinstance(result, list) or not result:
        raise RuntimeError(f"Ticker not found: {ticker}")
    item = result[0]
    if not isinstance(item, dict):
        raise RuntimeError("Invalid quote payload")
    return item


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    ticker = str(input_data.get("ticker", "")).strip().upper()
    if not ticker:
        return {"ok": False, "error": "ticker is required"}

    target_raw = input_data.get("target_price")
    target_price = float(target_raw) if target_raw is not None else None
    direction = str(input_data.get("direction", "above")).strip().lower()
    if direction not in {"above", "below"}:
        direction = "above"

    quote = _fetch_quote(ticker)
    current = quote.get("regularMarketPrice")
    if current is None:
        return {"ok": False, "error": "regularMarketPrice not available", "ticker": ticker}
    current_price = float(current)

    reached = None
    if target_price is not None:
        if direction == "above":
            reached = current_price >= target_price
        else:
            reached = current_price <= target_price

    ts = datetime.now(timezone.utc).isoformat()
    summary = f"{ticker} 현재가 {current_price:.4f}"
    if target_price is not None:
        summary += f", 목표 {direction} {target_price:.4f}, 달성={bool(reached)}"

    return {
        "ok": True,
        "ticker": ticker,
        "current_price": current_price,
        "currency": str(quote.get("currency", "")),
        "target_price": target_price,
        "direction": direction,
        "reached": reached,
        "timestamp": ts,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="stock_price_watch cli")
    parser.add_argument("--tool-spec-json", action="store_true")
    parser.add_argument("--tool-input-json", default="")
    parser.add_argument("--tool-context-json", default="")
    args = parser.parse_args()

    try:
        if args.tool_spec_json:
            print(json.dumps(TOOL_SPEC, ensure_ascii=False))
            return 0
        input_data = _load_json_object(args.tool_input_json)
        context = _load_json_object(args.tool_context_json)
        print(json.dumps(run(input_data, context), ensure_ascii=False, default=str))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=__import__("sys").stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
