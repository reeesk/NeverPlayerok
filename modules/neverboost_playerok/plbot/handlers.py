from __future__ import annotations

import json
import logging
import re
import time
import uuid
from datetime import datetime
from threading import Lock, Thread
from typing import TYPE_CHECKING

import requests
from playerokapi.enums import ItemDealStatuses
from playerokapi.listener.events import DealStatusChangedEvent, NewDealEvent, NewMessageEvent

from ..data import Data as data
from ..meta import NAME, PREFIX
from ..settings import Settings as sett

if TYPE_CHECKING:
    from plbot.playerokbot import PlayerokBot

logger = logging.getLogger(f"{NAME}.playerok")
requests.packages.urllib3.disable_warnings()  # type: ignore[attr-defined]

_PENDING_LOCK = Lock()

ORDER_MESSAGES = {
    "ru": (
        "👋 Спасибо за заказ! Отправьте ссылку на ваш Discord-сервер для буста.\n"
        "Пример: discord.gg/neverboost"
    ),
    "en": (
        "👋 Thanks for your order! Send your Discord server invite link for boosting.\n"
        "Example: discord.gg/neverboost"
    ),
}

BUYER_TEXTS = {
    "ru": {
        "invalid": "❌ Не вижу корректной Discord-ссылки. Отправьте в формате: discord.gg/neverboost",
        "bad": "❌ Ссылка недействительна или истекла. Отправьте новую ссылку.",
        "requests_on": "❌ На сервере включён вход по заявкам. Отключите заявки и отправьте новую ссылку.",
        "api_fail": "❌ Не удалось создать заказ на выдачу бустов. Попробуйте снова.",
        "order_created": "🚀 Заказ создан. Айди: {api_order_id}",
        "status_completed": "✅ Бусты успешно выданы. Спасибо за заказ!",
        "status_partial": "⚠️ Заказ выполнен частично: {boosted}/{requested}.",
        "status_failed_refund": "❌ Бусты не начислены. Сделка возвращена.",
        "status_failed_no_refund": "⏳ Сейчас нету бустов. Повторная попытка через 1 час.",
        "status_wait_cancelled_refund": "😔 Заказ отменен, т.к. сделка возвращена.",
        "please_confirm": "🙏 Подтвердите заказ в Playerok кнопкой «Подтвердить заказ».",
        "manual_only": "⏳ Автовыдача сейчас недоступна. Ожидайте, продавец выдаст бусты вручную.",
        "status_no_orders": "ℹ️ Нет данных по вашим последним заказам.",
        "status_response": (
            "📡 Статус вашего последнего API-заказа\n\n"
            "• Deal: #{deal_id}\n"
            "• API ID: {api_order_id}\n"
            "• Статус: {status}\n"
            "• Выдано: {boosted}/{requested}"
        ),
        "status_waiting_retry": (
            "⏳ Ваш заказ ожидает повторной попытки\n\n"
            "• Deal: #{deal_id}\n"
            "• Статус: нету бустов на API\n"
            "• Повтор через: {minutes} мин."
        ),
        "stock_response": (
            "📦 Текущий сток бустов\n\n"
            "• 1 месяц: {one_month}\n"
            "• 3 месяца: {three_month}"
        ),
        "retry_too_early": "⏳ Повторная попытка доступна через {minutes} мин.",
        "retry_missing_invite": "❌ Сначала отправьте Discord-ссылку приглашения.",
        "retry_started": "🔄 Пробую выдать бусты повторно...",
    }
}


class NeverBoostApiClient:
    def __init__(self, api_base_url: str, api_key: str):
        self.api_base_url = (api_base_url or "https://api.neverboost.com").rstrip("/")
        self.api_key = (api_key or "").strip()

    def _request(self, method: str, endpoint: str, payload: dict | None = None) -> tuple[bool, dict]:
        try:
            resp = requests.request(
                method=method,
                url=f"{self.api_base_url}{endpoint}",
                headers={"Accept": "application/json", "X-API-Key": self.api_key},
                json=payload if payload is not None else None,
                timeout=15,
                verify=False,
            )
            body = {}
            try:
                body = resp.json() if resp.content else {}
            except Exception:
                body = {}
            return resp.ok, body if isinstance(body, dict) else {}
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
            return False, {}

    def create_boost_order(self, order_id: str, duration: str, invite_url: str, count: int) -> tuple[bool, dict]:
        return self._request(
            "POST",
            "/boost",
            {
                "order_id": order_id,
                "duration": duration,
                "url": invite_url,
                "count": int(count),
            },
        )

    def get_order(self, order_id: str) -> tuple[bool, dict]:
        return self._request("GET", f"/order/{order_id}")


