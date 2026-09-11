import json
import threading
from pathlib import Path


class OrderRepository:
    def __init__(self, path: str) -> None:
        self.path = Path(path)
        if self.path.suffix.lower() != ".json":
            self.path = self.path.with_suffix(".json")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.orders = self._load()

    def _load(self) -> dict[str, dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _save(self) -> None:
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.orders, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)

    def create(self, deal_id: str, chat_id: str, item_id: str, duration: str, quantity: int) -> bool:
        with self.lock:
            if deal_id in self.orders:
                return False
            self.orders[deal_id] = {
                "deal_id": deal_id, "chat_id": chat_id, "item_id": item_id,
                "duration": duration, "quantity": quantity, "status": "waiting_invite",
                "invite_url": None, "api_order_id": None,
                "last_message_id": None,
                "confirmation_at": None,
            }
            self._save()
            return True

    def get(self, deal_id: str) -> dict | None:
        with self.lock:
            row = self.orders.get(deal_id)
            return dict(row) if isinstance(row, dict) else None

    def update(self, deal_id: str, **values: object) -> None:
        with self.lock:
            if deal_id not in self.orders:
                return
            self.orders[deal_id].update(values)
            self._save()

    def waiting_for_chat(self, chat_id: str) -> dict | None:
        with self.lock:
            rows = [row for row in self.orders.values() if row.get("chat_id") == chat_id and row.get("status") == "waiting_invite"]
            return dict(rows[-1]) if rows else None

    def active_confirmations(self) -> list[dict]:
        with self.lock:
            return [dict(row) for row in self.orders.values() if row.get("status") == "waiting_confirmation"]

    def waiting_for_confirmation(self, chat_id: str) -> dict | None:
        with self.lock:
            rows = [row for row in self.orders.values() if row.get("chat_id") == chat_id and row.get("status") == "waiting_confirmation"]
            return dict(rows[-1]) if rows else None
