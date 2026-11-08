"""Price checks with durable delivery reservations and a completion receipt."""
import base64
import copy
import json
import math
import os
from pathlib import Path
import re
import time
from datetime import datetime, timezone
import requests
from monitor import EXCURSIONS, HEADERS, format_price_change_message

RUNTIME = "data/watchdog/runtime.json"


def now():
    return datetime.now(timezone.utc).isoformat()


class StoreError(Exception):
    pass


class AmbiguousDelivery(Exception):
    pass


class RepositoryState:
    def __init__(self, token, repo, root=Path("."), session=requests):
        if not token or repo != "AntonioSkin/tripster-price-monitor":
            raise StoreError("repository_credentials_missing")
        self.token, self.repo, self.root, self.session = token, repo, Path(root), session
        self.sha, self.saved = None, None

    def request(self, method, payload=None):
        try:
            response = self.session.request(
                method, f"https://api.github.com/repos/{self.repo}/contents/{RUNTIME}",
                headers={"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json",
                         "X-GitHub-Api-Version": "2022-11-28"},
                json=payload, timeout=20, allow_redirects=False)
        except requests.RequestException:
            raise StoreError("repository_request_unconfirmed") from None
        return response

    def load(self):
        response = self.request("GET")
        try:
            if response.status_code == 404:
                state = {
                    "prices": json.loads((self.root / "prices.json").read_text()),
                    "sent_notifications": json.loads((self.root / "sent_notifications.json").read_text()),
                    "pending": {},
                }
            elif response.status_code == 200:
                body = response.json()
                self.sha = body["sha"]
                state = json.loads(base64.b64decode(body["content"]).decode())
                self.saved = copy.deepcopy(state)
            else:
                raise StoreError("repository_state_unavailable")
            if any(not isinstance(state.get(key), dict) for key in ("prices", "sent_notifications", "pending")):
                raise ValueError()
            return state
        except (KeyError, ValueError, OSError, TypeError):
            raise StoreError("repository_state_invalid") from None

    def persist(self, state):
        if self.saved == state:
            return
        payload = {"message": "Persist task 7 delivery state",
                   "content": base64.b64encode((json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode()).decode()}
        if self.sha:
            payload["sha"] = self.sha
        response = self.request("PUT", payload)
        try:
            sha = response.json()["content"]["sha"] if response.status_code in (200, 201) else None
            if not isinstance(sha, str) or not re.fullmatch("[a-f0-9]{40}", sha):
                raise ValueError()
        except (ValueError, KeyError, TypeError):
            raise StoreError("repository_write_unconfirmed") from None
        self.sha, self.saved = sha, copy.deepcopy(state)


def get_price(eid):
    page = f"https://experience.tripster.ru/experience/{eid}/"
    api = f"https://experience.tripster.ru/api/web/v2/experiences/{eid}/"
    with requests.Session() as session:
        landing_status = None
        try:
            landing_status = session.get(page, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=10).status_code
        except requests.RequestException:
            pass
        for attempt in range(3):
            try:
                response = session.get(api, headers={**HEADERS, "Referer": page}, timeout=15, allow_redirects=False)
                if response.status_code in (404, 410) and landing_status in (404, 410):
                    return None  # Checked and no longer available; never substitute a zero price.
                if response.status_code == 200:
                    raw = response.json()["price"]
                    value = raw.get("value")
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                        raise ValueError()
                    if raw.get("currency") != "RUB":
                        raise ValueError()
                    return {key: raw.get(key) for key in
                            ("value", "currency", "unit_string", "value_string", "discount")}
            except (requests.RequestException, ValueError, KeyError, TypeError):
                pass
            if attempt < 2:
                time.sleep(attempt + 1)
    raise RuntimeError("price_read_failed")


def telegram(text):
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not token or not chat:
        return False
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                                 data={"chat_id": chat, "text": text, "parse_mode": "HTML"},
                                 timeout=20, allow_redirects=False)
        body = response.json()
    except (requests.RequestException, ValueError):
        raise AmbiguousDelivery("delivery_result_unknown") from None
    if response.status_code == 200 and body.get("ok") is True:
        return True
    if 400 <= response.status_code < 500 and body.get("ok") is False:
        return False
    raise AmbiguousDelivery("delivery_result_unknown")


