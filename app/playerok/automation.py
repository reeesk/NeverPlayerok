import asyncio
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger("neverboost-playerok.automation")


class PlayerokAutomation:
    """Best-effort automation built on the same public SDK methods as Universal."""

    def __init__(self, account: Any, store, notify: Callable[[str], Awaitable[None]] | None = None) -> None:
        self.account = account
        self.store = store
        self.notify = notify

    def enabled(self, name: str) -> bool:
        return bool(self.store.get("features", name, default=False))

    async def _notify(self, text: str) -> None:
        if self.enabled("notifications") and self.notify:
            await self.notify(text)

    async def complete_deal(self, deal) -> None:
        if not self.enabled("auto_complete"):
            return
        try:
            from playerokapi.enums import ItemDealStatuses
            await asyncio.to_thread(self.account.update_deal, str(deal.id), ItemDealStatuses.SENT)
            await self._notify(f"✅ Сделка <code>{deal.id}</code> автоматически отмечена как отправленная")
        except Exception:
            logger.exception("Failed to auto-complete deal %s", getattr(deal, "id", "?"))

    async def restore_sold_item(self, deal) -> None:
        if not self.enabled("auto_restore"):
            return
        logger.info("Автовосстановление после продажи: deal=%s", getattr(deal, "id", "?"))
        try:
            from playerokapi.enums import ItemStatuses
            items = await asyncio.to_thread(self.account.get_my_items, statuses=[ItemStatuses.SOLD], count=24)
            source_name = str(getattr(getattr(deal, "item", None), "name", "") or "")
            candidates = getattr(items, "items", items)
            item = next((candidate for candidate in candidates if getattr(candidate, "name", "") == source_name), None)
            if item is None:
                return
            full_item = await asyncio.to_thread(self.account.get_item, item.id)
            priorities = await asyncio.to_thread(self.account.get_item_priority_statuses, full_item.id, full_item.raw_price)
            default = next((status for status in priorities if getattr(status, "price", 0) == 0), priorities[0])
            await asyncio.to_thread(self.account.publish_item, full_item.id, default.id)
            await self._notify(f"♻️ Товар <b>{source_name}</b> восстановлен после продажи")
        except Exception:
            logger.exception("Failed to restore item after deal %s", getattr(deal, "id", "?"))

    async def restore_expired(self) -> None:
        if not self.enabled("auto_restore"):
            return
        try:
            logger.info("Проверка истёкших товаров")
            from playerokapi.enums import ItemStatuses
            items = await asyncio.to_thread(self.account.get_my_items, statuses=[ItemStatuses.EXPIRED], count=100)
            for item in getattr(items, "items", items):
                full_item = await asyncio.to_thread(self.account.get_item, item.id)
                priorities = await asyncio.to_thread(self.account.get_item_priority_statuses, full_item.id, full_item.raw_price)
                default = next((status for status in priorities if getattr(status, "price", 0) == 0), priorities[0])
                await asyncio.to_thread(self.account.publish_item, full_item.id, default.id)
                await asyncio.sleep(0.5)
        except Exception:
            logger.exception("Failed to restore expired items")

    async def bump_all(self) -> None:
        if not self.enabled("auto_bump"):
            return
        try:
            logger.info("Проверка товаров для автоподнятия")
            from playerokapi.enums import ItemStatuses, PriorityTypes
            items = await asyncio.to_thread(self.account.get_my_items, statuses=[ItemStatuses.APPROVED], count=100)
            for item in getattr(items, "items", items):
                priorities = await asyncio.to_thread(self.account.get_item_priority_statuses, item.id, item.raw_price)
                premium = next((status for status in priorities if getattr(status, "type", None) == PriorityTypes.PREMIUM or getattr(status, "price", 0) > 0), None)
                if premium:
                    await asyncio.to_thread(self.account.increase_item_priority_status, item.id, premium.id)
                await asyncio.sleep(0.5)
        except Exception:
            logger.exception("Failed to bump items")

    async def background_loop(self) -> None:
        while True:
            try:
                await self.restore_expired()
                await self.bump_all()
            except Exception:
                logger.exception("Automation loop failed")
            interval = max(int(self.store.get("runtime", "automation_interval", default=3600)), 60)
            logger.info("Следующая проверка автоматизации через %s сек.", interval)
            await asyncio.sleep(interval)
