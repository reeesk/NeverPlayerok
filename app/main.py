import asyncio
import logging
from threading import Thread

from dotenv import load_dotenv

from app.config import Settings
from app.neverboost.client import NeverBoostClient
from app.orders.repository import OrderRepository
from app.orders.service import OrderService
from app.playerok.adapter import PaidDeal, PlayerokEventAdapter
from app.playerok.automation import PlayerokAutomation
from app.plugins.manager import PluginManager
from app.settings_store import SettingsStore
from app.telegram_panel import TelegramPanel

logger = logging.getLogger("neverboost-playerok")


def order_invite_message(quantity: int) -> str:
    quantity = max(int(quantity), 1)
    return (
        "👋 Спасибо за ваш заказ! Пожалуйста, отправьте ссылку на ваш Discord сервер для буста!\n"
        f"📦 К выдаче: {quantity} буст(ов).\n"
        "Пример: discord.gg/neverboost"
    )


async def main() -> None:
    load_dotenv()
    store = SettingsStore()
    settings = Settings.from_json()
    if not settings.neverboost_api_key:
        raise RuntimeError("NEVERBOOST_API_KEY is required")
    repository = OrderRepository(settings.database_path)
    service = OrderService(repository, NeverBoostClient(settings.neverboost_url, settings.neverboost_api_key))

    from playerokapi.account import Account
    from playerokapi.exceptions import UnauthorizedError
    from playerokapi.listener.events import EventTypes
    from playerokapi.listener.listener import EventListener

    account = Account(
        token=settings.playerok_token or None,
        ddg5=settings.playerok_ddg5,
        cookies=settings.playerok_cookies,
        user_agent=settings.playerok_user_agent,
        proxy=settings.playerok_proxy or None,
        requests_timeout=30,
    )
    try:
        account = account.get()
    except UnauthorizedError as exc:
        raise RuntimeError(
            "Playerok не авторизовал аккаунт. Проверьте data/config.json: "
            "укажите свежие cookies с token и __ddg5_ либо отдельные token/ddg5. "
            "Cookies должны соответствовать User-Agent и прокси."
        ) from exc

    class Transport:
        async def send_message(self, chat_id: str, text: str) -> None:
            await asyncio.to_thread(account.send_message, chat_id=chat_id, text=text)

        async def notify_admins(self, text: str) -> None:
            for admin_id in store.get("telegram", "admins", default=[]):
                await asyncio.to_thread(account.send_message, chat_id=str(admin_id), text=text)

    plugins = PluginManager(settings.plugins_dir)
    plugins.load()
    adapter = PlayerokEventAdapter(Transport(), service, plugins)
    automation = PlayerokAutomation(account, store, lambda text: panel_notify(text))
    async def panel_notify(text: str) -> None:
        await telegram_panel.notify_admins(text)
    telegram_panel = TelegramPanel(store, repository, settings.neverboost_url)
    telegram_task = asyncio.create_task(telegram_panel.run())
    automation_task = asyncio.create_task(automation.background_loop())

    async def handle(event) -> None:
        if event.type is EventTypes.NEW_DEAL:
            deal = event.deal
            binding_match = adapter.binding_for_deal(deal, settings.lot_bindings or {})
            if not binding_match:
                return
            _, binding = binding_match
            duration = str(binding.get("duration", "oneMonth"))
            quantity = max(int(binding.get("boosts_per_unit", 1) or 1), 1)
            if service.register_paid_deal(str(deal.id), str(event.chat.id), str(deal.item.id), duration, quantity):
                await adapter.transport.send_message(str(event.chat.id), order_invite_message(quantity))
            await automation.complete_deal(deal)
            await plugins.dispatch(event.type.name, adapter, event)
        elif event.type is EventTypes.NEW_MESSAGE:
            message = event.message
            if getattr(message.user, "id", None) == account.id:
                return
            row = repository.waiting_for_chat(str(event.chat.id))
            if row:
                await adapter.on_message(row["deal_id"], str(event.chat.id), str(getattr(message, "text", "") or ""))
            await plugins.dispatch(event.type.name, adapter, event)
        elif event.type is EventTypes.ITEM_PAID:
            await automation.restore_sold_item(event.deal)
            await plugins.dispatch(event.type.name, adapter, event)
        elif event.type is EventTypes.DEAL_STATUS_CHANGED:
            if str(getattr(getattr(event.deal, "status", None), "name", "")).upper() == "ROLLED_BACK":
                repository.update(str(event.deal.id), status="cancelled")
            await plugins.dispatch(event.type.name, adapter, event)

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def listen() -> None:
        try:
            for event in EventListener(account).listen():
                asyncio.run_coroutine_threadsafe(queue.put(event), loop)
        except Exception:
            logger.exception("Playerok listener stopped")

    Thread(target=listen, name="playerok-listener", daemon=True).start()
    try:
        while True:
            await handle(await queue.get())
    finally:
        telegram_task.cancel()
        automation_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
