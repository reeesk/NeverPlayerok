import importlib.util
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("neverboost-playerok.plugins")


@dataclass
class Plugin:
    name: str
    module: Any
    path: Path
    enabled: bool = True


class PluginManager:
    """Compatibility loader for Universal-style Python plugins."""

    def __init__(self, directory: str = "plugins") -> None:
        self.directory = Path(directory)
        self.plugins: list[Plugin] = []

    def load(self) -> list[Plugin]:
        self.directory.mkdir(parents=True, exist_ok=True)
        for path in sorted(self.directory.glob("*.py")):
            if path.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(f"nb_plugin_{path.stem}", path)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.plugins.append(Plugin(str(getattr(module, "NAME", path.stem)), module, path))
            except Exception:
                logger.exception("Cannot load plugin %s", path)
        return self.plugins

    async def dispatch(self, event_name: str, *args: Any) -> None:
        for plugin in self.plugins:
            if not plugin.enabled:
                continue
            handler_map = getattr(plugin.module, "PLAYEROK_EVENT_HANDLERS", {})
            handlers = handler_map.get(event_name, [])
            if not handlers:
                for key, candidate in handler_map.items():
                    if getattr(key, "name", "") == event_name or str(getattr(key, "value", "")) == event_name:
                        handlers = candidate
                        break
            # Universal plugins use EventTypes enum keys; string keys are also accepted.
            if not handlers:
                handlers = getattr(plugin.module, "EVENT_HANDLERS", {}).get(event_name, [])
            for handler in handlers:
                result = handler(*args)
                if inspect.isawaitable(result):
                    await result
