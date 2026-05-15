import os
from settings import Settings as sett, SettingsFile

CONFIG = SettingsFile(
    name="config",
    path=os.path.join(os.path.dirname(__file__), "module_settings", "config.json"),
    need_restore=True,
    default={
        "api_base_url": "https://api.neverboost.com",
        "api_key": "",
        "auto_refund_on_zero": False,
        "ask_confirm": True,
        "notifications": {
            "delivery_success": True,
            "refund_zero": True,
        },
        "lot_bindings": {}
    }
)

DATA = [CONFIG]


class Settings:
    @staticmethod
    def get(name: str) -> dict:
        return sett.get(name, DATA)

    @staticmethod
    def set(name: str, new: list | dict) -> dict:
        return sett.set(name, new, DATA)
