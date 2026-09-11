from urllib.parse import urlparse


def normalize_proxy(value: str | None) -> str | None:
    value = str(value or "").strip()
    if not value:
        return None
    if "://" in value:
        return value
    # Playerok installer accepts host:port and user:password@host:port.
    return f"http://{value}"
