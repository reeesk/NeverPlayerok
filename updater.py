from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path


REPOSITORY = "reeesk/NeverPlayerok"
BRANCH = "main"
ROOT = Path(__file__).resolve().parent
PRESERVED = {".git", ".venv", "data", "plugins", "logs", "__pycache__"}


def latest_commit() -> str:
    url = f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}"
    request = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "NeverPlayerok-Updater"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return str(json.load(response)["sha"])


def current_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def update_available() -> tuple[bool, str | None, str | None]:
    current = current_commit()
    latest = latest_commit()
    return bool(current and latest and current != latest), current, latest


def install_update() -> str:
    archive_url = f"https://github.com/{REPOSITORY}/archive/refs/heads/{BRANCH}.zip"
    with tempfile.TemporaryDirectory(prefix="neverplayerok-update-") as temporary:
        archive = Path(temporary) / "update.zip"
        urllib.request.urlretrieve(archive_url, archive)
        extracted = Path(temporary) / "extracted"
        with zipfile.ZipFile(archive) as package:
            package.extractall(extracted)
        source_dirs = [path for path in extracted.iterdir() if path.is_dir()]
        if len(source_dirs) != 1:
            raise RuntimeError("Неверная структура архива обновления")
        source = source_dirs[0]
        for path in source.iterdir():
            if path.name in PRESERVED:
                continue
            destination = ROOT / path.name
            if destination.exists():
                shutil.rmtree(destination) if destination.is_dir() else destination.unlink()
            shutil.copytree(path, destination) if path.is_dir() else shutil.copy2(path, destination)
    return latest_commit()


def restart() -> None:
    launcher = ROOT / "restart.bat"
    if os.name == "nt" and launcher.exists():
        subprocess.Popen(["cmd", "/c", str(launcher)], cwd=ROOT, creationflags=subprocess.CREATE_NEW_CONSOLE)
    else:
        subprocess.Popen([sys.executable, "-m", "app.main"], cwd=ROOT)


if __name__ == "__main__":
    changed, current, latest = update_available()
    if not changed:
        print("Обновлений нет.")
        raise SystemExit(0)
    print(f"Доступно обновление: {current[:8] if current else '?'} -> {latest[:8] if latest else '?'}")
    install_update()
    print("Обновление установлено. Перезапустите бота командой restart.bat.")
