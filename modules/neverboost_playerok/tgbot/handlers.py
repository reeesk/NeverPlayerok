from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

import requests
from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from settings import Settings as global_settings

from ..data import Data as data
from ..settings import Settings as sett

router = Router()
logger = logging.getLogger("neverboost_playerok.handlers")

class BoostsStates(StatesGroup):
    wait_api_key = State()
    wait_lot_id = State()
    wait_lot_boosts = State()


CB_OPEN = "nbp:open"
CB_BIND = "nbp:bind"
CB_STATS = "nbp:stats"
CB_ORDERS = "nbp:orders"
CB_LOTS = "nbp:lots"
CB_SETTINGS = "nbp:settings"
CB_NOTIFICATIONS = "nbp:notifs"
CB_LOTS_ADD = "nbp:lots:add"
CB_LOTS_DUR = "nbp:lots:dur:"
CB_LOTS_DEL = "nbp:lots:del:"
CB_LOTS_PAGE = "nbp:lots:page:"
CB_SETTINGS_TOGGLE = "nbp:settings:toggle:"
CB_NOTIF_TOGGLE = "nbp:notifs:toggle:"


RUNTIME_LOT_WIZARD: dict[int, dict] = {}
MAX_TG_CALLBACK_DATA = 64


async def _cb_fail(callback: types.CallbackQuery, context: str) -> None:
    logger.exception("Callback failed: %s", context)
    try:
        await callback.answer("? ?????? ??????. ?????????? ??? ???.", show_alert=True)
    except Exception:
        pass


def _is_allowed(user_id: int) -> bool:
    try:
        cfg = global_settings.get("config")
        signed_users = cfg["telegram"]["bot"]["signed_users"]
        return user_id in signed_users
    except Exception:
        return False


def _cfg() -> dict:
    cfg = sett.get("config")
    return cfg if isinstance(cfg, dict) else {}


def _save_cfg(cfg: dict) -> None:
    sett.set("config", cfg)


def _safe_cb_data(value: str, fallback: str = "nbp:noop") -> str:
    raw = str(value or "")
    if 1 <= len(raw.encode("utf-8")) <= MAX_TG_CALLBACK_DATA:
        return raw
    return fallback


def _mask_key(api_key: str) -> str:
    if not api_key:
        return "не задан"
    if len(api_key) <= 8:
        return "*" * len(api_key)
    return f"{api_key[:4]}{'*' * (len(api_key) - 8)}{api_key[-4:]}"


def _extract_lot_id(raw: str) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None

    # Normalize common copy/paste variants of dash characters.
    text = (
        text.replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u2011", "-")
        .replace("\u2212", "-")
    )

    # Playerok lot URL may contain numeric id or slug:
    # https://playerok.com/products/d7aa8f7e3bfa--item-name-
    # Also support trailing slash, query and fragments.
    lowered = text.lower()
    if "playerok.com/" in lowered:
        try:
            parsed = urlparse(text if "://" in text else f"https://{text}")
            path = (parsed.path or "").strip("/")
            parts = [p for p in path.split("/") if p]
            if len(parts) >= 2 and parts[0].lower() == "products":
                candidate = parts[1].strip()
                if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", candidate):
                    return candidate
        except Exception:
            pass

    m0 = re.search(r"/products/([A-Za-z0-9][A-Za-z0-9-]*)", text, flags=re.IGNORECASE)
    if m0:
        return m0.group(1).strip()
    m = re.search(r"[?&]id=(\d+)", text)
    if m:
        return m.group(1)
    # Accept plain lot id/slug sent without URL.
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]*", text):
        return text
    return None