def _cfg() -> dict:
    cfg = sett.get("config")
    if not isinstance(cfg, dict):
        return {}
    return cfg


def _save_cfg(cfg: dict) -> None:
    sett.set("config", cfg)


def _api_client() -> NeverBoostApiClient | None:
    cfg = _cfg()
    key = str(cfg.get("api_key", "") or "").strip()
    if not key:
        return None
    return NeverBoostApiClient(str(cfg.get("api_base_url", "https://api.neverboost.com") or "https://api.neverboost.com"), key)


def _buyer_text(locale: str, key: str, **kwargs) -> str:
    lang = "en" if locale == "en" else "ru"
    text = BUYER_TEXTS.get(lang, BUYER_TEXTS["ru"]).get(key, "")
    return text.format(**kwargs) if kwargs else text


def _extract_invite_code(text: str) -> str | None:
    if not text:
        return None
    patterns = (
        r"(?:https?://)?discord\.gg/([A-Za-z0-9-]+)",
        r"(?:https?://)?discord(?:app)?\.com/invite/([A-Za-z0-9-]+)",
    )
    for p in patterns:
        m = re.search(p, text, flags=re.IGNORECASE)
        if m:
            return m.group(1).strip()
    stripped = text.strip()
    if re.fullmatch(r"[A-Za-z0-9-]{2,}", stripped):
        return stripped
    return None


def _fetch_invite_data(invite_code: str) -> dict | None:
    url = f"https://discord.com/api/v9/invites/{invite_code}?with_counts=true"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
        if r.status_code != 200:
            return None
        payload = r.json()
        return payload if isinstance(payload, dict) else None
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
        return None


def _is_join_requests_enabled(invite_code: str) -> bool:
    payload = _fetch_invite_data(invite_code)
    if not payload:
        return False
    features = payload.get("guild", {}).get("features", [])
    return isinstance(features, list) and "MEMBER_VERIFICATION_MANUAL_APPROVAL" in features


def _normalize_title(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^0-9a-zа-яё]+", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _resolve_binding(deal) -> tuple[str, dict] | tuple[None, None]:
    cfg = _cfg()
    bindings = cfg.get("lot_bindings", {})
    if not isinstance(bindings, dict) or not bindings:
        return None, None

    item = getattr(deal, "item", None)
    item_name = str(getattr(item, "name", "") or "").strip()

    n_item_name = _normalize_title(item_name)
    candidates = []
    for lot_id, row in bindings.items():
        if not isinstance(row, dict):
            continue
        row_title = _normalize_title(str(row.get("item_title", "") or str(lot_id) or ""))
        if not row_title:
            continue
        if row_title == n_item_name or row_title in n_item_name or n_item_name in row_title:
            candidates.append((str(lot_id), row))

    if len(candidates) == 1:
        return candidates[0]

    if len(bindings) == 1:
        only_key = next(iter(bindings.keys()))
        row = bindings.get(only_key)
        if isinstance(row, dict):
            return str(only_key), row

    return None, None


def _pending_get() -> dict:
    rows = data.get("pending_invites")
    return rows if isinstance(rows, dict) else {}


def _pending_set(rows: dict) -> None:
    data.set("pending_invites", rows)


def _pending_upsert(chat_id: str, payload: dict) -> None:
    with _PENDING_LOCK:
        rows = _pending_get()
        rows[str(chat_id)] = payload
        _pending_set(rows)


def _pending_patch(chat_id: str, patch: dict) -> dict | None:
    with _PENDING_LOCK:
        rows = _pending_get()
        cur = rows.get(str(chat_id), {})
        if not isinstance(cur, dict):
            cur = {}
        cur.update(patch)
        rows[str(chat_id)] = cur
        _pending_set(rows)
        return cur


