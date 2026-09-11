from types import SimpleNamespace

from app.playerok.adapter import PlayerokEventAdapter


def test_single_binding_works_with_short_item_event():
    deal = SimpleNamespace(item=SimpleNamespace(id="event-item", name=""))
    result = PlayerokEventAdapter.binding_for_deal(deal, {"configured-item": {"duration": "oneMonth"}})
    assert result[0] == "configured-item"
