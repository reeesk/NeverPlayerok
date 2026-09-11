import asyncio

import app.orders.service as service_module
from app.delivery.inspector import InviteInspection
from app.neverboost.client import extract_order_id
from app.orders.repository import OrderRepository
from app.orders.service import OrderService


class FakeNeverBoost:
    async def create_order(self, duration, url, count):
        return {"id": "api-1234567890"}

    async def get_order(self, order_id):
        return {"order": {"id": order_id, "status": "completed", "boosted": 2, "requested": 2}}


def _fake_inspection(invite, proxy=None):
    async def runner(invite, proxy=None):
        return InviteInspection(True, "Test Server")
    return runner


def test_order_is_idempotent(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.json"))
    service = OrderService(repository, FakeNeverBoost())
    assert service.register_paid_deal("deal-1", "chat", "item", "oneMonth", 2)
    assert not service.register_paid_deal("deal-1", "chat", "item", "oneMonth", 2)


def test_invalid_invite_does_not_create_api_order(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.json"))
    service = OrderService(repository, FakeNeverBoost())
    service.register_paid_deal("deal-2", "chat", "item", "oneMonth", 2)
    accepted, message = asyncio.run(service.accept_message("deal-2", "not a link"))
    assert not accepted
    assert "Discord-ссылку" in message


def test_server_order_id_is_stored(tmp_path, monkeypatch):
    monkeypatch.setattr(service_module, "inspect_invite", _fake_inspection(None))
    repository = OrderRepository(str(tmp_path / "orders.json"))
    service = OrderService(repository, FakeNeverBoost())
    service.register_paid_deal("deal-3", "chat", "item", "oneMonth", 2)
    accepted, _ = asyncio.run(service.accept_message("deal-3", "discord.gg/example"))
    assert accepted
    order = repository.get("deal-3")
    assert order["api_order_id"] == "api-1234567890"
    assert order["status"] == "processing"


def test_extract_order_id_supports_response_shapes():
    assert extract_order_id({"id": "api-1"}) == "api-1"
    assert extract_order_id({"order": {"id": "api-2"}}) == "api-2"
    assert extract_order_id({"orderId": "api-3"}) == "api-3"
    assert extract_order_id({"detail": "nothing"}) is None
