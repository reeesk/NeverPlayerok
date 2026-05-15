import pytz
import re
import sys
from datetime import datetime, timedelta
from collections import Counter
import base64
import string
import requests
from logging import getLogger
from colorama import Fore

from playerokapi.account import Account
from playerokapi.types import Chat
from playerokapi.exceptions import BotCheckDetectedException

from settings import Settings as sett
from data import Data as data


logger = getLogger("universal")


def strip_html(text):
    return re.sub(r'<[^>]+>', '', text or '')


def parse_date(date_str: str) -> datetime | None:
    formats = [
        "%d.%m.%Y",
        "%d.%m.%y",
        "%-d.%-m.%Y",
        "%-d.%-m.%y",
        "%-d.%m.%Y",
        "%-d.%m.%y",
        "%d.%-m.%Y",
        "%d.%-m.%y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def get_event_next_time(last_time_iso, interval):
    return (
        datetime.fromisoformat(last_time_iso) + timedelta(seconds=interval)
        if last_time_iso else datetime.now()
    )


def is_cookies_valid(cookie_str: str) -> bool:
    if not cookie_str or "=" not in cookie_str:
        return False

    parts = cookie_str.split(";")

    for part in parts:
        part = part.strip()
        if "=" not in part:
            return False

        key, value = part.split("=", 1)

        if not key or not value:
            return False

    return True


def is_token_valid(token: str) -> bool:
    if not re.match(r"^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$", token):
        return False
    try:
        header, payload, signature = token.split('.')
        for part in (header, payload, signature):
            padding = '=' * (-len(part) % 4)
            base64.urlsafe_b64decode(part + padding)
        return True
    except Exception:
        return False


def is_pl_account_working() -> tuple[bool, str]:
    try:
        config = sett.get("config")
        Account(
            cookies=config["playerok"]["api"]["cookies"],
            user_agent=config["playerok"]["api"]["user_agent"],
            requests_timeout=config["playerok"]["api"]["requests_timeout"],
            proxy=config["playerok"]["api"]["proxy"] or None
        ).get()
        return True, ""
    except BotCheckDetectedException:
        return False, "Р‘РѕС‚-РїСЂРѕРІРµСЂРєР° Р·Р°РјРµС‚РёР»Р° РїРѕРґРѕР·СЂРёС‚РµР»СЊРЅСѓСЋ Р°РєС‚РёРІРЅРѕСЃС‚СЊ РїСЂРё РїРѕРґРєР»СЋС‡РµРЅРёРё Рє Р°РєРєР°СѓРЅС‚Сѓ Playerok. Р§С‚РѕР±С‹ РїСЂРѕРґРѕР»Р¶РёС‚СЊ СЂР°Р±РѕС‚Сѓ, РІР°Рј РЅСѓР¶РЅРѕ СѓРєР°Р·Р°С‚СЊ Р°РєС‚СѓР°Р»СЊРЅС‹Рµ Cookie-РґР°РЅРЅС‹Рµ РІР°С€РµРіРѕ Р°РІС‚РѕСЂРёР·РѕРІР°РЅРЅРѕРіРѕ Playerok Р°РєРєР°СѓРЅС‚Р°."
    except:
        return False, ""


def is_pl_account_banned() -> bool:
    try:
        config = sett.get("config")
        acc = Account(
            cookies=config["playerok"]["api"]["cookies"],
            user_agent=config["playerok"]["api"]["user_agent"],
            requests_timeout=config["playerok"]["api"]["requests_timeout"],
            proxy=config["playerok"]["api"]["proxy"] or None
        ).get()
        return acc.profile.is_blocked
    except:
        return False


def is_user_agent_valid(ua: str) -> bool:
    if not ua or not (10 <= len(ua) <= 512):
        return False
    allowed_chars = string.ascii_letters + string.digits + string.punctuation + ' '
    return all(c in allowed_chars for c in ua)


def is_proxy_valid(proxy: str) -> bool:
    ip_pattern = r'(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)'
    pattern_ip_port = re.compile(
        rf'^{ip_pattern}\.{ip_pattern}\.{ip_pattern}\.{ip_pattern}:(\d+)$'
    )
    pattern_auth_ip_port = re.compile(
        rf'^[^:@]+:[^:@]+@{ip_pattern}\.{ip_pattern}\.{ip_pattern}\.{ip_pattern}:(\d+)$'
    )
    match = pattern_ip_port.match(proxy)
    if match:
        port = int(match.group(1))
        return 1 <= port <= 65535
    match = pattern_auth_ip_port.match(proxy)
    if match:
        port = int(match.group(1))
        return 1 <= port <= 65535
    return False


def is_proxy_working(proxy: str, test_url="https://playerok.com", timeout=10) -> bool:
    proxies = {
        "http": f"http://{proxy}",
        "https": f"http://{proxy}"
    }
    try:
        response = requests.get(test_url, proxies=proxies, timeout=timeout)
        return response.status_code < 404
    except Exception:
        return False


def is_tg_token_valid(token: str) -> bool:
    pattern = r'^\d{7,12}:[A-Za-z0-9_-]{35}$'
    return bool(re.match(pattern, token))


def is_tg_bot_exists() -> bool:
    try:
        config = sett.get("config")
        token = config["telegram"]["api"]["token"]
        proxy = config["telegram"]["api"]["proxy"]
        
        if proxy:
            proxies = {
                "http": f"http://{proxy}",
                "https": f"http://{proxy}",
            }
        else:
            proxies = None
        
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe", 
            proxies=proxies,
            timeout=5
        )
        
        data = response.json()
        return data.get("ok", False) is True and data.get("result", {}).get("is_bot", False) is True
    except Exception:
        return False
    

