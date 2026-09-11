from typing import Any
import httpx
import logging

logger = logging.getLogger("neverboost-playerok.neverboost")


class NeverBoostError(RuntimeError):
    def __init__(self, message: str, *, reason: str | None = None):
        super().__init__(message)
        self.reason = reason


class NeverBoostClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key.strip()

    def _headers(self, idempotency_key: str | None = None) -> dict[str, str]:
        headers = {"Accept": "application/json", "X-API-Key": self.api_key}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        logger.info("NeverBoost API: %s %s", method, path)
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(method, f"{self.base_url}{path}", headers=self._headers(kwargs.pop("idempotency_key", None)), **kwargs)
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
            raise NeverBoostError(message, reason=reason)
        logger.info("NeverBoost API: %s %s -> %s", method, path, response.status_code)
        return data if isinstance(data, dict) else {}

    async def create_order(self, order_id: str, duration: str, invite_url: str, count: int) -> dict[str, Any]:
        logger.info("Создание NeverBoost-заказа: id=%s duration=%s count=%d", order_id, duration, count)
        return await self._request(
            "POST", "/boost",
            json={"order_id": order_id, "duration": duration, "url": invite_url, "count": count},
            idempotency_key=order_id,
        )

    async def get_order(self, order_id: str) -> dict[str, Any]:
        logger.debug("Проверка NeverBoost-заказа: id=%s", order_id)
        return await self._request("GET", f"/order/{order_id}")

    async def get_stock(self) -> dict[str, Any]:
        return await self._request("GET", "/stock")

    async def get_balance(self) -> dict[str, Any]:
        return await self._request("GET", "/balance")
