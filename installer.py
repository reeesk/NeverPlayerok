import json
import os
import subprocess
import sys
from pathlib import Path

from app.settings_store import DEFAULT_CONFIG, SettingsStore


BLUE = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def ask(label: str, default: str = "", secret: bool = False) -> str:
    suffix = f" [{default}]" if default else ""
    value = input(f"{BLUE}{label}{suffix}: {RESET}").strip()
    return value or default


def main() -> None:
    print(f"{BLUE}╔══════════════════════════════════════════╗")
    print("║        NeverBoost Playerok Setup         ║")
    print(f"╚══════════════════════════════════════════╝{RESET}\n")
    store = SettingsStore()
    print("Playerok принимает либо полный cookie string, либо отдельные token и __ddg5_.")
    print("Cookies/token должны быть свежими и получены с тем же IP и User-Agent, что будут в конфиге.\n")
    store.set("playerok", "cookies", value=ask("Playerok cookies (можно оставить пустым)", store.get("playerok", "cookies", default="")))
    store.set("playerok", "token", value=ask("Playerok token (если cookies пустые)", store.get("playerok", "token", default="")))
    store.set("playerok", "ddg5", value=ask("Playerok __ddg5_ (если cookies пустые)", store.get("playerok", "ddg5", default="")))
    store.set("playerok", "user_agent", value=ask("Playerok User-Agent", store.get("playerok", "user_agent", default="")))
    store.set("playerok", "proxy", value=ask("Playerok proxy (пусто если нет)", store.get("playerok", "proxy", default="")))
    store.set("neverboost", "api_key", value=ask("NeverBoost API key", store.get("neverboost", "api_key", default="")))
    store.set("telegram", "token", value=ask("Telegram bot token", store.get("telegram", "token", default="")))
    admins = ask("Telegram admin ID через запятую", ",".join(map(str, store.get("telegram", "admins", default=[]))))
    store.set("telegram", "admins", value=[int(x.strip()) for x in admins.split(",") if x.strip().isdigit()])
    store.set("telegram", "proxy", value=ask("Telegram proxy (пусто если нет)", store.get("telegram", "proxy", default="")))
    print(f"\n{YELLOW}Привязки лотов задаются после установки в Telegram или вручную в data/config.json.{RESET}")
    store.save()
    Path("plugins").mkdir(exist_ok=True)
    Path("logs").mkdir(exist_ok=True)
    Path("data").mkdir(exist_ok=True)
    print(f"\n{GREEN}Конфигурация сохранена в data/config.json{RESET}")
    print("Запуск: python -m app.main")


if __name__ == "__main__":
    main()