def _extract_lot_title(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    # Support plain slug input without URL, e.g.:
    # 47860eede62c--avtovydacha-24-7-...
    if "--" in text and "/" not in text:
        tail = text.split("--", 1)[1].strip("-")
        tail = re.sub(r"[-_]+", " ", tail).strip()
        if tail:
            return tail
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
        path = (parsed.path or "").strip("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "products":
            slug = parts[1].strip()
            # playerok slug format: <id>--human-readable-title-
            if "--" in slug:
                tail = slug.split("--", 1)[1].strip("-")
                tail = re.sub(r"[-_]+", " ", tail).strip()
                if tail:
                    return tail
    except Exception:
        pass
    return ""


def _normalize_title(value: str) -> str:
    value = str(value or "").lower()
    value = re.sub(r"[^0-9a-zа-яё]+", " ", value, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", value).strip()


def _binding_storage_key(item_title: str) -> str:
    normalized_title = _normalize_title(item_title)
    return normalized_title


def _fetch_lot_title_by_id_or_slug(lot_id: str) -> str:
    candidate = str(lot_id or "").strip()
    if not candidate:
        return ""
    url = f"https://playerok.com/products/{candidate}"
    user_agents = [
        # Playerok often returns full OG metadata for crawler UAs.
        "facebookexternalhit/1.1",
        "Twitterbot/1.0",
        "TelegramBot (like TwitterBot)",
        "Mozilla/5.0",
    ]
    for ua in user_agents:
        try:
            resp = requests.get(url, timeout=12, headers={"User-Agent": ua, "Accept-Language": "ru"})
            if resp.status_code != 200:
                continue
            html = str(resp.text or "")
            # Prefer OG title from the actual product page.
            m = re.search(
                r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']',
                html,
                flags=re.IGNORECASE,
            )
            if m:
                title = str(m.group(1) or "").strip()
                if title and "Маркетплейс игровых товаров" not in title:
                    # Example OG title:
                    # "Купить <item name> Discord за 90 ₽ - Бусты Discord"
                    title = re.sub(r"^\s*Купить\s+", "", title, flags=re.IGNORECASE)
                    title = re.sub(r"\s+Discord\s+за\s+.*$", "", title, flags=re.IGNORECASE)
                    return title.strip()
            # Fallback to <title> if it is not a generic marketplace page title.
            m2 = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
            if m2:
                title = re.sub(r"\s+", " ", str(m2.group(1) or "")).strip()
                title = re.sub(r"\s*\|\s*Playerok.*$", "", title, flags=re.IGNORECASE)
                if title and "Маркетплейс игровых товаров" not in title:
                    return title
        except Exception:
            logger.debug("TRACEBACK", exc_info=True)
    return ""


def _period_bounds(name: str, now: datetime) -> tuple[datetime | None, datetime | None]:
    if name == "all":
        return None, None
    if name == "hour":
        return now - timedelta(hours=1), now
    if name == "day24":
        return now - timedelta(hours=24), now
    if name == "yesterday":
        today_start = datetime(now.year, now.month, now.day)
        return today_start - timedelta(days=1), today_start
    if name == "week":
        return now - timedelta(days=7), now
    if name == "month":
        return now - timedelta(days=30), now
    return None, None


def _parse_dt(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except Exception:
            continue
    return None


def _sales_rows() -> list[dict]:
    rows = data.get("sales")
    return rows if isinstance(rows, list) else []


def _boosts_issued(period: str) -> int:
    now = datetime.now()
    start_dt, end_dt = _period_bounds(period, now)
    total = 0
    for row in _sales_rows():
        if not isinstance(row, dict):
            continue
        dt = _parse_dt(str(row.get("created_at", "")))
        if start_dt and (not dt or dt < start_dt):
            continue
        if end_dt and dt and dt >= end_dt:
            continue
        total += max(int(row.get("boosted", 0) or 0), 0)
    return total


def _profit(period: str) -> float:
    now = datetime.now()
    start_dt, end_dt = _period_bounds(period, now)
    total = 0.0
    for row in _sales_rows():
        if not isinstance(row, dict):
            continue
        dt = _parse_dt(str(row.get("created_at", "")))
        if start_dt and (not dt or dt < start_dt):
            continue
        if end_dt and dt and dt >= end_dt:
            continue
        net_revenue = float(row.get("net_revenue", 0.0) or 0.0)
        api_spent = float(row.get("api_spent", 0.0) or 0.0)
        total += net_revenue - api_spent
    return round(total, 2)


def _menu_text() -> str:
    cfg = _cfg()
    bindings = cfg.get("lot_bindings", {}) if isinstance(cfg.get("lot_bindings"), dict) else {}
    return (
        "<b>🚀 Панель Boosts</b>\n\n"
        f"<b>API ключ:</b> <tg-spoiler>{_mask_key(str(cfg.get('api_key', '') or ''))}</tg-spoiler>\n"
        f"<b>Привязок лотов:</b> <code>{len(bindings)}</code>\n"
        f"<b>Бустов куплено:</b> <code>{_boosts_issued('all')}</code>\n"
        f"<b>Заработано:</b> <code>{_profit('all'):.2f}</code>\n\n"
        "Выберите нужный раздел ниже."
    )


def _menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data=CB_STATS),
                InlineKeyboardButton(text="📦 Заказы", callback_data=CB_ORDERS),
            ],
            [
                InlineKeyboardButton(text="🧾 Лоты", callback_data=CB_LOTS),
                InlineKeyboardButton(text="⚙️ Настройки", callback_data=CB_SETTINGS),
            ],
            [
                InlineKeyboardButton(text="🔔 Уведомления", callback_data=CB_NOTIFICATIONS),
            ],
            [InlineKeyboardButton(text="🔑 Сменить API ключ", callback_data=CB_BIND)],
            [InlineKeyboardButton(text="🔄 Обновить", callback_data=CB_OPEN)],
        ]
    )


