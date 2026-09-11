import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.neverboost.client import NeverBoostClient, NeverBoostError
from app.settings_store import SettingsStore
import updater

logger = logging.getLogger("neverboost-playerok.telegram")


def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Обзор", callback_data="screen:status"), InlineKeyboardButton(text="💰 NeverBoost", callback_data="screen:api")],
        [InlineKeyboardButton(text="⚙️ Автоматизация", callback_data="screen:features"), InlineKeyboardButton(text="📦 Мои лоты", callback_data="screen:lots")],
        [InlineKeyboardButton(text="🧾 Заказы", callback_data="screen:orders"), InlineKeyboardButton(text="🔧 Подключение", callback_data="screen:connection")],
        [InlineKeyboardButton(text="🆕 Обновить бота", callback_data="update:check"), InlineKeyboardButton(text="🔄 Обновить меню", callback_data="screen:menu")],
    ])


def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="⬅️ В главное меню", callback_data="screen:menu")]])


FEATURE_INFO = {
    "auto_restore": {
        "title": "♻️ Автовосстановление товаров",
        "description": "После продажи или истечения срока бот автоматически публикует товар снова, чтобы он продолжал продаваться.",
    },
    "auto_complete": {
        "title": "✅ Автоподтверждение сделки",
        "description": "Бот сам отмечает сделку как выполненную после оплаты. Включайте только если ваша выдача действительно происходит автоматически.",
    },
    "auto_bump": {
        "title": "⬆️ Автоподнятие товаров",
        "description": "Бот периодически поднимает ваши активные товары в поиске Playerok. Если для поднятия нужен платный статус, расход оплачивается в Playerok.",
    },
    "notifications": {
        "title": "🔔 Уведомления",
        "description": "Бот присылает администратору сообщения о новых заказах, восстановлении товаров, ошибках и изменениях статуса.",
    },
}


