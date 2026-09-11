from typing import Any
import httpx
import logging

logger = logging.getLogger("neverboost-playerok.neverboost")


class NeverBoostError(RuntimeError):
    def __init__(self, message: str, *, reason: str | None = None, status_code: int | None = None):
        super().__init__(message)
        self.reason = reason
        self.status_code = status_code


def extract_order_id(payload: dict[str, Any]) -> str | None:
    """Извлекает ID заказа из ответа POST /boost в любом из возможных форматов."""
    if not isinstance(payload, dict):
        return None
    candidates = payload.get("id"), payload.get("orderId"), payload.get("order_id")
    nested = payload.get("order")
    if isinstance(nested, dict):
        candidates += nested.get("id"), nested.get("orderId"), nested.get("order_id")
    for candidate in candidates:
        if isinstance(candidate, (str, int)) and str(candidate).strip():
            return str(candidate).strip()
    return None


class NeverBoostClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    def _headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json", "X-API-Key": self.api_key}

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        logger.info("NeverBoost API: %s %s", method, path)
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.request(method, f"{self.base_url}{path}", headers=self._headers(), **kwargs)
        except httpx.HTTPError as exc:
            logger.warning("NeverBoost API: %s %s -> %s", method, path, exc.__class__.__name__)
            raise NeverBoostError(f"NeverBoost API недоступен: {exc.__class__.__name__}") from exc
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        if response.is_error:
            detail = data.get("detail") if isinstance(data, dict) else None
            message = str(detail or "NeverBoost API error")
            reason = (detail or {}).get("reason") if isinstance(detail, dict) else None
            if not reason and isinstance(detail, str):
                for candidate in ("invalid_invite", "limited_invite", "join_request_enabled", "age_restricted", "lookup_failed"):
                    if candidate in detail:
                        reason = candidate
                        break
            logger.info("NeverBoost API: %s %s -> %s (%s)", method, path, response.status_code, message)
            raise NeverBoostError(message, reason=reason, status_code=response.status_code)
        logger.info("NeverBoost API: %s %s -> %s", method, path, response.status_code)
        return data if isinstance(data, dict) else {}

    async def create_order(self, duration: str, url: str, count: int) -> dict[str, Any]:
        logger.info("Создание NeverBoost-заказа: duration=%s count=%d", duration, count)
        return await self._request("POST", "/boost", json={"duration": duration, "url": url, "count": int(count)})

    async def get_order(self, order_id: str) -> dict[str, Any]:
        logger.debug("Проверка NeverBoost-заказа: id=%s", order_id)
        return await self._request("GET", f"/order/{order_id}")

    async def get_stock(self) -> dict[str, Any]:
        return await self._request("GET", "/stock")

    async def get_balance(self) -> dict[str, Any]:
        return await self._request("GET", "/balance")

    async def get_prices(self) -> dict[str, Any]:
        return await self._request("GET", "/prices")