def _settings_kb(cfg: dict) -> InlineKeyboardMarkup:
    ask_confirm = bool(cfg.get("ask_confirm", True))

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{'🟢' if ask_confirm else '🔴'} Просить подтверждение заказа", callback_data=f"{CB_SETTINGS_TOGGLE}ask_confirm")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=CB_OPEN)],
        ]
    )


def _notifications_kb(cfg: dict) -> InlineKeyboardMarkup:
    nt = cfg.get("notifications", {}) if isinstance(cfg.get("notifications"), dict) else {}
    success = bool(nt.get("delivery_success", True))
    refund = bool(nt.get("refund_zero", True))
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=f"{'🟢' if success else '🔴'} Уведомлять об успешной выдаче", callback_data=f"{CB_NOTIF_TOGGLE}delivery_success")],
            [InlineKeyboardButton(text=f"{'🟢' if refund else '🔴'} Уведомлять о возврате при 0 бустов", callback_data=f"{CB_NOTIF_TOGGLE}refund_zero")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data=CB_OPEN)],
        ]
    )


def _lots_kb(cfg: dict, page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    bindings = cfg.get("lot_bindings", {}) if isinstance(cfg.get("lot_bindings"), dict) else {}
    items = [(lot_id, row) for lot_id, row in bindings.items() if isinstance(row, dict)]
    total = len(items)
    total_pages = max((total + page_size - 1) // page_size, 1)
    page = max(min(int(page), total_pages - 1), 0)
    start = page * page_size
    end = start + page_size
    items_slice = items[start:end]

    rows = []
    for idx, (lot_id, row) in enumerate(items_slice):
        duration = "1м" if str(row.get("duration", "oneMonth")) == "oneMonth" else "3м"
        bpu = max(int(row.get("boosts_per_unit", 1) or 1), 1)
        title = str(row.get("item_title", "") or "").strip() or str(lot_id)
        if len(title) > 34:
            title = f"{title[:31]}..."
        rows.append([
            InlineKeyboardButton(text=f"🎯 {title} • {duration} • x{bpu}", callback_data="nbp:noop"),
            # Telegram callback_data has strict size limit, so we pass compact index.
            InlineKeyboardButton(text="🗑", callback_data=_safe_cb_data(f"{CB_LOTS_DEL}{page}:{idx}")),
        ])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=_safe_cb_data(f"{CB_LOTS_PAGE}{page - 1}")))
    nav.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="nbp:noop"))
    if page + 1 < total_pages:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=_safe_cb_data(f"{CB_LOTS_PAGE}{page + 1}")))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(text="➕ Добавить лот", callback_data=_safe_cb_data(CB_LOTS_ADD))])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data=_safe_cb_data(CB_OPEN))])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("boosts"))
