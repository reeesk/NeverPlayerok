from app.delivery.invite import extract_invite
from app.delivery.inspector import inspect_invite
import asyncio
import logging
from typing import Awaitable, Callable

from app.neverboost.client import NeverBoostClient, NeverBoostError
from app.orders.repository import OrderRepository

logger = logging.getLogger("neverboost-playerok.orders")


ERRORS = {
    "invalid_invite": "Ссылка недействительна или удалена.",
    "limited_invite": "Срок действия инвайта должен быть не менее 24 часов, а лимит использований не менее 25.",
    "join_request_enabled": "На сервере включён вход по заявкам. Отключите заявки и отправьте новую ссылку.",
    "age_restricted": "18+ серверы не поддерживаются.",
    "lookup_failed": "Не удалось проверить Discord-инвайт. Попробуйте ещё раз позже.",
}


class OrderService:
    def __init__(self, repository: OrderRepository, neverboost: NeverBoostClient) -> None:
        self.repository = repository
        self.neverboost = neverboost

    def register_paid_deal(self, deal_id: str, chat_id: str, item_id: str, duration: str, quantity: int) -> bool:
        return self.repository.create(deal_id, chat_id, item_id, duration, quantity)

    async def accept_message(self, deal_id: str, text: str, proxy: str | None = None) -> tuple[bool, str]:
        order = self.repository.get(deal_id)
        if order is None:
            logger.warning("Сообщение для неизвестного заказа: %s", deal_id)
            return False, "Активный заказ не найден."
        if order["status"] == "waiting_confirmation":
            new_invite = extract_invite(text)
            if new_invite:
                invite = new_invite
                inspection = await inspect_invite(invite, proxy)
                if not inspection.valid:
                    return False, "Ссылка недействительна или сервер недоступен для проверки."
                if inspection.join_requests:
                    return False, "На сервере включён вход по заявкам. Отключите заявки и отправьте новую ссылку."
            elif text.strip().lower() in {"да", "да, выдавайте", "yes", "y"}:
                invite = extract_invite(order.get("invite_url", ""))
                if invite is None:
                    return False, "Отправьте Discord-ссылку в формате discord.gg/example."
            else:
                return False, "Напишите «Да», чтобы подтвердить сервер, или отправьте другую Discord-ссылку."
        elif order["status"] != "waiting_invite":
            return False, "Этот заказ уже обрабатывается."
        else:
            invite = extract_invite(text)
            if invite is None:
                logger.info("Заказ #%s: в сообщении нет Discord-инвайта", deal_id)
                return False, "Отправьте Discord-ссылку в формате discord.gg/example."
            inspection = await inspect_invite(invite, proxy)
            if not inspection.valid:
                logger.info("Заказ #%s: Discord-инвайт не прошёл проверку", deal_id)
                return False, "Ссылка недействительна или сервер недоступен для проверки."
            if inspection.join_requests:
                logger.info("Заказ #%s: на сервере включены заявки", deal_id)
                return False, "На сервере включён вход по заявкам. Отключите заявки и отправьте новую ссылку."
        api_order_id = f"playerok-{deal_id}"
        try:
            await self.neverboost.create_order(api_order_id, order["duration"], invite.url, order["quantity"])
        except NeverBoostError as exc:
            return False, ERRORS.get(exc.reason or "", str(exc))
        self.repository.update(deal_id, status="processing", invite_url=invite.url, api_order_id=api_order_id)
        logger.info("Заказ #%s переведён в processing, api_order_id=%s", deal_id, api_order_id)
        return True, "Заказ на выдачу бустов создан. Проверяю результат выдачи."

    async def accept_prefilled_invite(self, deal_id: str, invite_url: str, server_name: str) -> str | None:
        order = self.repository.get(deal_id)
        if order is None or order["status"] != "waiting_invite":
            return None
        self.repository.update(deal_id, status="waiting_confirmation", invite_url=invite_url, server_name=server_name)
        return f"✅ Нашёл Discord-сервер: <b>{server_name}</b>.\nВыдавать бусты на этот сервер? Ответьте: <b>Да</b> или отправьте другую ссылку."

    async def wait_for_completion(
        self,
        deal_id: str,
        notify: Callable[[str], Awaitable[None]],
        *,
        attempts: int = 120,
        delay: float = 5,
    ) -> None:
        order = self.repository.get(deal_id)
        if order is None or not order["api_order_id"]:
            return
        api_order_id = str(order["api_order_id"])
        for _ in range(attempts):
            try:
                payload = await self.neverboost.get_order(api_order_id)
            except NeverBoostError:
                await asyncio.sleep(delay)
                continue
            data = payload.get("order", payload)
            status = str(data.get("status", "")).lower() if isinstance(data, dict) else ""
            if status not in {"completed", "partially_completed", "failed"}:
                await asyncio.sleep(delay)
                continue
            boosted = int(data.get("boosted", 0) or 0)
            requested = int(data.get("requested", order["quantity"]) or order["quantity"])
            self.repository.update(deal_id, status=status)
            logger.info("Заказ #%s завершён со статусом %s: %d/%d", deal_id, status, boosted, requested)
            if status == "completed":
                await notify("Бусты успешно выданы. Пожалуйста, подтвердите выполнение сделки.")
            elif status == "partially_completed":
                await notify(f"Заказ выполнен частично: выдано {boosted} из {requested} бустов.")
            else:
                await notify("Не удалось выдать бусты. Обратитесь к продавцу для решения вопроса.")
            return
