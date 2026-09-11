from app.orders.repository import OrderRepository


def test_orders_are_saved_as_json(tmp_path):
    path = tmp_path / "data" / "orders.json"
    repo = OrderRepository(str(path))
    assert repo.create("deal", "chat", "item", "oneMonth", 2)
    assert '"deal"' in path.read_text(encoding="utf-8")
    reopened = OrderRepository(str(path))
    assert reopened.get("deal")["status"] == "waiting_invite"