async def cmd_boosts(message: types.Message, state: FSMContext):
    await state.set_state(None)
    if not _is_allowed(message.from_user.id):
        return
    await message.answer(_menu_text(), reply_markup=_menu_kb(), parse_mode="HTML")


@router.callback_query(F.data == CB_OPEN)
async def cb_open(callback: types.CallbackQuery):
    try:
        if not _is_allowed(callback.from_user.id):
            await callback.answer()
            return
        await callback.message.edit_text(_menu_text(), reply_markup=_menu_kb(), parse_mode="HTML")
        await callback.answer()
    except Exception:
        await _cb_fail(callback, "cb_open")

@router.callback_query(F.data == CB_STATS)
async def cb_stats(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return

    def fmt(period_key: str, title: str) -> str:
        return f"<b>{title}</b>: бустов <code>{_boosts_issued(period_key)}</code>, прибыль <code>{_profit(period_key):.2f}</code>"

    text = (
        "<b>📊 Статистика</b>\n\n"
        f"{fmt('hour', 'За час')}\n"
        f"{fmt('day24', 'За 24 часа')}\n"
        f"{fmt('yesterday', 'Вчера')}\n"
        f"{fmt('week', 'За неделю')}\n"
        f"{fmt('month', 'За месяц')}\n"
        f"{fmt('all', 'За всё время')}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=CB_OPEN)]])
    await callback.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == CB_ORDERS)
async def cb_orders(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return

    pending = data.get("pending_invites")
    pending = pending if isinstance(pending, dict) else {}
    rows = _sales_rows()

    lines = [
        "<b>📦 Заказы</b>",
        "",
        f"Ожидают ссылку: <code>{len(pending)}</code>",
        f"История выдач: <code>{len(rows)}</code>",
    ]
    for row in list(rows)[-8:][::-1]:
        if not isinstance(row, dict):
            continue
        deal_id = str(row.get("deal_id", "n/a") or "n/a")
        boosted = int(row.get("boosted", 0) or 0)
        requested = int(row.get("requested", 0) or 0)
        lines.append(f"• <code>#{deal_id}</code> — {boosted}/{requested}")

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=CB_OPEN)]])
    await callback.message.edit_text("\n".join(lines), reply_markup=kb, parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data == CB_LOTS)
async def cb_lots(callback: types.CallbackQuery):
    try:
        if not _is_allowed(callback.from_user.id):
            await callback.answer()
            return
        cfg = _cfg()
        await callback.message.edit_text("<b>🧾 Привязки лотов</b>", reply_markup=_lots_kb(cfg, page=0), parse_mode="HTML")
        await callback.answer()
    except Exception:
        await _cb_fail(callback, "cb_lots")

@router.callback_query(F.data.startswith(CB_LOTS_PAGE))
async def cb_lots_page(callback: types.CallbackQuery):
    try:
        if not _is_allowed(callback.from_user.id):
            await callback.answer()
            return
        try:
            page = int(callback.data.replace(CB_LOTS_PAGE, "", 1))
        except Exception:
            page = 0
        cfg = _cfg()
        await callback.message.edit_reply_markup(reply_markup=_lots_kb(cfg, page=page))
        await callback.answer()
    except Exception:
        await _cb_fail(callback, "cb_lots_page")

