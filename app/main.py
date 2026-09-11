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
from app.delivery.invite import extract_invite, is_invite_field
from app.delivery.inspector import inspect_invite
from app.plugins.manager import PluginManager
from app.settings_store import SettingsStore
from app.telegram_panel import TelegramPanel
from app.logging_setup import configure_logging
from app.network import normalize_proxy

logger = logging.getLogger("neverboost-playerok")


def order_invite_message(quantity: int) -> str:
    quantity = max(int(quantity), 1)
    return (
        "👋 Спасибо за ваш заказ! Пожалуйста, отправьте ссылку на ваш Discord сервер для буста!\n"
        f"📦 К выдаче: {quantity} буст(ов).\n"
        "Пример: discord.gg/neverboost"
    )


async def main() -> None:
    configure_logging()
    logger.info("========== NeverPlayerok запускается ==========")
    load_dotenv()
    store = SettingsStore()
    settings = Settings.from_json()
    if not settings.neverboost_api_key:
        raise RuntimeError("NEVERBOOST_API_KEY is required")
    logger.info("Конфигурация загружена: лотов=%d, plugins=%s, interval=%ss", len(store.get("lot_bindings", default={})), settings.plugins_dir, settings.poll_interval)
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
        proxy=normalize_proxy(settings.playerok_proxy),
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
    logger.info("Playerok авторизован: username=%s, account_id=%s", account.username, account.id)

    class Transport:
        async def send_message(self, chat_id: str, text: str) -> None:
            await asyncio.to_thread(account.send_message, chat_id=chat_id, text=text)

        async def notify_admins(self, text: str) -> None:
            for admin_id in store.get("telegram", "admins", default=[]):
                await asyncio.to_thread(account.send_message, chat_id=str(admin_id), text=text)

    plugins = PluginManager(settings.plugins_dir)
    loaded_plugins = plugins.load()
    logger.info("Плагины загружены: %d", len(loaded_plugins))
    adapter = PlayerokEventAdapter(Transport(), service, plugins)
    automation = PlayerokAutomation(account, store, lambda text: panel_notify(text))
    async def panel_notify(text: str) -> None:
        await telegram_panel.notify_admins(text)
    telegram_panel = TelegramPanel(store, repository, settings.neverboost_url)
    telegram_task = asyncio.create_task(telegram_panel.run())
    automation_task = asyncio.create_task(automation.background_loop())
    logger.info("Telegram-панель и автоматизация запущены")

    for row in list(repository.orders.values()):
        if row.get("status") == "processing" and str(row.get("api_order_id") or "").startswith("playerok-"):
            repository.update(row["deal_id"], status="untracked")
            logger.warning("Заказ #%s помечен untracked: старый локальный api_order_id не отслеживается API", row["deal_id"])
            try:
                await telegram_panel.notify_admins(
                    f"⚠️ Заказ <code>{row['deal_id']}</code> был создан в старом формате API и не отслеживается. "
                    "Проверьте выдачу бустов вручную в личном кабинете NeverBoost."
                )
            except Exception as exc:
                logger.warning("Уведомление об untracked-заказе не отправлено: %s", exc.__class__.__name__)

    async def handle(event) -> None:
        logger.info("Playerok event: %s, chat_id=%s", getattr(event.type, "name", event.type), getattr(event.chat, "id", "?"))
        if event.type is EventTypes.NEW_DEAL or event.type is EventTypes.ITEM_PAID:
            deal = event.deal
            if event.type is EventTypes.NEW_DEAL:
                binding_match = adapter.binding_for_deal(deal, store.get("lot_bindings", default={}))
                if not binding_match:
                    logger.warning("Пропущена сделка %s: не найдена привязка лота (item_id=%s, name=%r)", deal.id, getattr(getattr(deal, "item", None), "id", None), getattr(getattr(deal, "item", None), "name", None))
                    return
                _, binding = binding_match
                duration = str(binding.get("duration", "oneMonth"))
                quantity = max(int(binding.get("boosts_per_unit", 1) or 1), 1)
                if service.register_paid_deal(str(deal.id), str(event.chat.id), str(getattr(deal.item, "id", "")), duration, quantity):
                    logger.info("Заказ #%s зарегистрирован: duration=%s, quantity=%d", deal.id, duration, quantity)
                    prefilled = None
                    has_invite_field = False
                    for field in getattr(deal, "obtaining_fields", None) or []:
                        if is_invite_field(getattr(field, "label", "")):
                            has_invite_field = True
                            candidate = extract_invite(getattr(field, "value", "") or "")
                            if candidate:
                                inspection = await inspect_invite(candidate, normalize_proxy(settings.playerok_proxy))
                                if inspection.valid and not inspection.join_requests:
                                    prefilled = await service.accept_prefilled_invite(str(deal.id), candidate.url, inspection.server_name or "Discord-сервер")
                            break
                    if prefilled:
                        await adapter.transport.send_message(str(event.chat.id), prefilled)
                    elif not has_invite_field:
                        await adapter.transport.send_message(str(event.chat.id), order_invite_message(quantity))
                else:
                    logger.info("Заказ #%s уже существует, повторно не создаём", deal.id)
            else:
                # ITEM_PAID is the reliable payment event. It may arrive even
                # when the preceding NEW_DEAL payload had incomplete item data.
                if repository.get(str(deal.id)) is None:
                    binding_match = adapter.binding_for_deal(deal, store.get("lot_bindings", default={}))
                    if binding_match:
                        _, binding = binding_match
                        duration = str(binding.get("duration", "oneMonth"))
                        quantity = max(int(binding.get("boosts_per_unit", 1) or 1), 1)
                        if service.register_paid_deal(str(deal.id), str(event.chat.id), str(getattr(deal.item, "id", "")), duration, quantity):
                            await adapter.transport.send_message(str(event.chat.id), order_invite_message(quantity))
                    else:
                        logger.warning("ITEM_PAID %s получен, но привязка лота не найдена", deal.id)
                await automation.restore_sold_item(deal)
            await plugins.dispatch(event.type.name, adapter, event)
        elif event.type is EventTypes.NEW_MESSAGE:
            message = event.message
            if getattr(message.user, "id", None) == account.id:
                return
            message_deal = getattr(getattr(message, "deal", None), "id", None)
            row = repository.get(str(message_deal)) if message_deal else None
            row = row or repository.waiting_for_confirmation(str(event.chat.id)) or repository.waiting_for_chat(str(event.chat.id))
            if row:
                logger.info("Сообщение покупателя связано с заказом #%s", row["deal_id"])
                await adapter.on_message(row["deal_id"], str(event.chat.id), str(getattr(message, "text", "") or ""), normalize_proxy(settings.playerok_proxy))
            else:
                logger.warning("Сообщение покупателя %s не связано с ожидающей сделкой (chat_id=%s)", getattr(message, "id", "?"), event.chat.id)
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
    logger.info("Playerok listener запущен")
    try:
        while True:
            await handle(await queue.get())
    finally:
        telegram_task.cancel()
        automation_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
