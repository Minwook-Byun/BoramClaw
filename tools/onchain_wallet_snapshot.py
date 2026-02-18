from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from typing import Any
import urllib.parse
import urllib.request

__version__ = "1.0.0"


TOOL_SPEC = {
    "name": "onchain_wallet_snapshot",
    "description": "Lookup wallet balance/tx count from public blockchain APIs (ETH/BTC).",
    "version": "1.0.0",
    "network_access": True,
    "input_schema": {
        "type": "object",
        "properties": {
            "network": {"type": "string", "enum": ["ethereum", "bitcoin"], "default": "ethereum"},
            "address": {"type": "string", "description": "Wallet address"},
            "include_price": {"type": "boolean", "default": True},
            "currency": {"type": "string", "default": "usd"},
            "timeout_seconds": {"type": "integer", "minimum": 3, "maximum": 45, "default": 15},
        },
        "required": ["address"],
    },
}


def _load_json_object(raw: str) -> dict[str, Any]:
    if not raw.strip():
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("JSON input must be an object.")
    return parsed


def _fetch_json(url: str, timeout_seconds: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "BoramClaw-OnChain/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise RuntimeError("invalid json payload")
    return payload


def _fetch_balance(network: str, address: str, timeout_seconds: int) -> dict[str, Any]:
    if network == "bitcoin":
        url = f"https://api.blockcypher.com/v1/btc/main/addrs/{urllib.parse.quote(address)}"
        payload = _fetch_json(url, timeout_seconds)
        satoshi = int(payload.get("final_balance", 0) or 0)
        balance = satoshi / 100_000_000
        tx_count = int(payload.get("n_tx", 0) or 0)
        symbol = "BTC"
        return {
            "network": "bitcoin",
            "symbol": symbol,
            "address": address,
            "balance": balance,
            "tx_count": tx_count,
            "raw_balance": satoshi,
        }

    url = f"https://api.blockcypher.com/v1/eth/main/addrs/{urllib.parse.quote(address)}/balance"
    payload = _fetch_json(url, timeout_seconds)
    wei = int(payload.get("final_balance", 0) or 0)
    balance = wei / 1_000_000_000_000_000_000
    tx_count = int(payload.get("n_tx", 0) or 0)
    symbol = "ETH"
    return {
        "network": "ethereum",
        "symbol": symbol,
        "address": address,
        "balance": balance,
        "tx_count": tx_count,
        "raw_balance": wei,
    }


def _fetch_price(network: str, currency: str, timeout_seconds: int) -> float | None:
    coin_id = "bitcoin" if network == "bitcoin" else "ethereum"
    query = urllib.parse.urlencode({"ids": coin_id, "vs_currencies": currency})
    url = f"https://api.coingecko.com/api/v3/simple/price?{query}"
    payload = _fetch_json(url, timeout_seconds)
    row = payload.get(coin_id)
    if not isinstance(row, dict):
        return None
    value = row.get(currency)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def run(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    network = str(input_data.get("network", "ethereum")).strip().lower()
    if network not in {"ethereum", "bitcoin"}:
        network = "ethereum"
    address = str(input_data.get("address", "")).strip()
    if not address:
        return {"ok": False, "error": "address is required"}
    include_price = bool(input_data.get("include_price", True))
    currency = str(input_data.get("currency", "usd")).strip().lower() or "usd"
    timeout_seconds = max(3, min(int(input_data.get("timeout_seconds", 15)), 45))

    balance_row = _fetch_balance(network=network, address=address, timeout_seconds=timeout_seconds)
    price = None
    if include_price:
        try:
            price = _fetch_price(network=network, currency=currency, timeout_seconds=timeout_seconds)
        except Exception:
            price = None
    usd_estimate = None
    if price is not None:
        usd_estimate = float(balance_row["balance"]) * price
    ts = datetime.now(timezone.utc).isoformat()
    summary = (
        f"{balance_row['symbol']} 주소 {address} 잔액 {balance_row['balance']:.8f}, "
        f"트랜잭션 {balance_row['tx_count']}건"
    )
    if usd_estimate is not None:
        summary += f", 평가액 약 {usd_estimate:.2f} {currency.upper()}"

    return {
        "ok": True,
        "timestamp": ts,
        "network": balance_row["network"],
        "symbol": balance_row["symbol"],
        "address": address,
        "balance": balance_row["balance"],
        "tx_count": balance_row["tx_count"],
        "price": price,
        "price_currency": currency,
        "estimated_value": usd_estimate,
        "summary": summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="onchain_wallet_snapshot cli")
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
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

