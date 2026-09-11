import asyncio

from app.neverboost.client import NeverBoostError
from app.orders.repository import OrderRepository
from app.orders.service import OrderService


class FakeNeverBoost:
    async def create_order(self, order_id, duration, invite_url, count):
        return {"order": {"id": order_id}}


def test_order_is_idempotent(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.sqlite3"))
    service = OrderService(repository, FakeNeverBoost())
    assert service.register_paid_deal("deal-1", "chat", "item", "oneMonth", 2)
    assert not service.register_paid_deal("deal-1", "chat", "item", "oneMonth", 2)


def test_invalid_invite_does_not_create_api_order(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.sqlite3"))
    service = OrderService(repository, FakeNeverBoost())
    service.register_paid_deal("deal-2", "chat", "item", "oneMonth", 2)
    accepted, message = asyncio.run(service.accept_message("deal-2", "not a link"))
    assert not accepted
    assert "Discord-ссылку" in message
