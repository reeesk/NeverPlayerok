from app.network import normalize_proxy


def test_proxy_without_scheme_gets_http_scheme():
    assert normalize_proxy("127.0.0.1:8080") == "http://127.0.0.1:8080"


def test_proxy_with_scheme_is_preserved():
    assert normalize_proxy("socks5://127.0.0.1:1080") == "socks5://127.0.0.1:1080"