@router.callback_query(F.data == CB_LOTS_ADD)
async def cb_lots_add(callback: types.CallbackQuery, state: FSMContext):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BoostsStates.wait_lot_id)
    await callback.message.answer(
        "Введите название товара.\n\n"
        "Пример: <code>⋆.˚ ⚡ Автовыдача 24/7 ▾ 🚀 Цена за 1 шт ▾ ✅ Буст на 30 дней 🌙 ˚.⋆</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BoostsStates.wait_lot_id)
async def st_wait_lot_id(message: types.Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    raw_input = str(message.text or "").strip()
    if not raw_input:
        await message.answer("❌ Пустое название. Введите название товара или ссылку.")
        return

    cfg = _cfg()
    bindings = cfg.get("lot_bindings", {}) if isinstance(cfg.get("lot_bindings"), dict) else {}

    parsed_title = _extract_lot_title(raw_input)
    if not parsed_title:
        lot_id = _extract_lot_id(raw_input)
        if lot_id:
            parsed_title = _fetch_lot_title_by_id_or_slug(lot_id)
    if not parsed_title:
        parsed_title = raw_input
    normalized_title = _normalize_title(parsed_title)
    if not normalized_title:
        await message.answer("❌ Не удалось распознать название лота.")
        return
    if normalized_title in bindings:
        await state.set_state(None)
        await message.answer("❌ Этот лот уже привязан.")
        return
    RUNTIME_LOT_WIZARD[message.from_user.id] = {"item_title": parsed_title}
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="1 месяц", callback_data=f"{CB_LOTS_DUR}oneMonth"), InlineKeyboardButton(text="3 месяца", callback_data=f"{CB_LOTS_DUR}threeMonth")]]
    )
    await message.answer("Выберите длительность:", reply_markup=kb)


@router.callback_query(F.data.startswith(CB_LOTS_DUR))
async def cb_lots_duration(callback: types.CallbackQuery, state: FSMContext):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    duration = callback.data.replace(CB_LOTS_DUR, "", 1)
    if duration not in {"oneMonth", "threeMonth"}:
        await callback.answer("Неверная длительность")
        return

    wiz = RUNTIME_LOT_WIZARD.get(callback.from_user.id)
    if not isinstance(wiz, dict) or not str(wiz.get("item_title", "") or "").strip():
        await callback.answer("Сессия устарела")
        return
    wiz["duration"] = duration
    RUNTIME_LOT_WIZARD[callback.from_user.id] = wiz

    await state.set_state(BoostsStates.wait_lot_boosts)
    await callback.message.answer("Введите количество бустов на 1 единицу товара (например: 2):")
    await callback.answer()