def discount_message(excursion, old, price):
    discount, previous = price.get("discount") or {}, old.get("discount") or {}
    eid = excursion["id"]
    key = f"{eid}_discount_{discount.get('value')}_{discount.get('expiration_date')}"
    message = (f"ℹ️ Изменились условия скидки!\n\n<b>Экскурсия:</b> {excursion['title']}\n"
               f"<b>Цена:</b> {price['value']} ₽\n")
    if discount.get("value"):
        message += f"<b>Скидка:</b> {int(discount['value'] * 100)}% (до {discount.get('expiration_date', '?')})\n"
    elif previous.get("value"):
        message += "<b>Скидка снята</b>\n"
    if discount.get("original_price"):
        message += f"<b>Цена без скидки:</b> {discount['original_price']} ₽\n"
    message += f"\n🔗 <a href='https://experience.tripster.ru/experience/{eid}/'>Открыть на Tripster</a>"
    return key, message


def check(store, fetch_price=get_price, send=telegram, excursions=EXCURSIONS):
    state = store.load()
    checked, unavailable, failed, delivery_failed = [], [], [], []
    store_ok = True
    for excursion in excursions:
        eid = str(excursion["id"])
        try:
            price = fetch_price(excursion["id"])
            checked.append(excursion["id"])
            if price is None:
                unavailable.append(excursion["id"])
                continue
            old = state["prices"].get(eid)
            if eid in state["pending"]:
                delivery_failed.append(excursion["id"])
                continue  # A scheduled run also must not replay an ambiguous delivery.
            message, discount_key = None, None
            if old is not None and price["value"] != old["value"]:
                message = format_price_change_message(excursion, old, price)
            elif old is not None and (price.get("discount") or {}) != (old.get("discount") or {}):
                discount_key, message = discount_message(excursion, old, price)
                if discount_key in state["sent_notifications"]:
                    message = None
            if message is not None:
                state["pending"][eid] = {"prepared_at": now(), "price": price, "discount_key": discount_key}
                store.persist(state)  # Durable reservation BEFORE the Telegram POST.
                try:
                    delivered = send(message)
                except AmbiguousDelivery:
                    delivery_failed.append(excursion["id"])
                    continue
                if not delivered:
                    del state["pending"][eid]
                    store.persist(state)
                    delivery_failed.append(excursion["id"])
                    continue
                state["prices"][eid] = price
                if discount_key:
                    state["sent_notifications"][discount_key] = now()
                del state["pending"][eid]
                store.persist(state)  # A failed acknowledgement leaves the durable reservation intact.
            else:
                state["prices"][eid] = price
        except StoreError:
            store_ok = False
            failed.append(excursion["id"])
            break
        except Exception:
            # Never print request exceptions: a Telegram URL can contain the token.
            failed.append(excursion["id"])
    if store_ok:
        try:
            store.persist(state)
        except StoreError:
            store_ok = False
    uncertain = sorted(state["pending"])
    safe = store_ok and not uncertain
    complete = len(checked) == len(excursions) and not failed
    delivered = not delivery_failed and not uncertain
    stamp = now()
    status = {"ok": safe and complete and delivered, "checked_at": stamp,
              "all_prices_checked": complete, "delivery_complete": delivered,
              "recovery_safe": safe, "checked_ids": checked, "unavailable_ids": unavailable,
              "failed_ids": failed, "uncertain_ids": uncertain}
    outputs = {"data/watchdog/status.json": status}
    # Only confirmed repository state is mirrored to the legacy files.
    saved = store.saved or state
    outputs["prices.json"] = saved["prices"]
    outputs["sent_notifications.json"] = saved["sent_notifications"]
    if status["ok"]:
        outputs["data/watchdog/completed.json"] = {**status, "completed_at": stamp}
    return outputs, 0 if status["ok"] else 1


def write_bundle(directory, outputs):
    for name, value in outputs.items():
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)


def main():
    directory = Path(os.environ.get("MONITOR_BUNDLE", "_monitor_bundle"))
    try:
        store = RepositoryState(os.getenv("GITHUB_TOKEN"), os.getenv("GITHUB_REPO"))
        outputs, code = check(store)
    except StoreError:
        outputs, code = {"data/watchdog/status.json": {
            "ok": False, "checked_at": now(), "recovery_safe": False,
            "reason": "repository_state_unavailable"}}, 1
    write_bundle(directory, outputs)
    print(json.dumps(outputs["data/watchdog/status.json"], ensure_ascii=False))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