def _pending_pop(chat_id: str) -> dict | None:
    with _PENDING_LOCK:
        rows = _pending_get()
        val = rows.pop(str(chat_id), None)
        _pending_set(rows)
        return val if isinstance(val, dict) else None


def _pending_pop_by_deal_id(deal_id: str) -> bool:
    if not deal_id:
        return False
    removed = False
    with _PENDING_LOCK:
        rows = _pending_get()
        for key, row in list(rows.items()):
            if not isinstance(row, dict):
                continue
            if str(row.get("deal_id", "") or "").strip() == str(deal_id).strip():
                rows.pop(key, None)
                removed = True
        if removed:
            _pending_set(rows)
    return removed


def _pending_get_one(chat_id: str) -> dict | None:
    with _PENDING_LOCK:
        row = _pending_get().get(str(chat_id))
        return row if isinstance(row, dict) else None


def _last_orders_get() -> dict:
    rows = data.get("last_api_orders_by_buyer")
    return rows if isinstance(rows, dict) else {}


def _last_orders_set(rows: dict) -> None:
    data.set("last_api_orders_by_buyer", rows)


def _last_order_set_for_buyer(buyer_username: str, payload: dict) -> None:
    key = str(buyer_username or "").strip().lower()
    if not key:
        return
    rows = _last_orders_get()
    current = rows.get(key)
    if isinstance(current, list):
        items = [i for i in current if isinstance(i, dict)]
    elif isinstance(current, dict):
        items = [current]
    else:
        items = []
    items.append(payload)
    rows[key] = items[-10:]
    _last_orders_set(rows)


def _last_order_get_for_buyer(buyer_username: str) -> dict | None:
    key = str(buyer_username or "").strip().lower()
    if not key:
        return None
    row = _last_orders_get().get(key)
    if isinstance(row, dict):
        return row
    if isinstance(row, list):
        items = [i for i in row if isinstance(i, dict)]
        if items:
            return items[-1]
    return None


def _last_orders_list_for_buyer(buyer_username: str) -> list[dict]:
    key = str(buyer_username or "").strip().lower()
    if not key:
        return []
    row = _last_orders_get().get(key)
    if isinstance(row, dict):
        return [row]
    if isinstance(row, list):
        return [i for i in row if isinstance(i, dict)]
    return []


def _append_sale(deal_id: str, requested: int, boosted: int, gross: float, api_spent: float) -> None:
    rows = data.get("sales")
    rows = rows if isinstance(rows, list) else []
    if any(str(r.get("deal_id", "")) == str(deal_id) for r in rows if isinstance(r, dict)):
        return
    if requested <= 0 or boosted <= 0:
        return
    issued_ratio = min(max(boosted / requested, 0.0), 1.0)
    issued_revenue = round(max(gross, 0.0) * issued_ratio, 2)
    rows.append(
        {
            "deal_id": str(deal_id),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "requested": int(requested),
            "boosted": int(boosted),
            "gross_revenue": issued_revenue,
            "net_revenue": round(issued_revenue * 0.97, 2),
            "api_spent": round(max(float(api_spent), 0.0), 2),
        }
    )
    data.set("sales", rows)


def _api_error_text(payload: dict | None) -> str:
    body = payload if isinstance(payload, dict) else {}
    detail = body.get("detail")
    if isinstance(detail, dict):
        err = str(detail.get("error", "") or "").strip().lower()
        if err == "insufficient_balance":
            return "❌ Недостаточно баланса API-ключа для выдачи."
        if err == "insufficient_stock":
            return "⏳ Сейчас нету бустов. Повторная попытка через 1 час."
    if isinstance(detail, str) and detail.strip():
        return f"❌ Ошибка API: {detail.strip()}"
    return _buyer_text("ru", "api_fail")


def _is_insufficient_stock(payload: dict | None) -> bool:
    body = payload if isinstance(payload, dict) else {}
    detail = body.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("error", "") or "").strip().lower() == "insufficient_stock"
    if isinstance(detail, str):
        return "insufficient_stock" in detail.lower()
    return False


