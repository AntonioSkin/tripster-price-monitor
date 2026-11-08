import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import requests
from safe_monitor import check, AmbiguousDelivery, StoreError, RepositoryState, get_price
from persist_bundle import validate

TOURS = [{"id": 1, "title": "Test tour"}]


def price(value):
    return {"value": value, "currency": "RUB", "discount": None}


class MemoryStore:
    def __init__(self, state=None, fail_write=None):
        self.remote = copy.deepcopy(state or {"prices": {"1": price(100)}, "sent_notifications": {}, "pending": {}})
        self.saved = copy.deepcopy(self.remote)
        self.writes, self.fail_write = 0, fail_write

    def load(self):
        return copy.deepcopy(self.remote)

    def persist(self, state):
        self.writes += 1
        if self.writes == self.fail_write:
            raise StoreError("write_unconfirmed")
        self.remote = copy.deepcopy(state)
        self.saved = copy.deepcopy(state)


class SafetyTests(unittest.TestCase):
    def test_reservation_is_durable_before_send_and_next_process_does_not_repeat(self):
        store, messages = MemoryStore(), []
        def send(text):
            self.assertIn("1", store.remote["pending"])
            self.assertEqual(store.remote["prices"]["1"]["value"], 100)
            messages.append(text)
            return True
        outputs, code = check(store, lambda _: price(200), send, TOURS)
        self.assertEqual(code, 0)
        self.assertTrue(outputs["data/watchdog/completed.json"]["all_prices_checked"])
        self.assertEqual(store.remote["prices"]["1"]["value"], 200)
        check(MemoryStore(store.remote), lambda _: price(200), send, TOURS)
        self.assertEqual(len(messages), 1)

    def test_ambiguous_delivery_survives_a_new_process_and_blocks_replay(self):
        store = MemoryStore()
        def unknown(_):
            raise AmbiguousDelivery()
        outputs, code = check(store, lambda _: price(200), unknown, TOURS)
        self.assertEqual(code, 1)
        self.assertFalse(outputs["data/watchdog/status.json"]["recovery_safe"])
        self.assertNotIn("data/watchdog/completed.json", outputs)
        sender = Mock(return_value=True)
        outputs, code = check(MemoryStore(store.remote), lambda _: price(200), sender, TOURS)
        sender.assert_not_called()
        self.assertEqual(code, 1)

    def test_failed_acknowledgement_cannot_cause_a_duplicate(self):
        store, sender = MemoryStore(fail_write=2), Mock(return_value=True)
        outputs, code = check(store, lambda _: price(200), sender, TOURS)
        self.assertEqual(code, 1)
        self.assertEqual(outputs["prices.json"]["1"]["value"], 100)
        self.assertIn("1", store.remote["pending"])
        check(MemoryStore(store.remote), lambda _: price(200), sender, TOURS)
        self.assertEqual(sender.call_count, 1)

    def test_known_rejection_keeps_old_price_and_allows_a_safe_retry(self):
        store = MemoryStore()
        outputs, code = check(store, lambda _: price(200), lambda _: False, TOURS)
        self.assertEqual(code, 1)
        self.assertTrue(outputs["data/watchdog/status.json"]["recovery_safe"])
        self.assertEqual(store.remote["prices"]["1"]["value"], 100)
        self.assertEqual(store.remote["pending"], {})
        _, code = check(MemoryStore(store.remote), lambda _: price(200), lambda _: True, TOURS)
        self.assertEqual(code, 0)

    def test_incomplete_reads_never_produce_a_completion_receipt(self):
        def failed(_):
            raise RuntimeError()
        outputs, code = check(MemoryStore(), failed, lambda _: True, TOURS)
        self.assertEqual(code, 1)
        self.assertFalse(outputs["data/watchdog/status.json"]["all_prices_checked"])
        self.assertNotIn("data/watchdog/completed.json", outputs)

    def test_confirmed_removed_listing_is_recorded_without_zeroing_its_price(self):
        outputs, code = check(MemoryStore(), lambda _: None, Mock(), TOURS)
        self.assertEqual(code, 0)
        self.assertEqual(outputs["data/watchdog/status.json"]["unavailable_ids"], [1])
        self.assertEqual(outputs["prices.json"]["1"]["value"], 100)

    def test_each_return_to_a_previous_price_still_notifies(self):
        store, sender = MemoryStore(), Mock(return_value=True)
        for amount in (200, 100, 200):
            _, code = check(store, lambda _, amount=amount: price(amount), sender, TOURS)
            self.assertEqual(code, 0)
        self.assertEqual(sender.call_count, 3)

    def test_repository_error_cannot_silently_reset_the_baseline(self):
        session = Mock()
        session.request.return_value.status_code = 503
        with self.assertRaises(StoreError):
            RepositoryState("test-only", "AntonioSkin/tripster-price-monitor", session=session).load()

    @patch("safe_monitor.time.sleep")
    @patch("safe_monitor.requests.Session")
    def test_api_404_with_a_live_page_is_not_a_successful_price_check(self, factory, _sleep):
        session = factory.return_value.__enter__.return_value
        session.get.side_effect = [Mock(status_code=200)] + [Mock(status_code=404) for _ in range(3)]
        with self.assertRaises(RuntimeError):
            get_price(1)
        session.get.side_effect = [Mock(status_code=404), Mock(status_code=404)]
        self.assertIsNone(get_price(1))

    @patch("safe_monitor.time.sleep")
    @patch("safe_monitor.requests.Session")
    def test_missing_or_zero_price_is_a_failed_read(self, factory, _sleep):
        session = factory.return_value.__enter__.return_value
        for amount in (None, 0, True):
            response = Mock(status_code=200)
            response.json.return_value = {"price": price(amount)}
            session.get.side_effect = [Mock(status_code=200), response, response, response]
            with self.assertRaises(RuntimeError):
                get_price(1)

    def test_writer_rejects_ledger_overwrites_and_accepts_status_only_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "data/watchdog/status.json"
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({"ok": False}))
            self.assertEqual(validate(root), ["data/watchdog/status.json"])
            (root / "data/watchdog/runtime.json").write_text("{}")
            with self.assertRaises(ValueError):
                validate(root)


if __name__ == "__main__":
    unittest.main()