class TelegramPanel:
    def __init__(self, store: SettingsStore, repository, base_url: str) -> None:
        self.store = store
        self.repository = repository
        self.base_url = base_url
        self.router = Router()
        self.router.message.middleware(self._auth_middleware)
        self.router.callback_query.middleware(self._auth_middleware)
        self._register_handlers()

    async def _auth_middleware(self, handler, event, data):
        admins = {int(x) for x in self.store.get("telegram", "admins", default=[]) if str(x).isdigit()}
        user_id = getattr(getattr(event, "from_user", None), "id", None)
        if user_id not in admins:
            if isinstance(event, CallbackQuery):
                await event.answer("Нет доступа", show_alert=True)
            return
        return await handler(event, data)

    def _register_handlers(self) -> None:
        self.router.message.register(self.start, Command("start"))
        self.router.message.register(self.start, Command("menu"))
        self.router.message.register(self.help, Command("help"))
        self.router.message.register(self.set_key, Command("set_key"))
        self.router.message.register(self.add_lot, Command("add_lot"))
        self.router.message.register(self.toggle, Command("toggle"))
        self.router.callback_query.register(self.callback)

    async def start(self, message: Message) -> None:
        await message.answer(self._home_text(), reply_markup=keyboard())

    async def help(self, message: Message) -> None:
        await message.answer(
            "<b>Команды панели</b>\n\n"
            "/menu — открыть меню\n"
            "/set_key KEY — заменить API-ключ\n"
            "/add_lot ID oneMonth 2 — добавить лот\n"
            "/toggle NAME on — изменить функцию\n\n"
            "Остальное доступно через кнопки меню.",
            reply_markup=keyboard(),
        )

    def _home_text(self) -> str:
        bindings = self.store.get("lot_bindings", default={})
        active = sum(1 for row in self.repository.orders.values() if row.get("status") == "processing")
        waiting = sum(1 for row in self.repository.orders.values() if row.get("status") == "waiting_invite")
        return (
            "<b>NeverBoost Playerok</b>\n"
            "<i>Центр управления магазином</i>\n\n"
            f"📦 Лотов настроено: <b>{len(bindings)}</b>\n"
            f"⏳ Ожидают ссылку: <b>{waiting}</b>\n"
            f"🚀 В обработке: <b>{active}</b>"
        )

    async def set_key(self, message: Message) -> None:
        parts = message.text.split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Использование: <code>/set_key API_KEY</code>")
            return
        self.store.set("neverboost", "api_key", value=parts[1].strip())
        await message.answer("✅ API-ключ сохранён")

    async def add_lot(self, message: Message) -> None:
        parts = message.text.split()
        if len(parts) < 4 or parts[2] not in {"oneMonth", "threeMonth"} or not parts[3].isdigit():
            await message.answer("Использование: <code>/add_lot ITEM_ID oneMonth 2</code>\nСрок: <code>oneMonth</code> или <code>threeMonth</code>")
            return
        bindings = self.store.get("lot_bindings", default={})
        bindings[parts[1]] = {"duration": parts[2], "boosts_per_unit": max(int(parts[3]), 1)}
        self.store.set("lot_bindings", value=bindings)
        await message.answer(f"✅ Лот <code>{html.escape(parts[1])}</code> добавлен")

    async def toggle(self, message: Message) -> None:
        parts = message.text.split()
        if len(parts) != 3 or parts[1] not in {"auto_restore", "auto_complete", "auto_bump", "notifications"} or parts[2] not in {"on", "off"}:
            await message.answer("Использование: <code>/toggle auto_restore on</code>")
            return
        self.store.set("features", parts[1], value=parts[2] == "on")
        await message.answer("✅ Настройка обновлена")

    async def callback(self, query: CallbackQuery) -> None:
        action = query.data or "screen:menu"
        if action == "update:check":
            await query.answer("Проверяю GitHub...", show_alert=False)
            try:
                available, current, latest = await asyncio.to_thread(updater.update_available)
                if not available:
                    await query.message.edit_text("✅ У вас последняя версия.", reply_markup=back_keyboard())
                else:
                    buttons = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text="⬇️ Установить и перезапустить", callback_data="update:install")],
                        [InlineKeyboardButton(text="⬅️ Назад", callback_data="screen:menu")],
                    ])
                    await query.message.edit_text(f"🆕 Доступно обновление\n\nТекущая: <code>{current[:8]}</code>\nНовая: <code>{latest[:8]}</code>", reply_markup=buttons)
            except Exception as exc:
                await query.message.edit_text(f"❌ Не удалось проверить обновления:\n<code>{html.escape(str(exc))}</code>", reply_markup=back_keyboard())
        elif action == "update:install":
            await query.message.edit_text("⏳ Устанавливаю обновление и перезапускаю бота...")
            try:
                await asyncio.to_thread(updater.install_update)
                await query.message.edit_text("✅ Обновление установлено. Перезапуск...")
                await asyncio.sleep(1)
                updater.restart()
            except Exception as exc:
                await query.message.edit_text(f"❌ Обновление не установлено:\n<code>{html.escape(str(exc))}</code>", reply_markup=back_keyboard())
        elif action.startswith("toggle:"):
            feature = action.split(":", 1)[1]
            current = bool(self.store.get("features", feature, default=False))
            self.store.set("features", feature, value=not current)
            await self._show(query, "features")
        elif action.startswith("delete_lot:"):
            lot_id = action.split(":", 1)[1]
            bindings = self.store.get("lot_bindings", default={})
            bindings.pop(lot_id, None)
            self.store.set("lot_bindings", value=bindings)
            await self._show(query, "lots")
        elif action.startswith("screen:"):
            await self._show(query, action.split(":", 1)[1])
        await query.answer()

    async def _show(self, query: CallbackQuery, screen: str) -> None:
        if not query.message:
            return
        if screen == "menu":
            await query.message.edit_text(self._home_text(), reply_markup=keyboard())
        elif screen == "status":
            waiting = sum(1 for row in self.repository.orders.values() if row.get("status") == "waiting_invite")
            processing = sum(1 for row in self.repository.orders.values() if row.get("status") == "processing")
            completed = sum(1 for row in self.repository.orders.values() if row.get("status") == "completed")
            failed = sum(1 for row in self.repository.orders.values() if row.get("status") in {"failed", "cancelled"})
            await query.message.edit_text(
                f"📊 <b>Обзор магазина</b>\n\n⏳ Ожидают ссылку: <b>{waiting}</b>\n🚀 В обработке: <b>{processing}</b>\n✅ Завершено: <b>{completed}</b>\n❌ Ошибки/отмены: <b>{failed}</b>",
                reply_markup=back_keyboard(),
            )
        elif screen == "features":
            features = self.store.get("features", default={})
            sections = []
            buttons = []
            for key, value in features.items():
                info = FEATURE_INFO.get(key, {"title": key, "description": "Настройка функции бота."})
                sections.append(f"{info['title']}\n{'🟢 Включено' if value else '⚪ Выключено'}\n<i>{info['description']}</i>")
                buttons.append([InlineKeyboardButton(text=f"{'🔴 Выключить' if value else '🟢 Включить'}: {info['title']}", callback_data=f"toggle:{key}")])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="screen:menu")])
            await query.message.edit_text(
                "⚙️ <b>Автоматизация магазина</b>\n\n" + "\n\n".join(sections) + "\n\n<i>Нажмите кнопку под нужной функцией, чтобы включить или выключить её.</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        elif screen == "lots":
            bindings = self.store.get("lot_bindings", default={})
            text = "\n".join(f"<code>{html.escape(str(key))}</code>: {value.get('duration')} • x{value.get('boosts_per_unit')}" for key, value in bindings.items()) or "Лоты не настроены"
            buttons = [[InlineKeyboardButton(text=f"🗑 Удалить {key}", callback_data=f"delete_lot:{key}")] for key in bindings]
            buttons.extend([[InlineKeyboardButton(text="➕ Как добавить лот", callback_data="screen:lot_help")], [InlineKeyboardButton(text="⬅️ Назад", callback_data="screen:menu")]])
            await query.message.edit_text(f"📦 <b>Мои лоты</b>\n\n{text}\n\nДобавление: <code>/add_lot ID oneMonth 2</code>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
        elif screen == "lot_help":
            await query.message.edit_text("<b>Добавление лота</b>\n\nОтправьте команду:\n<code>/add_lot ID oneMonth 2</code>\n\nГде ID — ID товара Playerok, срок — oneMonth или threeMonth, последнее число — бусты за единицу.", reply_markup=back_keyboard())
        elif screen == "orders":
            rows = list(self.repository.orders.values())[-10:]
            text = "\n".join(f"<code>{html.escape(str(row['deal_id']))}</code> • {row['status']} • x{row['quantity']}" for row in reversed(rows)) or "Заказов нет"
            await query.message.edit_text(f"🧾 <b>Последние заказы</b>\n\n{text}", reply_markup=back_keyboard())
        elif screen == "connection":
            proxy = self.store.get("playerok", "proxy", default="")
            proxy_status = "✅ настроен" if proxy else "⚪ не используется"
            await query.message.edit_text(f"🔧 <b>Подключение</b>\n\nPlayerok proxy: {proxy_status}\nПлагины: <code>{html.escape(str(self.store.get('runtime', 'plugins_dir', default='plugins')))}</code>\n\nДля изменения подключения запустите <code>install.bat</code>.", reply_markup=back_keyboard())
        elif screen == "api":
            client = NeverBoostClient(self.base_url, self.store.get("neverboost", "api_key", default=""))
            try:
                balance = await client.get_balance()
                stock = await client.get_stock()
                await query.message.edit_text(f"💰 <b>NeverBoost API</b>\n\nБаланс: <code>{html.escape(str(balance))}</code>\nСток: <code>{html.escape(str(stock))}</code>", reply_markup=back_keyboard())
            except NeverBoostError as exc:
                await query.message.edit_text(f"❌ API недоступен: {html.escape(str(exc))}", reply_markup=back_keyboard())

    async def run(self) -> None:
        token = self.store.get("telegram", "token", default="")
        if not token:
            logger.warning("Telegram token is not configured")
            return
        logger.info("Telegram-панель запускается")
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dispatcher = Dispatcher()
        dispatcher.include_router(self.router)
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())

    async def notify_admins(self, text: str) -> None:
        token = self.store.get("telegram", "token", default="")
        if not token:
            return
        bot = Bot(token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        try:
            for admin_id in self.store.get("telegram", "admins", default=[]):
                await bot.send_message(int(admin_id), text)
        finally:
            await bot.session.close()
