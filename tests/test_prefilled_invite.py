import asyncio
from types import SimpleNamespace

from app.delivery.invite import is_invite_field
from app.orders.repository import OrderRepository
from app.orders.service import OrderService


def test_playerok_invite_field_is_detected():
    assert is_invite_field("Ссылка на Discord сервер")


def test_prefilled_invite_moves_order_to_confirmation(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.json"))
    service = OrderService(repository, object())
    service.register_paid_deal("deal", "chat", "item", "oneMonth", 3)

    # The network inspector is bypassed here; this verifies the state transition.
    message = asyncio.run(service.accept_prefilled_invite("deal", "https://discord.gg/example", "Example"))
    assert "Example" in message
    assert repository.get("deal")["status"] == "waiting_confirmation"
