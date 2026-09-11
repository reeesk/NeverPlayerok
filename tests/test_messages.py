from app.main import order_invite_message


def test_order_invite_message_contains_quantity_and_example():
    message = order_invite_message(3)
    assert "Спасибо за ваш заказ" in message
    assert "К выдаче: 3 буст(ов)" in message
    assert "discord.gg/neverboost" in message
