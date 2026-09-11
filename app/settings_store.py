import json
import threading
from pathlib import Path
from typing import Any


DEFAULT_CONFIG = {
    "playerok": {"cookies": "", "user_agent": "", "proxy": "", "timeout": 30},
    "neverboost": {"api_key": "", "url": "https://api.neverboost.com"},
    "telegram": {"token": "", "proxy": "", "admins": []},
    "features": {
        "auto_restore": True,
        "auto_complete": False,
        "auto_bump": False,
        "notifications": True,
    },
    "lot_bindings": {},
    "runtime": {"orders_file": "data/orders.json", "plugins_dir": "plugins", "poll_interval": 5, "automation_interval": 3600},
}


class SettingsStore:
    def __init__(self, path: str = "data/config.json") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            return self._merge(DEFAULT_CONFIG, loaded if isinstance(loaded, dict) else {})
        except (FileNotFoundError, json.JSONDecodeError):
            return json.loads(json.dumps(DEFAULT_CONFIG))

    @staticmethod
    def _merge(base: dict, extra: dict) -> dict:
        result = json.loads(json.dumps(base))
        for key, value in extra.items():
            if isinstance(value, dict) and isinstance(result.get(key), dict):
                result[key] = SettingsStore._merge(result[key], value)
            else:
                result[key] = value
        return result

    def save(self) -> None:
        with self.lock:
            temp = self.path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.path)

    def get(self, *keys: str, default: Any = None) -> Any:
        value: Any = self.data
        for key in keys:
            if not isinstance(value, dict):
                return default
            value = value.get(key, default)
        return value

    def set(self, *keys: str, value: Any) -> None:
        target = self.data
        for key in keys[:-1]:
            target = target.setdefault(key, {})
        target[keys[-1]] = value
        self.save()
