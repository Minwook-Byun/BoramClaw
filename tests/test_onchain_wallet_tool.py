from __future__ import annotations

import unittest

from tools import onchain_wallet_snapshot


class TestOnchainWalletTool(unittest.TestCase):
    def test_run_ethereum(self) -> None:
        onchain_wallet_snapshot._fetch_balance = lambda network, address, timeout_seconds: {  # type: ignore[method-assign]
            "network": "ethereum",
            "symbol": "ETH",
            "address": address,
            "balance": 1.5,
            "tx_count": 7,
            "raw_balance": 1500000000000000000,
        }
        onchain_wallet_snapshot._fetch_price = lambda network, currency, timeout_seconds: 3000.0  # type: ignore[method-assign]
        out = onchain_wallet_snapshot.run(
            {"network": "ethereum", "address": "0xabc", "include_price": True},
            {},
        )
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("network"), "ethereum")
        self.assertEqual(out.get("tx_count"), 7)
        self.assertEqual(out.get("estimated_value"), 4500.0)


if __name__ == "__main__":
    unittest.main()

