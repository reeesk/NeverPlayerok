from app.orders.repository import OrderRepository


def test_active_confirmations_returns_waiting_orders(tmp_path):
    repository = OrderRepository(str(tmp_path / "orders.json"))
    repository.create("deal", "chat", "item", "oneMonth", 1)
    repository.update("deal", status="waiting_confirmation")
    assert repository.active_confirmations()[0]["deal_id"] == "deal"
