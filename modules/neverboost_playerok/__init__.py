from core.modules import Module
from playerokapi.enums import EventTypes

from .plbot.handlers import on_new_deal, on_new_message, on_deal_status_changed
from .tgbot import router
from .meta import *

_module: Module = None


def set_module(new: Module):
    global _module
    _module = new


def get_module() -> Module | None:
    return _module


async def on_module_enabled(module: Module):
    set_module(module)


BOT_EVENT_HANDLERS = {
    "ON_MODULE_ENABLED": [on_module_enabled],
}
PLAYEROK_EVENT_HANDLERS = {
    EventTypes.NEW_DEAL: [on_new_deal],
    EventTypes.NEW_MESSAGE: [on_new_message],
    EventTypes.DEAL_STATUS_CHANGED: [on_deal_status_changed],
}
TELEGRAM_BOT_ROUTERS = [router]