def _extract_stock(payload: dict | None) -> tuple[int, int]:
    body = payload if isinstance(payload, dict) else {}
    stock = body.get("stock")
    if not isinstance(stock, dict):
        return 0, 0
    one_month = int(stock.get("oneMonth", 0) or 0)
    three_month = int(stock.get("threeMonth", 0) or 0)
    return max(one_month, 0), max(three_month, 0)


def _deal_is_rolled_back(plbot: "PlayerokBot", deal_id: str) -> bool:
    if not deal_id:
        return False
    try:
        # 1) Prefer live status from Playerok API.
        deal = plbot.account.get_deal(str(deal_id))
        live_status = str(getattr(getattr(deal, "status", None), "name", "") or "").upper()
        if live_status == "ROLLED_BACK":
            return True
        # 2) Fallback to cached status.
        status = str(getattr(plbot, "cached_orders", {}).get(str(deal_id), {}).get("status", "") or "").upper()
        return status == "ROLLED_BACK"
    except Exception:
        try:
            status = str(getattr(plbot, "cached_orders", {}).get(str(deal_id), {}).get("status", "") or "").upper()
            return status == "ROLLED_BACK"
        except Exception:
            return False


def _deal_status_name(plbot: "PlayerokBot", deal_id: str) -> str:
    if not deal_id:
        return "UNKNOWN"
    try:
        deal = plbot.account.get_deal(str(deal_id))
        status = str(getattr(getattr(deal, "status", None), "name", "") or "").upper()
        if status:
            return status
    except Exception:
        logger.debug("TRACEBACK", exc_info=True)
    try:
        return str(getattr(plbot, "cached_orders", {}).get(str(deal_id), {}).get("status", "UNKNOWN") or "UNKNOWN").upper()
    except Exception:
        return "UNKNOWN"


def _watch_order(plbot: "PlayerokBot", deal_id: str, chat_id: str, buyer_name: str,
                 api_order_id: str, requested_boosts: int, api_spent_total: float, gross: float):
    client = _api_client()
    if client is None:
        return

    ask_confirm = bool(_cfg().get("ask_confirm", True))
    final_states = {"completed", "partially_completed", "failed"}

    for _ in range(120):
        ok, resp = client.get_order(api_order_id)
        if ok and isinstance(resp, dict):
            order_data = resp.get("order", resp)
            if isinstance(order_data, dict):
                status = str(order_data.get("status", "") or "").lower()
                boosted = int(order_data.get("boosted", 0) or 0)
                requested = int(order_data.get("requested", requested_boosts) or requested_boosts)
                if status in final_states:
                    if status == "completed":
                        # Mark deal as completed from seller side so buyer can confirm.
                        try:
                            if requested > 0 and boosted >= requested:
                                plbot.account.update_deal(deal_id, ItemDealStatuses.SENT)
                        except Exception:
                            logger.debug("TRACEBACK", exc_info=True)
                        plbot.send_message(chat_id, _buyer_text("ru", "status_completed"), exclude_watermark=True)
                        if ask_confirm:
                            plbot.send_message(chat_id, _buyer_text("ru", "please_confirm"), exclude_watermark=True)
                    elif status == "partially_completed":
                        plbot.send_message(chat_id, _buyer_text("ru", "status_partial", boosted=boosted, requested=requested), exclude_watermark=True)
                        if ask_confirm:
                            plbot.send_message(chat_id, _buyer_text("ru", "please_confirm"), exclude_watermark=True)
                    else:
                        if boosted <= 0:
                            cached_status = str(getattr(plbot, "cached_orders", {}).get(deal_id, {}).get("status", "") or "").upper()
                            if cached_status == "ROLLED_BACK":
                                plbot.send_message(chat_id, _buyer_text("ru", "status_wait_cancelled_refund"), exclude_watermark=True)
                            else:
                                plbot.send_message(chat_id, _buyer_text("ru", "status_failed_no_refund"), exclude_watermark=True)

                    if boosted > 0:
                        _append_sale(deal_id, requested, boosted, gross, api_spent_total)
                    return
        time.sleep(5)


def _deal_gross(deal) -> float:
    try:
        return float(getattr(getattr(deal, "item", None), "price", 0.0) or 0.0)
    except Exception:
        return 0.0