@router.message(BoostsStates.wait_lot_boosts)
async def st_wait_lot_boosts(message: types.Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    try:
        bpu = int(str(message.text or "").strip())
        if bpu <= 0:
            raise ValueError
    except Exception:
        await message.answer("❌ Введите целое число больше 0.")
        return

    wiz = RUNTIME_LOT_WIZARD.pop(message.from_user.id, None)
    if not isinstance(wiz, dict) or "duration" not in wiz:
        await state.set_state(None)
        await message.answer("❌ Сессия добавления лота устарела.")
        return

    cfg = _cfg()
    bindings = cfg.get("lot_bindings", {}) if isinstance(cfg.get("lot_bindings"), dict) else {}
    item_title = str(wiz.get("item_title", "") or "")
    storage_key = _binding_storage_key(item_title)
    if not storage_key:
        await state.set_state(None)
        await message.answer("❌ Не удалось сохранить привязку: пустое название.")
        return
    bindings[storage_key] = {
        "duration": str(wiz["duration"]),
        "boosts_per_unit": bpu,
        "item_title": item_title,
    }
    cfg["lot_bindings"] = bindings
    _save_cfg(cfg)

    await state.set_state(None)
    await message.answer("✅ Лот успешно привязан.")
    await message.answer("<b>🧾 Привязки лотов</b>", reply_markup=_lots_kb(cfg), parse_mode="HTML")


@router.callback_query(F.data.startswith(CB_LOTS_DEL))
async def cb_lots_del(callback: types.CallbackQuery):
    try:
        if not _is_allowed(callback.from_user.id):
            await callback.answer()
            return
        payload = callback.data.replace(CB_LOTS_DEL, "", 1)
        page = 0
        idx = -1
        if ":" in payload:
            page_s, idx_s = payload.split(":", 1)
            try:
                page = int(page_s)
            except Exception:
                page = 0
            try:
                idx = int(idx_s)
            except Exception:
                idx = -1
        cfg = _cfg()
        bindings = cfg.get("lot_bindings", {}) if isinstance(cfg.get("lot_bindings"), dict) else {}
        if idx >= 0:
            items = [(lid, row) for lid, row in bindings.items() if isinstance(row, dict)]
            page_size = 8
            total_pages = max((len(items) + page_size - 1) // page_size, 1)
            page = max(min(page, total_pages - 1), 0)
            start = page * page_size
            end = start + page_size
            items_slice = items[start:end]
            if 0 <= idx < len(items_slice):
                lot_id = items_slice[idx][0]
                if lot_id in bindings:
                    bindings.pop(lot_id, None)
                    cfg["lot_bindings"] = bindings
                    _save_cfg(cfg)
        await callback.message.edit_reply_markup(reply_markup=_lots_kb(cfg, page=page))
        await callback.answer("Удалено")
    except Exception:
        await _cb_fail(callback, "cb_lots_del")

@router.callback_query(F.data == "nbp:noop")
async def cb_noop(callback: types.CallbackQuery):
    await callback.answer()


@router.callback_query(F.data == CB_SETTINGS)
async def cb_settings(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    cfg = _cfg()
    await callback.message.edit_text("<b>⚙️ Настройки</b>", reply_markup=_settings_kb(cfg), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith(CB_SETTINGS_TOGGLE))
async def cb_settings_toggle(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.replace(CB_SETTINGS_TOGGLE, "", 1)
    allowed = {"ask_confirm"}
    if key not in allowed:
        await callback.answer("Неизвестная настройка")
        return

    cfg = _cfg()
    cfg[key] = not bool(cfg.get(key, False))
    _save_cfg(cfg)
    await callback.message.edit_reply_markup(reply_markup=_settings_kb(cfg))
    await callback.answer("Обновлено")


@router.callback_query(F.data == CB_NOTIFICATIONS)
async def cb_notifs(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    cfg = _cfg()
    await callback.message.edit_text("<b>🔔 Уведомления</b>", reply_markup=_notifications_kb(cfg), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith(CB_NOTIF_TOGGLE))
async def cb_notif_toggle(callback: types.CallbackQuery):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    key = callback.data.replace(CB_NOTIF_TOGGLE, "", 1)
    if key not in {"delivery_success", "refund_zero"}:
        await callback.answer("Неизвестная настройка")
        return

    cfg = _cfg()
    nt = cfg.get("notifications", {}) if isinstance(cfg.get("notifications"), dict) else {}
    nt[key] = not bool(nt.get(key, True))
    cfg["notifications"] = nt
    _save_cfg(cfg)
    await callback.message.edit_reply_markup(reply_markup=_notifications_kb(cfg))
    await callback.answer("Обновлено")


@router.callback_query(F.data == CB_BIND)
async def cb_bind(callback: types.CallbackQuery, state: FSMContext):
    if not _is_allowed(callback.from_user.id):
        await callback.answer()
        return
    await state.set_state(BoostsStates.wait_api_key)
    await callback.message.answer(
        "Отправьте ваш API ключ одним сообщением.\n\n"
        "Пример: <code>nb_xxxxxxxxxxxxxxxxx</code>",
        parse_mode="HTML",
    )
    await callback.answer()


@router.message(BoostsStates.wait_api_key)
async def st_wait_api_key(message: types.Message, state: FSMContext):
    if not _is_allowed(message.from_user.id):
        return
    api_key = str(message.text or "").strip()
    if len(api_key) < 8 or " " in api_key:
        await message.answer("Неверный формат API ключа.")
        return

    cfg = _cfg()
    cfg["api_key"] = api_key
    _save_cfg(cfg)

    await state.set_state(None)
    await message.answer("✅ Ключ принят и сохранен.")
    await message.answer(_menu_text(), reply_markup=_menu_kb(), parse_mode="HTML")
