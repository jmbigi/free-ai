import unittest
from process import process_transactions

class TestProcessTransactions(unittest.TestCase):

    def test_empty(self):
        self.assertEqual(process_transactions([]), {"balance": 0, "valid_transactions": []})

    def test_only_deposits(self):
        txs = [
            {"type": "deposit", "amount": 10},
            {"type": "deposit", "amount": 20},
            {"type": "deposit", "amount": 30},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 60, "valid_transactions": txs},
        )

    def test_only_insufficient_withdrawals(self):
        txs = [
            {"type": "withdraw", "amount": 10},
            {"type": "withdraw", "amount": 5},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 0, "valid_transactions": []},
        )

    def test_mixed_valid_and_invalid(self):
        txs = [
            {"type": "deposit", "amount": 100},
            {"type": "withdraw", "amount": 40},
            {"type": "withdraw", "amount": 70},
            {"type": "deposit", "amount": 20},
            {"type": "unknown", "amount": 5},
        ]
        expected = [
            {"type": "deposit", "amount": 100},
            {"type": "withdraw", "amount": 40},
            {"type": "deposit", "amount": 20},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 80, "valid_transactions": expected},
        )

    def test_exact_withdraw(self):
        txs = [
            {"type": "deposit", "amount": 50},
            {"type": "withdraw", "amount": 50},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 0, "valid_transactions": txs},
        )

    def test_withdraw_zero(self):
        txs = [
            {"type": "deposit", "amount": 10},
            {"type": "withdraw", "amount": 0},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 10, "valid_transactions": txs},
        )

    def test_unknown_type_ignored(self):
        txs = [
            {"type": "deposit", "amount": 10},
            {"type": "transfer", "amount": 5},
            {"type": "withdraw", "amount": 3},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": 7, "valid_transactions": [
                {"type": "deposit", "amount": 10},
                {"type": "withdraw", "amount": 3},
            ]},
        )

    def test_negative_amount(self):
        txs = [
            {"type": "deposit", "amount": -5},
        ]
        self.assertEqual(
            process_transactions(txs),
            {"balance": -5, "valid_transactions": txs},
        )


if __name__ == "__main__":
    unittest.main()
