from dataclasses import dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    playerok_cookies: str
    playerok_user_agent: str
    neverboost_api_key: str
    database_path: str = "data/orders.sqlite3"
    neverboost_url: str = "https://api.neverboost.com"
    poll_interval: int = 5
    lot_bindings: dict[str, dict] | None = None
    plugins_dir: str = "plugins"
    playerok_proxy: str = ""
    telegram_token: str = ""
    telegram_proxy: str = ""
    automation_interval: int = 3600

    @classmethod
    def from_json(cls, path: str = "data/config.json") -> "Settings":
        file = Path(path)
        if not file.exists():
            return cls.from_env()
        data = json.loads(file.read_text(encoding="utf-8"))
        playerok = data.get("playerok", {})
        neverboost = data.get("neverboost", {})
        runtime = data.get("runtime", {})
        return cls(
            playerok_cookies=str(playerok.get("cookies", "")),
            playerok_user_agent=str(playerok.get("user_agent", "")),
            neverboost_api_key=str(neverboost.get("api_key", "")),
            database_path=str(runtime.get("orders_file", "data/orders.json")),
            neverboost_url=str(neverboost.get("url", "https://api.neverboost.com")).rstrip("/"),
            poll_interval=max(int(runtime.get("poll_interval", 5)), 1),
            lot_bindings=data.get("lot_bindings", {}) if isinstance(data.get("lot_bindings", {}), dict) else {},
            plugins_dir=str(runtime.get("plugins_dir", "plugins")),
            playerok_proxy=str(playerok.get("proxy", "")),
            telegram_token=str(data.get("telegram", {}).get("token", "")),
            telegram_proxy=str(data.get("telegram", {}).get("proxy", "")),
            automation_interval=max(int(runtime.get("automation_interval", 3600)), 60),
        )

    @classmethod
    def from_env(cls) -> "Settings":
        bindings_raw = os.getenv("LOT_BINDINGS", "{}")
        try:
            bindings = json.loads(bindings_raw)
        except json.JSONDecodeError:
            bindings = {}
        return cls(
            playerok_cookies=os.getenv("PLAYEROK_COOKIES", ""),
            playerok_user_agent=os.getenv("PLAYEROK_USER_AGENT", ""),
            neverboost_api_key=os.getenv("NEVERBOOST_API_KEY", ""),
            database_path=os.getenv("DATABASE_PATH", "data/orders.sqlite3"),
            neverboost_url=os.getenv("NEVERBOOST_URL", "https://api.neverboost.com").rstrip("/"),
            poll_interval=max(int(os.getenv("POLL_INTERVAL", "5")), 1),
            lot_bindings=bindings if isinstance(bindings, dict) else {},
            plugins_dir=os.getenv("PLUGINS_DIR", "plugins"),
            playerok_proxy=os.getenv("PLAYEROK_PROXY", ""),
            telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
            telegram_proxy=os.getenv("TELEGRAM_PROXY", ""),
        )