def is_password_valid(password: str) -> bool:
    if len(password) < 6 or len(password) > 64:
        return False
    common_passwords = {
        "123456", "1234567", "12345678", "123456789", "password", "qwerty",
        "admin", "123123", "111111", "abc123", "letmein", "welcome",
        "monkey", "login", "root", "pass", "test", "000000", "user",
        "qwerty123", "iloveyou"
    }
    if password.lower() in common_passwords:
        return False
    return True


def configure_config():
    config = sett.get("config")

    needs_setup = (
        not config["playerok"]["api"]["cookies"] or
        not config["telegram"]["api"]["token"] or
        not config["telegram"]["bot"]["password"]
    )

    if needs_setup and not sys.stdin.isatty():
        print(
            f"\n{Fore.YELLOW}вљ пёЏ  Р‘РѕС‚ РЅРµ РЅР°СЃС‚СЂРѕРµРЅ!"
            f"\n{Fore.WHITE}РџРѕРґРєР»СЋС‡РёС‚РµСЃСЊ Рє СЃРµСЂРІРµСЂСѓ Рё РІС‹РїРѕР»РЅРёС‚Рµ РєРѕРјР°РЅРґСѓ:"
            f"\n\n   {Fore.CYAN}playerok-neverboost setup"
            f"\n\n{Fore.WHITE}Р­С‚Рѕ Р·Р°РїСѓСЃС‚РёС‚ РёРЅС‚РµСЂР°РєС‚РёРІРЅСѓСЋ РЅР°СЃС‚СЂРѕР№РєСѓ РїСЂСЏРјРѕ РІ С‚РµСЂРјРёРЅР°Р»Рµ.\n"
        )
        sys.exit(0)

    while not config["playerok"]["api"]["cookies"] :
        while not config["playerok"]["api"]["cookies"]:
            print(
                f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ Р’РІРµРґРёС‚Рµ {Fore.YELLOW}Cookie-Р”Р°РЅРЅС‹Рµ {Fore.LIGHTYELLOW_EX}в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
                f"\n\n  РђРІС‚РѕСЂРёР·СѓР№С‚РµСЃСЊ РІ СЃРІРѕР№ Р°РєРєР°СѓРЅС‚ РЅР° Playerok, Р° РїРѕСЃР»Рµ СЃРєРѕРїРёСЂСѓР№С‚Рµ РєСѓРєРё СЃ РїРѕРјРѕС‰СЊСЋ СЂР°СЃС€РёСЂРµРЅРёСЏ Cookie-Editor"
                f"\n  (Р›РљРњ РЅР° СЂР°СЃС€РёСЂРµРЅРёРµ в†’ Export в†’ Header String)"
                f"\n\n  {Fore.LIGHTWHITE_EX}В· РџСЂРёРјРµСЂ: {Fore.WHITE}__ddg3=YOUR_COOKIE_VALUE;token=YOUR_PLAYEROK_TOKEN"
            )
            str_cookies = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()
            cookies = {
                c.split("=")[0].strip(): c.split("=")[1].strip() for c
                in str_cookies.split(";") if c.strip() and "=" in c
            }
            
            if is_cookies_valid(str_cookies) and is_token_valid(cookies["token"]):
                config["playerok"]["api"]["cookies"] = str_cookies
                sett.set("config", config)
                print(f"\n{Fore.YELLOW}Cookie-РґР°РЅРЅС‹Рµ СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅРµРЅС‹ РІ РєРѕРЅС„РёРі.")
            else:
                print(
                    f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РІС‹ РІРІРµР»Рё РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Рµ Cookie-РґР°РЅРЅС‹Рµ. "
                    f"РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РѕРЅРё СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·."
                )

        while not config["playerok"]["api"]["user_agent"]:
            print(
                f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ Р’РІРµРґРёС‚Рµ {Fore.LIGHTMAGENTA_EX}Р®Р·РµСЂ-Р°РіРµРЅС‚ {Fore.LIGHTYELLOW_EX}в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
                f"\n\n  Р•РіРѕ РјРѕР¶РЅРѕ СЃРєРѕРїРёСЂРѕРІР°С‚СЊ РЅР° СЃР°Р№С‚Рµ https://whatmyuseragent.com"
                f"\n  {Fore.LIGHTWHITE_EX}РР»Рё РїСЂРѕРїСѓСЃС‚РёС‚Рµ СЌС‚Сѓ РЅР°СЃС‚СЂРѕР№РєСѓ, РЅР°Р¶Р°РІ Enter"
                f"\n\n  {Fore.LIGHTWHITE_EX}В· РџСЂРёРјРµСЂ: {Fore.WHITE}Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36..."
            )
            user_agent = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()
            
            if not user_agent:
                print(f"\n{Fore.WHITE}Р’С‹ РїСЂРѕРїСѓСЃС‚РёР»Рё РІРІРѕРґ Р®Р·РµСЂ-Р°РіРµРЅС‚Р°.")
                break
            if is_user_agent_valid(user_agent):
                config["playerok"]["api"]["user_agent"] = user_agent
                sett.set("config", config)
                print(f"\n{Fore.YELLOW}Р®Р·РµСЂ-Р°РіРµРЅС‚ СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅС‘РЅ РІ РєРѕРЅС„РёРі.")
            else:
                print(
                    f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РІС‹ РІРІРµР»Рё РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ Р®Р·РµСЂ-Р°РіРµРЅС‚. "
                    f"РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РІ РЅС‘Рј РЅРµС‚ СЂСѓСЃСЃРєРёС… СЃРёРјРІРѕР»РѕРІ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·."
                )
        
        while not config["playerok"]["api"]["proxy"]:
            print(
                f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ Р’РІРµРґРёС‚Рµ {Fore.LIGHTBLUE_EX}HTTP РїСЂРѕРєСЃРё {Fore.LIGHTYELLOW_EX}РґР»СЏ Playerok в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
                f"\n\n  Р¤РѕСЂРјР°С‚: user:password@ip:port, ip:port:user:password РёР»Рё ip:port"
                f"\n  {Fore.LIGHTWHITE_EX}РР»Рё РїСЂРѕРїСѓСЃС‚РёС‚Рµ СЌС‚Сѓ РЅР°СЃС‚СЂРѕР№РєСѓ, РЅР°Р¶Р°РІ Enter"
                f"\n\n  {Fore.LIGHTWHITE_EX}В· РџСЂРёРјРµСЂ: {Fore.WHITE}DRjcQTm3Yc:m8GnUN8Q9L@46.161.30.187:8000"
            )
            proxy = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()

            if proxy.count(":") == 3:
                ip, port, user, passwd = proxy.split(":")
                proxy = f"{user}:{passwd}@{ip}:{port}"
            
            if not proxy:
                print(f"\n{Fore.WHITE}Р’С‹ РїСЂРѕРїСѓСЃС‚РёР»Рё РІРІРѕРґ РїСЂРѕРєСЃРё.")
                break
            if is_proxy_valid(proxy):
                config["playerok"]["api"]["proxy"] = proxy
                sett.set("config", config)
                print(f"\n{Fore.YELLOW}РџСЂРѕРєСЃРё СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅС‘РЅ РІ РєРѕРЅС„РёРі.")
            else:
                print(
                    f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РІС‹ РІРІРµР»Рё РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ РџСЂРѕРєСЃРё. "
                    f"РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РѕРЅ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·."
                )

    while not config["telegram"]["api"]["token"]:
        while not config["telegram"]["api"]["token"]:
            print(
                f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ Р’РІРµРґРёС‚Рµ {Fore.CYAN}РўРѕРєРµРЅ Telegram Р±РѕС‚Р° {Fore.LIGHTYELLOW_EX}в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
                f"\n\n  {Fore.WHITE}Р‘РѕС‚Р° РЅСѓР¶РЅРѕ СЃРѕР·РґР°С‚СЊ Сѓ @BotFather (https://t.me/BotFather)"
                f"\n\n  {Fore.LIGHTWHITE_EX}В· РџСЂРёРјРµСЂ: {Fore.WHITE}1234567890:YOUR_TELEGRAM_BOT_TOKEN"
            )
            token = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()
            
            if is_tg_token_valid(token):
                config["telegram"]["api"]["token"] = token
                sett.set("config", config)
                print(f"\n{Fore.YELLOW}РўРѕРєРµРЅ Telegram Р±РѕС‚Р° СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅС‘РЅ РІ РєРѕРЅС„РёРі.")
            else:
                print(
                    f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РІС‹ РІРІРµР»Рё РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ С‚РѕРєРµРЅ. "
                    f"РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РѕРЅ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·."
                )

        while not config["telegram"]["api"]["proxy"]:
            print(
                f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ Р’РІРµРґРёС‚Рµ {Fore.LIGHTBLUE_EX}HTTP РїСЂРѕРєСЃРё {Fore.LIGHTYELLOW_EX}РґР»СЏ Telegram в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
                f"\n\n  Р¤РѕСЂРјР°С‚: user:password@ip:port, ip:port:user:password РёР»Рё ip:port"
                f"\n  {Fore.LIGHTWHITE_EX}РР»Рё РїСЂРѕРїСѓСЃС‚РёС‚Рµ СЌС‚Сѓ РЅР°СЃС‚СЂРѕР№РєСѓ, РЅР°Р¶Р°РІ Enter"
                f"\n\n  {Fore.LIGHTWHITE_EX}В· РџСЂРёРјРµСЂ: {Fore.WHITE}DRjcQTm3Yc:m8GnUN8Q9L@46.161.30.187:8000"
            )
            proxy = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()

            if proxy.count(":") == 3:
                ip, port, user, passwd = proxy.split(":")
                proxy = f"{user}:{passwd}@{ip}:{port}"
            
            if not proxy:
                print(f"\n{Fore.WHITE}Р’С‹ РїСЂРѕРїСѓСЃС‚РёР»Рё РІРІРѕРґ РїСЂРѕРєСЃРё.")
                break
            if is_proxy_valid(proxy):
                config["telegram"]["api"]["proxy"] = proxy
                sett.set("config", config)
                print(f"\n{Fore.YELLOW}РџСЂРѕРєСЃРё СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅС‘РЅ РІ РєРѕРЅС„РёРі.")
            else:
                print(
                    f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РІС‹ РІРІРµР»Рё РЅРµРєРѕСЂСЂРµРєС‚РЅС‹Р№ РїСЂРѕРєСЃРё. "
                    f"РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РѕРЅ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·."
                )

    while not config["telegram"]["bot"]["password"]:
        print(
            f"\n{Fore.LIGHTYELLOW_EX}в”Њв”Ђв”Ђв”Ђв”Ђв”¤ РџСЂРёРґСѓРјР°Р№С‚Рµ {Fore.YELLOW}РџР°СЂРѕР»СЊ РґР»СЏ Telegram Р±РѕС‚Р° {Fore.LIGHTYELLOW_EX}в”њв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”Ђв”ђ{Fore.WHITE}"
            f"\n\n  Р‘РѕС‚ Р±СѓРґРµС‚ Р·Р°РїСЂР°С€РёРІР°С‚СЊ РµРіРѕ РїСЂРё РєР°Р¶РґРѕР№ РЅРѕРІРѕР№ РїРѕРїС‹С‚РєРµ РІР·Р°РёРјРѕРґРµР№СЃС‚РІРёСЏ С‡СѓР¶РѕРіРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ"
            f"\n\n  {Fore.LIGHTWHITE_EX}В· Р’Р°Р¶РЅРѕ: {Fore.WHITE}РџР°СЂРѕР»СЊ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ СЃР»РѕР¶РЅС‹Рј, РґР»РёРЅРѕР№ РЅРµ РјРµРЅРµРµ 6 Рё РЅРµ Р±РѕР»РµРµ 64 СЃРёРјРІРѕР»РѕРІ"
        )
        password = input(f"  {Fore.WHITE}в†’ {Fore.LIGHTWHITE_EX}").strip()
        
        if is_password_valid(password):
            config["telegram"]["bot"]["password"] = password
            sett.set("config", config)
            print(f"\n{Fore.YELLOW}РџР°СЂРѕР»СЊ СѓСЃРїРµС€РЅРѕ СЃРѕС…СЂР°РЅС‘РЅ РІ РєРѕРЅС„РёРі.")
        else:
            print(f"\n{Fore.LIGHTRED_EX}Р’Р°С€ РїР°СЂРѕР»СЊ РЅРµ РїРѕРґС…РѕРґРёС‚. РЈР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ РѕРЅ СЃРѕРѕС‚РІРµС‚СЃС‚РІСѓРµС‚ С„РѕСЂРјР°С‚Сѓ Рё РЅРµ СЏРІР»СЏРµС‚СЃСЏ Р»С‘РіРєРёРј Рё РїРѕРїСЂРѕР±СѓР№С‚Рµ РµС‰С‘ СЂР°Р·.")
    
    logger.info("")
    
    if config["playerok"]["api"]["proxy"] and not is_proxy_working(config["playerok"]["api"]["proxy"]):
        print(
            f"\n{Fore.LIGHTRED_EX}РџРѕС…РѕР¶Рµ, С‡С‚Рѕ РїСЂРѕРєСЃРё РґР»СЏ Playerok Р°РєРєР°СѓРЅС‚Р° РЅРµ СЂР°Р±РѕС‚Р°РµС‚. "
            f"РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїСЂРѕРІРµСЂСЊС‚Рµ РµРіРѕ Рё РІРІРµРґРёС‚Рµ СЃРЅРѕРІР°."
        )
        
        config["playerok"]["api"]["cookies"] = ""
        config["playerok"]["api"]["user_agent"] = ""
        config["playerok"]["api"]["proxy"] = ""
        sett.set("config", config)
        
        return configure_config()
    elif config["playerok"]["api"]["proxy"]:
        logger.info(f"{Fore.LIGHTYELLOW_EX}Playerok РїСЂРѕРєСЃРё СѓСЃРїРµС€РЅРѕ СЂР°Р±РѕС‚Р°РµС‚.")

    is_pl_acc_working, reason = is_pl_account_working()
    if not is_pl_acc_working:
        reason = reason if reason else "РќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРєР»СЋС‡РёС‚СЊСЃСЏ Рє РІР°С€РµРјСѓ Playerok Р°РєРєР°СѓРЅС‚Сѓ. РџРѕР¶Р°Р»СѓР№СЃС‚Р°, СѓР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ Сѓ РІР°СЃ СѓРєР°Р·Р°РЅС‹ РІРµСЂРЅС‹Рµ cookie-РґР°РЅРЅС‹Рµ Рё РІРІРµРґРёС‚Рµ РёС… СЃРЅРѕРІР°."
        print(f"\n{Fore.LIGHTRED_EX}{reason}")
        
        config["playerok"]["api"]["cookies"] = ""
        config["playerok"]["api"]["user_agent"] = ""
        config["playerok"]["api"]["proxy"] = ""
        sett.set("config", config)
        
        return configure_config()
    else:
        logger.info(f"{Fore.LIGHTYELLOW_EX}Playerok Р°РєРєР°СѓРЅС‚ СѓСЃРїРµС€РЅРѕ Р°РІС‚РѕСЂРёР·РѕРІР°РЅ.")

    if is_pl_account_banned():
        print(
            f"{Fore.LIGHTRED_EX}\nР’Р°С€ Playerok Р°РєРєР°СѓРЅС‚ Р·Р°Р±Р°РЅРµРЅ! "
            f"РЈРІС‹, СЏ РЅРµ РјРѕРіСѓ Р·Р°РїСѓСЃС‚РёС‚СЊ Р±РѕС‚Р° РЅР° Р·Р°Р±Р»РѕРєРёСЂРѕРІР°РЅРЅРѕРј Р°РєРєР°СѓРЅС‚Рµ..."
        )
        
        config["playerok"]["api"]["cookies"] = ""
        config["playerok"]["api"]["user_agent"] = ""
        config["playerok"]["api"]["proxy"] = ""
        sett.set("config", config)
        
        return configure_config()

    if config["telegram"]["api"]["proxy"] and not is_proxy_working(
        config["telegram"]["api"]["proxy"], 
        "https://api.telegram.org/"
    ):
        print(
            f"{Fore.LIGHTRED_EX}\nРџРѕС…РѕР¶Рµ, С‡С‚Рѕ РїСЂРѕРєСЃРё РґР»СЏ Telegram Р±РѕС‚Р° РЅРµ СЂР°Р±РѕС‚Р°РµС‚. "
            f"РџРѕР¶Р°Р»СѓР№СЃС‚Р°, РїСЂРѕРІРµСЂСЊС‚Рµ РµРіРѕ Рё РІРІРµРґРёС‚Рµ СЃРЅРѕРІР°."
        )
        
        config["telegram"]["api"]["token"] = ""
        config["telegram"]["api"]["proxy"] = ""
        sett.set("config", config)
        
        return configure_config()
    elif config["telegram"]["api"]["proxy"]:
        logger.info(f"{Fore.LIGHTYELLOW_EX}Telegram РїСЂРѕРєСЃРё СѓСЃРїРµС€РЅРѕ СЂР°Р±РѕС‚Р°РµС‚.")

    if not is_tg_bot_exists():
        print(
            f"{Fore.LIGHTRED_EX}\nРќРµ СѓРґР°Р»РѕСЃСЊ РїРѕРґРєР»СЋС‡РёС‚СЊСЃСЏ Рє РІР°С€РµРјСѓ Telegram Р±РѕС‚Сѓ. "
            f"Р•СЃР»Рё РІС‹ РЅР°С…РѕРґРёС‚РµСЃСЊ РЅР° С‚РµСЂСЂРёС‚РѕСЂРёРё Р РѕСЃСЃРёРё, РІР°Рј РЅСѓР¶РЅРѕ РїРѕРґРєР»СЋС‡РёС‚СЊ РїСЂРѕРєСЃРё Рє Telegram Р±РѕС‚Сѓ РёР»Рё РёСЃРїРѕР»СЊР·РѕРІР°С‚СЊ VPN, РІ РІРёРґСѓ Р±Р»РѕРєРёСЂРѕРІРѕРє СЃРѕ СЃС‚РѕСЂРѕРЅС‹ Р РљРќ."
        )
        config["telegram"]["api"]["token"] = ""
        config["telegram"]["api"]["proxy"] = ""
        sett.set("config", config)
        
        return configure_config()
    else:
        logger.info(f"{Fore.LIGHTYELLOW_EX}Telegram Р±РѕС‚ СѓСЃРїРµС€РЅРѕ СЂР°Р±РѕС‚Р°РµС‚.")


