from dataclasses import dataclass
from typing import Protocol
import re
import asyncio


@dataclass(frozen=True)
class PaidDeal:
    deal_id: str
    chat_id: str
    item_id: str
    duration: str
    quantity: int


class PlayerokTransport(Protocol):
    async def send_message(self, chat_id: str, text: str) -> None: ...


class PlayerokEventAdapter:
    """Thin boundary between the real Playerok listener and order business logic."""

    def __init__(self, transport: PlayerokTransport, orders, plugins=None) -> None:
        self.transport = transport
        self.orders = orders
        self.plugins = plugins

    async def on_paid_deal(self, deal: PaidDeal) -> None:
        if self.orders.register_paid_deal(deal.deal_id, deal.chat_id, deal.item_id, deal.duration, deal.quantity):
            await self.transport.send_message(
                deal.chat_id,
                "👋 Спасибо за ваш заказ! Пожалуйста, отправьте ссылку на ваш Discord сервер для буста!\n"
                f"📦 К выдаче: {max(int(deal.quantity), 1)} буст(ов).\n"
                "Пример: discord.gg/neverboost",
            )

    async def on_message(self, deal_id: str, chat_id: str, text: str, proxy: str | None = None) -> None:
        accepted, response = await self.orders.accept_message(deal_id, text, proxy)
        await self.transport.send_message(chat_id, response)
        if accepted:
            task = asyncio.create_task(
                self.orders.wait_for_completion(
                    deal_id,
                    lambda message: self.transport.send_message(chat_id, message),
                )
            )
            task.add_done_callback(self._log_task_error)

    @staticmethod
    def _log_task_error(task: asyncio.Task) -> None:
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            import logging
            logging.getLogger("neverboost-playerok.orders").error(
                "Ошибка мониторинга заказа: %s", exc.__class__.__name__
            )

    @staticmethod
    def binding_for_deal(deal, bindings: dict[str, dict]) -> tuple[str, dict] | None:
        item = getattr(deal, "item", None)
        item_id = str(getattr(item, "id", "") or "")
        item_name = str(getattr(item, "name", "") or "").lower()
        for binding_id, binding in bindings.items():
            if not isinstance(binding, dict):
                continue
            title = str(binding.get("item_title", "") or "").lower()
            if str(binding_id) == item_id or (title and (title in item_name or item_name in title)):
                return str(binding_id), binding
        # Some Playerok events contain a shortened item object without a name.
        # A configured title can still identify the only configured lot.
        if len(bindings) == 1:
            binding_id, binding = next(iter(bindings.items()))
            if isinstance(binding, dict):
                return str(binding_id), binding
        return None