async def on_new_deal(plbot: "PlayerokBot", event: NewDealEvent):
    try:
        if event.deal.user.id == plbot.account.id:
            return
    except Exception:
        pass

    lot_id, binding = _resolve_binding(event.deal)
    if not lot_id or not binding:
        return

    if _api_client() is None:
        logger.warning(f"{PREFIX} API key не задан. Автовыдача отключена для сделки #{event.deal.id}.")
        plbot.send_message(event.chat.id, _buyer_text("ru", "manual_only"), exclude_watermark=True)
        return

    qty_units = 1
    requested_boosts = max(int(binding.get("boosts_per_unit", 1) or 1) * qty_units, 1)
    duration = str(binding.get("duration", "oneMonth") or "oneMonth")
    if duration not in {"oneMonth", "threeMonth"}:
        duration = "oneMonth"

    _pending_upsert(
        event.chat.id,
        {
            "deal_id": str(event.deal.id),
            "chat_id": str(event.chat.id),
            "buyer_username": str(event.deal.user.username or ""),
            "requested_boosts": requested_boosts,
            "duration": duration,
            "gross": _deal_gross(event.deal),
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    plbot.send_message(event.chat.id, ORDER_MESSAGES["ru"], exclude_watermark=True)
    logger.info(f"{PREFIX} Новая сделка #{event.deal.id} ({event.deal.user.username}) взята в обработку NeverBoost.")


async def on_new_message(plbot: "PlayerokBot", event: NewMessageEvent):
    try:
        if event.message.user.id == plbot.account.id:
            return
    except Exception:
        return

    text = str(getattr(event.message, "text", "") or "").strip()
    sender_username = str(getattr(event.message.user, "username", "") or "buyer")
    if text.lower() == "#status":
        client = _api_client()
        if client is None:
            plbot.send_message(event.chat.id, _buyer_text("ru", "manual_only"), exclude_watermark=True)
            return
        # If buyer is currently in pending retry queue, show that first.
        pending_for_status = _pending_get_one(event.chat.id)
        if isinstance(pending_for_status, dict):
            deal_id = str(pending_for_status.get("deal_id", "") or "n/a")
            if _deal_is_rolled_back(plbot, deal_id):
                _pending_pop(event.chat.id)
                _pending_pop_by_deal_id(deal_id)
                plbot.send_message(event.chat.id, _buyer_text("ru", "status_wait_cancelled_refund"), exclude_watermark=True)
                return
            retry_after_ts = float(pending_for_status.get("retry_after_ts", 0.0) or 0.0)
            now_ts = time.time()
            if retry_after_ts > now_ts:
                minutes = max(int((retry_after_ts - now_ts + 59) // 60), 1)
                plbot.send_message(
                    event.chat.id,
                    _buyer_text("ru", "status_waiting_retry", deal_id=deal_id, minutes=minutes),
                    exclude_watermark=True,
                )
                return
        buyer_rows = _last_orders_list_for_buyer(sender_username)
        if not buyer_rows:
            plbot.send_message(event.chat.id, _buyer_text("ru", "status_no_orders"), exclude_watermark=True)
            return
        lines = ["📡 Ваши последние API-заказы"]
        for row in reversed(buyer_rows[-5:]):
            deal_id = str(row.get("deal_id", "") or "n/a").strip() or "n/a"
            api_order_id = str(row.get("api_order_id", "") or "").strip()
            deal_status = _deal_status_name(plbot, deal_id)
            if deal_status == "ROLLED_BACK":
                lines.append(f"\n• Deal #{deal_id}: ОТМЕНЕН")
                continue
            if not api_order_id:
                lines.append(f"\n• Deal #{deal_id}: нет API ID")
                continue
            ok, resp = client.get_order(api_order_id)
            if not ok or not isinstance(resp, dict):
                lines.append(f"\n• Deal #{deal_id}: API недоступен")
                continue
            order_data = resp.get("order", resp)
            if not isinstance(order_data, dict):
                lines.append(f"\n• Deal #{deal_id}: API недоступен")
                continue
            status = str(order_data.get("status", "unknown") or "unknown")
            boosted = int(order_data.get("boosted", 0) or 0)
            requested = int(order_data.get("requested", 0) or 0)
            lines.append(
                f"\n• Deal #{deal_id}\n"
                f"  API: {api_order_id}\n"
                f"  Статус: {status}\n"
                f"  Выдано: {boosted}/{requested}"
            )
        plbot.send_message(event.chat.id, "\n".join(lines), exclude_watermark=True)
        return

    if text.lower() == "#stock":
        client = _api_client()
        if client is None:
            plbot.send_message(event.chat.id, _buyer_text("ru", "manual_only"), exclude_watermark=True)
            return
        ok, resp = client._request("GET", "/stock")
        if not ok:
            plbot.send_message(event.chat.id, "❌ Не удалось получить сток. Попробуйте позже.", exclude_watermark=True)
            return
        one_month, three_month = _extract_stock(resp)
        plbot.send_message(
            event.chat.id,
            _buyer_text("ru", "stock_response", one_month=one_month, three_month=three_month),
            exclude_watermark=True,
        )
        return

    if text.lower() == "#boost":
        pending_for_retry = _pending_get_one(event.chat.id)
        if not isinstance(pending_for_retry, dict):
            # Requested behavior: silently ignore when there is nothing to retry.
            return
        client = _api_client()
        if client is None:
            plbot.send_message(event.chat.id, _buyer_text("ru", "manual_only"), exclude_watermark=True)
            return
        retry_after_ts = float(pending_for_retry.get("retry_after_ts", 0.0) or 0.0)
        now_ts = time.time()
        if retry_after_ts > now_ts:
            minutes = max(int((retry_after_ts - now_ts + 59) // 60), 1)
            plbot.send_message(event.chat.id, _buyer_text("ru", "retry_too_early", minutes=minutes), exclude_watermark=True)
            return
        invite_code_saved = str(pending_for_retry.get("invite_code", "") or "").strip()
        if not invite_code_saved:
            plbot.send_message(event.chat.id, _buyer_text("ru", "retry_missing_invite"), exclude_watermark=True)
            return
        plbot.send_message(event.chat.id, _buyer_text("ru", "retry_started"), exclude_watermark=True)
        qty = max(int(pending_for_retry.get("requested_boosts", 1) or 1), 1)
        duration = str(pending_for_retry.get("duration", "oneMonth") or "oneMonth")
        deal_id = str(pending_for_retry.get("deal_id", "") or "").strip()
        gross = float(pending_for_retry.get("gross", 0.0) or 0.0)
        if _deal_is_rolled_back(plbot, deal_id):
            _pending_pop(event.chat.id)
            _pending_pop_by_deal_id(deal_id)
            return
        api_order_id = uuid.uuid4().hex
        ok, resp = client.create_boost_order(api_order_id, duration, f"https://discord.gg/{invite_code_saved}", qty)
        if not ok:
            ok2, check = client.get_order(api_order_id)
            order_data = check.get("order") if ok2 and isinstance(check, dict) else None
            if isinstance(order_data, dict):
                status = str(order_data.get("status", "") or "").lower()
                if status and status != "failed":
                    ok = True
                    resp = order_data
            if not ok:
                if _is_insufficient_stock(resp):
                    if _deal_is_rolled_back(plbot, deal_id):
                        _pending_pop(event.chat.id)
                        _pending_pop_by_deal_id(deal_id)
                        return
                    _pending_patch(event.chat.id, {"retry_after_ts": time.time() + 3600})
                plbot.send_message(event.chat.id, _api_error_text(resp), exclude_watermark=True)
                return
        spent = 0.0
        if isinstance(resp, dict):
            final_amount = float(resp.get("final_amount", resp.get("amount", 0.0)) or 0.0)
            refund_amount = float(resp.get("refund_amount", 0.0) or 0.0)
            spent = round(max(final_amount - refund_amount, 0.0), 2)
        _pending_pop(event.chat.id)
        plbot.send_message(event.chat.id, _buyer_text("ru", "order_created", api_order_id=api_order_id), exclude_watermark=True)
        _last_order_set_for_buyer(
            sender_username,
            {
                "deal_id": deal_id,
                "chat_id": str(event.chat.id),
                "api_order_id": api_order_id,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        Thread(
            target=_watch_order,
            args=(plbot, deal_id, event.chat.id, sender_username, api_order_id, qty, spent, gross),
            daemon=True,
        ).start()
        return

    pending = _pending_get_one(event.chat.id)
    if not pending:
        return

    expected = str(pending.get("buyer_username", "") or "").strip().lower()
    sender = str(getattr(event.message.user, "username", "") or "").strip().lower()
    if expected and sender and expected != sender:
        return

    invite_code = _extract_invite_code(text)
    if not invite_code:
        plbot.send_message(event.chat.id, _buyer_text("ru", "invalid"), exclude_watermark=True)
        return

    invite_data = _fetch_invite_data(invite_code)
    if not isinstance(invite_data, dict):
        plbot.send_message(event.chat.id, _buyer_text("ru", "bad"), exclude_watermark=True)
        return

    if _is_join_requests_enabled(invite_code):
        plbot.send_message(event.chat.id, _buyer_text("ru", "requests_on"), exclude_watermark=True)
        return

    client = _api_client()
    if client is None:
        plbot.send_message(event.chat.id, _buyer_text("ru", "api_fail"), exclude_watermark=True)
        return

    qty = max(int(pending.get("requested_boosts", 1) or 1), 1)
    duration = str(pending.get("duration", "oneMonth") or "oneMonth")
    deal_id = str(pending.get("deal_id", "") or "").strip()
    gross = float(pending.get("gross", 0.0) or 0.0)
    if _deal_is_rolled_back(plbot, deal_id):
        _pending_pop(event.chat.id)
        _pending_pop_by_deal_id(deal_id)
        plbot.send_message(event.chat.id, _buyer_text("ru", "status_wait_cancelled_refund"), exclude_watermark=True)
        return

    api_order_id = uuid.uuid4().hex
    _pending_patch(event.chat.id, {"invite_code": invite_code})
    ok, resp = client.create_boost_order(api_order_id, duration, f"https://discord.gg/{invite_code}", qty)
    if not ok:
        ok2, check = client.get_order(api_order_id)
        order_data = check.get("order") if ok2 and isinstance(check, dict) else None
        if isinstance(order_data, dict):
            status = str(order_data.get("status", "") or "").lower()
            if status and status != "failed":
                ok = True
                resp = order_data
        if not ok:
            if _is_insufficient_stock(resp):
                if _deal_is_rolled_back(plbot, deal_id):
                    _pending_pop(event.chat.id)
                    _pending_pop_by_deal_id(deal_id)
                    plbot.send_message(event.chat.id, _buyer_text("ru", "status_wait_cancelled_refund"), exclude_watermark=True)
                    return
                _pending_patch(event.chat.id, {"retry_after_ts": time.time() + 3600})
            plbot.send_message(event.chat.id, _api_error_text(resp), exclude_watermark=True)
            return

    spent = 0.0
    if isinstance(resp, dict):
        final_amount = float(resp.get("final_amount", resp.get("amount", 0.0)) or 0.0)
        refund_amount = float(resp.get("refund_amount", 0.0) or 0.0)
        spent = round(max(final_amount - refund_amount, 0.0), 2)

    _pending_pop(event.chat.id)
    plbot.send_message(event.chat.id, _buyer_text("ru", "order_created", api_order_id=api_order_id), exclude_watermark=True)
    _last_order_set_for_buyer(
        sender_username,
        {
            "deal_id": deal_id,
            "chat_id": str(event.chat.id),
            "api_order_id": api_order_id,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
    )

    Thread(
        target=_watch_order,
        args=(
            plbot,
            deal_id,
            event.chat.id,
            str(getattr(event.message.user, "username", "") or "buyer"),
            api_order_id,
            qty,
            spent,
            gross,
        ),
        daemon=True,
    ).start()


async def on_deal_status_changed(plbot: "PlayerokBot", event: DealStatusChangedEvent):
    deal = event.deal
    if deal is None or not getattr(deal, "id", None):
        return

    if deal.status in {ItemDealStatuses.ROLLED_BACK}:
        # Если сделку вернули вручную, убираем ожидание ссылки.
        _pending_pop(event.chat.id)
        _pending_pop_by_deal_id(str(deal.id))
        plbot.send_message(event.chat.id, _buyer_text("ru", "status_wait_cancelled_refund"), exclude_watermark=True)