def get_stats():
    cached_orders = data.get("cached_orders")

    now = datetime.now(pytz.timezone("Europe/Moscow"))
    day_ago = now - timedelta(days=1)
    week_ago = now - timedelta(days=7)
    month_ago = now - timedelta(days=30)

    day_orders = [o for o in cached_orders.values() if datetime.fromisoformat(o["date"]) >= day_ago]
    week_orders = [o for o in cached_orders.values() if datetime.fromisoformat(o["date"]) >= week_ago]
    month_orders = [o for o in cached_orders.values() if datetime.fromisoformat(o["date"]) >= month_ago]
    all_orders = list(cached_orders.values())

    day_active = [o for o in day_orders if not o["status"].startswith("CONFIRMED") and not o["status"].startswith("ROLLED_BACK")]
    week_active = [o for o in week_orders if not o["status"].startswith("CONFIRMED") and not o["status"].startswith("ROLLED_BACK")]
    month_active = [o for o in month_orders if not o["status"].startswith("CONFIRMED") and not o["status"].startswith("ROLLED_BACK")]
    all_active = [o for o in all_orders if not o["status"].startswith("CONFIRMED") and not o["status"].startswith("ROLLED_BACK")]

    day_completed = [o for o in day_orders if o["status"].startswith("CONFIRMED")]
    week_completed = [o for o in week_orders if o["status"].startswith("CONFIRMED")]
    month_completed = [o for o in month_orders if o["status"].startswith("CONFIRMED")]
    all_completed = [o for o in all_orders if o["status"].startswith("CONFIRMED")]

    day_refunded = [o for o in day_orders if o["status"].startswith("ROLLED_BACK")]
    week_refunded = [o for o in week_orders if o["status"].startswith("ROLLED_BACK")]
    month_refunded = [o for o in month_orders if o["status"].startswith("ROLLED_BACK")]
    all_refunded = [o for o in all_orders if o["status"].startswith("ROLLED_BACK")]

    day_profit = round(sum(o["price"] for o in day_orders if o["status"].startswith("CONFIRMED")), 2)
    week_profit = round(sum(o["price"] for o in week_orders if o["status"].startswith("CONFIRMED")), 2)
    month_profit = round(sum(o["price"] for o in month_orders if o["status"].startswith("CONFIRMED")), 2)
    all_profit = round(sum(o["price"] for o in all_orders if o["status"].startswith("CONFIRMED")), 2)

    day_best = Counter(o["item_name"] for o in day_orders).most_common(1)[0][0] if day_orders else "-"
    week_best = Counter(o["item_name"] for o in week_orders).most_common(1)[0][0] if day_orders else "-"
    month_best = Counter(o["item_name"] for o in month_orders).most_common(1)[0][0] if day_orders else "-"
    all_best = Counter(o["item_name"] for o in all_orders).most_common(1)[0][0] if day_orders else "-"

    return {
        "day": {
            "orders": len(day_orders),
            "active": len(day_active),
            "completed": len(day_completed),
            "refunded": len(day_refunded),
            "profit": day_profit,
            "best": day_best
        },
        "week": {
            "orders": len(week_orders),
            "active": len(week_active),
            "completed": len(week_completed),
            "refunded": len(week_refunded),
            "profit": week_profit,
            "best": week_best
        },
        "month": {
            "orders": len(month_orders),
            "active": len(month_active),
            "completed": len(month_completed),
            "refunded": len(month_refunded),
            "profit": month_profit,
            "best": month_best
        },
        "all": {
            "orders": len(all_orders),
            "active": len(all_active),
            "completed": len(all_completed),
            "refunded": len(all_refunded),
            "profit": all_profit,
            "best": all_best
        }
    }
