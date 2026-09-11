from app.delivery.invite import extract_invite


def test_extracts_discord_gg_invite():
    assert extract_invite("Вот discord.gg/AbC-123").url == "https://discord.gg/AbC-123"


def test_extracts_discord_com_invite():
    assert extract_invite("https://discord.com/invite/test-code").code == "test-code"


def test_rejects_unrelated_text():
    assert extract_invite("привет") is None
