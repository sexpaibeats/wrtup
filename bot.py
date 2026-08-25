#!/usr/bin/env python3
import asyncio
import html
import json
import logging
import os
import re
import socket
import struct
import subprocess
import shlex
import time
from collections import namedtuple
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote

try:
    import fcntl
except ImportError:
    fcntl = None

import aiohttp
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

try:
    import asyncssh
    ASYNCSSH_AVAILABLE = True
except ImportError:
    ASYNCSSH_AVAILABLE = False

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8912794808:AAF4ubk18sOApVQT4aJRbAcJCpxMwGEA468")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "7400895852"))
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "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")

# Уровень логирования (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()

# Интерфейс, через который бот обязан ходить в интернет (br-vpnnet на роутере,
# на Android/Termux интерфейса не будет — код сам откатится на системный маршрут).
VPN_IFACE = os.environ.get("VPN_IFACE", "br-vpnnet")
# Резервный интерфейс на случай падения VPN. Пусто = системный маршрут по умолчанию (WAN/LAN).
FALLBACK_IFACE = os.environ.get("FALLBACK_IFACE", "")

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "wrtrelease")
CONFIG_FILE = os.environ.get("CONFIG_FILE", "bot_config.json")

DEFAULT_OZON_COOKIE = "abt_data=7.u7LYCjte22xEN02AlCKwd5Oyhxd6x8cUJAr4V91dm9GGnEjgsQy9_p8GzqORFahJz4psu3AINRYjjo0EsGcF-_SjMAj5xRuuk_sj0KGy7brEH6Jxfo3qSlVEZdM1rD7nMsAIbOPMwGbdaQ_3I2WXg_yC8wi9Cb9EnbrEjCK9BuFWjR26EDoIf-daTiSLwerFpj7gbipZBYrzMbw12l-0sLRcLPpYzaCsA3DnU_7nWRNxPFKA1cvYrV7qnYhwCOkjmmwIE5uHSpv_CRZElrzZBYejv7avV7xF97q21ZZYg50ccc-jUxeI8m9poaFsXKZ3jbQUTkTWRVmvUb9N0CIUuoSU6SqPBG2f0kXSs6OvRRbUz5t4bzD8KbpvztAaRijQhK1zof3-0YjsugoKWgP2ylV05PRwtOxTYCgtj8xEfQmbNphJMmo-ZSgLwmXPlA6GlCgVsk8cEhfC1jp8DosXGZ-ra3fL_YfiE5a6-U3WBWF_W07-QP79fXNetVQBhjoT9yL9yVDV6SP5laGy7DCvtko2534l3pfoZw-0oESX6yh5imFH_pcQYwPziQhvck_ITq7q6filTg1tspC61nIg9H7zGjN8Nhx-FhWceEqVZ37rCK8yY-EQaENYz8Pkd2DHrYoQFTiFUyRlZ38P6SWwIMDvTCLFWXzRANy_yfDE0hUJBZbyfVXYK1VMfC2_W_ocGqAlEOhqLv4PSrtk5iYwZcRkTBkWhXBPtrY3LracaBKBKFnwnmh2V96K5LQNZSWUXggI39HfSXRTHYQ1aSFamiz8bEuCZnXYKtzpfgUG; __Secure-ETC=51be9c52067035b904d6a9f1a2ff3334; __Secure-ext_xcid=23467ed16204e1aa96b4f33019ab8117; __Secure-access-token=12.240533142.FaOU74m_T9KflhRFoxY3Vw.96.ATbZRAR7rsotlhP3Emj6iRyb_F1OgtCDsH66W5zrf9f1q3wGiI_t1tMV_f5cF_9KrAXAak_BUqPwb6InuUOubONNKgtgK9SSkR19bSF4gKa1Cw5iOdLoT5QksZTk-JPa4Zlb0psjvTGMgcBSRnBbE8w.20260123022020.20260820195919.1.R_BFerU1DZv_iSCjqOuuPhMnE7iQbCND_iacZ0mPQoE.1b5dfdb8d171cd95; __Secure-refresh-token=12.240533142.FaOU74m_T9KflhRFoxY3Vw.96.ATbZRAR7rsotlhP3Emj6iRyb_F1OgtCDsH66W5zrf9f1q3wGiI_t1tMV_f5cF_9KrAXAak_BUqPwb6InuUOubONNKgtgK9SSkR19bSF4gKa1Cw5iOdLoT5QksZTk-JPa4Zlb0psjvTGMgcBSRnBbE8w.20260123022020.20260820195919.1.V_7vjA2cotPS3tyS8KU4O9fT4cZnQ00M9pLcLKafcsQ.1469b87219b2b6ef2; __Secure-ab-group=96; __Secure-user-id=240533142; xcid=09458079309c7f6c4be7dc52499c287c; TSDK_trackerSessionId=f74f1fd4-b162-8d0e-1fc3; X-O3-INGRESSCOOKIE=3ab20fee47ca969f52360801066bfb45|606b83e93604e880112d5da09185637f"

DEFAULT_CONFIG: Dict[str, Any] = {
    "check_interval": 300,
    "github_releases": [
        {"repo": "ushan0v/forkop", "filter": "", "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""},
        {"repo": "itdoginfo/podkop", "filter": "", "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""},
        {"repo": "SagerNet/sing-box", "filter": "", "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""},
        {"repo": "thaw-app/Thaw", "filter": r"macos|\.dmg|\.pkg", "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""},
    ],
    "github_commits": [
        {"repo": "MetaCubeX/meta-rules-dat", "branch": "sing", "path": "geo/geosite/category-ru.srs", "last_ver": "", "last_url": "", "last_cl": ""},
        {"repo": "Homebrew/homebrew-core", "branch": "", "path": "", "last_ver": "", "last_url": "", "last_cl": ""},
    ],
    "glinet": {
        "mt6000": {
            "stable": {"version": "", "date": "", "url": "", "hash": "", "changelog": ""},
            "openwrt25": {"version": "", "date": "", "url": "", "hash": "", "changelog": ""}
        }
    },
    "ssh": {"host": "192.168.8.1", "user": "root", "password": "", "port": 22},
    "package_tracking": {},
    "ozon_cookie": DEFAULT_OZON_COOKIE
}

router = Router()
cfg: Dict[str, Any] = {}

Net = namedtuple("Net", ["vpn", "fb", "vpn_ip", "fb_ip"])

# ================= УПРАВЛЕНИЕ АКТИВНЫМИ ЗАДАЧАМИ =================
sysinfo_task_ref: Optional[asyncio.Task] = None
ssh_session_active: bool = False
active_ssh_proc = None

async def cancel_tasks():
    global sysinfo_task_ref, ssh_session_active, active_ssh_proc
    if sysinfo_task_ref:
        sysinfo_task_ref.cancel()
        sysinfo_task_ref = None
    ssh_session_active = False
    
    if active_ssh_proc:
        try:
            if hasattr(active_ssh_proc, 'kill'): active_ssh_proc.kill()
            elif hasattr(active_ssh_proc, 'terminate'): active_ssh_proc.terminate()
            elif hasattr(active_ssh_proc, 'close'): active_ssh_proc.close()
        except Exception:
            pass
            
        # АНТИ-УТЕЧКА ПАМЯТИ: Дожидаемся завершения процесса, чтобы не плодить Zombie-процессы на роутере
        if hasattr(active_ssh_proc, 'wait'):
            try:
                await asyncio.wait_for(active_ssh_proc.wait(), timeout=1.0)
            except Exception:
                pass
        active_ssh_proc = None

# ================= ЖИВОЙ ЛОГ В TELEGRAM =================
log_queue: asyncio.Queue = asyncio.Queue()
log_buffer = ""
log_message_id: Optional[int] = None
LOG_LIMIT = 3000

class TelegramLogHandler(logging.Handler):
    def emit(self, record):
        try:
            log_queue.put_nowait(self.format(record))
        except Exception:
            pass

numeric_log_level = getattr(logging, LOG_LEVEL, logging.INFO)

logging.basicConfig(level=numeric_log_level, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger()
logger.setLevel(numeric_log_level)

tg_handler = TelegramLogHandler()
tg_handler.setLevel(numeric_log_level)
tg_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
logger.addHandler(tg_handler)

async def init_log_window(bot: Bot):
    global log_message_id
    try:
        msg = await bot.send_message(ADMIN_ID, "📝 <b>Live Log Window</b>\n<pre>Инициализация...</pre>")
        log_message_id = msg.message_id
        try:
            await bot.pin_chat_message(ADMIN_ID, msg.message_id, disable_notification=True)
        except Exception:
            pass
    except Exception as e:
        logging.error(f"Не удалось создать окно логов: {e}")

async def log_updater_task(bot: Bot):
    global log_buffer, log_message_id
    while True:
        try:
            updated = False
            while not log_queue.empty():
                log_buffer += log_queue.get_nowait() + "\n"
                updated = True

            if updated:
                if len(log_buffer) > LOG_LIMIT:
                    log_buffer = log_buffer[-LOG_LIMIT:]
                    idx = log_buffer.find("\n")
                    if idx != -1:
                        log_buffer = log_buffer[idx + 1:]

                safe_log = html.escape(log_buffer.strip()) or "…"
                text = f"📝 <b>Live Log Window</b>\n<pre>{safe_log}</pre>"

                if log_message_id:
                    try:
                        await bot.edit_message_text(chat_id=ADMIN_ID, message_id=log_message_id, text=text)
                    except TelegramRetryAfter as e:
                        await asyncio.sleep(e.retry_after)
                    except TelegramBadRequest as e:
                        if "message is not modified" not in str(e):
                            log_message_id = None
                    except Exception:
                        log_message_id = None

                if not log_message_id:
                    try:
                        msg = await bot.send_message(ADMIN_ID, text)
                        log_message_id = msg.message_id
                    except Exception:
                        pass
        except Exception as e:
            # Предотвращает падение цикла обработки логов из-за сетевых сбоев
            pass
            
        await asyncio.sleep(3)

# ================= КОНФИГ =================
def normalize_config():
    for it in cfg.get("github_releases", []):
        it.setdefault("filter", "")
        it.setdefault("last_ver", "")
        it.setdefault("last_ver_display", "")
        it.setdefault("last_url", "")
        it.setdefault("last_cl", "")
    for it in cfg.get("github_commits", []):
        it.setdefault("path", "")
        it.setdefault("branch", "")
        it.setdefault("last_ver", "")
        it.setdefault("last_url", "")
        it.setdefault("last_cl", "")
    
    if "glinet" not in cfg or isinstance(cfg.get("glinet"), list):
        cfg["glinet"] = {
            "mt6000": {
                "stable": {"version": "", "date": "", "url": "", "hash": "", "changelog": ""},
                "openwrt25": {"version": "", "date": "", "url": "", "hash": "", "changelog": ""}
            }
        }
    else:
        for model, branches in cfg["glinet"].items():
            for branch, data in branches.items():
                data.setdefault("version", "")
                data.setdefault("date", "")
                data.setdefault("url", "")
                data.setdefault("hash", "")
                data.setdefault("changelog", "")
                
    if "ozon_tracking" in cfg:
        cfg["package_tracking"] = cfg.pop("ozon_tracking")
    if "package_tracking" not in cfg:
        cfg["package_tracking"] = {}
    
    for track, data in cfg["package_tracking"].items():
        if "status" in data:
            data["last_event"] = data.pop("status")
            data["last_moment"] = ""
        data.setdefault("last_event", "")
        data.setdefault("last_moment", "")
        data.setdefault("history", [])
                
    cfg.setdefault("check_interval", 300)
    cfg.setdefault("ssh", {"host": "192.168.8.1", "user": "root", "password": "", "port": 22})
    cfg.setdefault("ozon_cookie", DEFAULT_OZON_COOKIE)

import sqlite3

DB_FILE = os.environ.get("DB_FILE", "bot_database.db")

def init_db():
    conn = sqlite3.connect(DB_FILE)
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    return conn

def load_config():
    global cfg
    init_db()
    
    if os.path.exists(CONFIG_FILE) and not os.path.exists(CONFIG_FILE + ".migrated"):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                cfg_old = json.load(f)
            conn = sqlite3.connect(DB_FILE)
            for k, v in cfg_old.items():
                conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
            conn.commit()
            conn.close()
            os.rename(CONFIG_FILE, CONFIG_FILE + ".migrated")
            logging.info("Миграция JSON -> SQLite завершена.")
        except Exception as e:
            logging.error(f"Ошибка миграции: {e}")

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.execute("SELECT key, value FROM config")
        for row in cursor:
            cfg[row[0]] = json.loads(row[1])
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка загрузки из SQLite: {e}")
        
    normalize_config()
    save_config()

def save_config():
    try:
        conn = sqlite3.connect(DB_FILE)
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA journal_mode = WAL")
        for k, v in cfg.items():
            conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (k, json.dumps(v, ensure_ascii=False)))
        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Ошибка сохранения в SQLite: {e}")

def get_gh_headers() -> dict:
    headers = {"User-Agent": "WrtReleaseBot/9.0", "Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers

# ================= СЕТЬ =================
def get_iface_ip(ifname: str) -> Optional[str]:
    if not ifname or fcntl is None:
        return None
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            ip = socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x8915, 
                struct.pack("256s", ifname[:15].encode()),
            )[20:24])
            return ip
        finally:
            s.close()
    except Exception:
        return None

def resolve_ip(ifname: str) -> Optional[str]:
    return get_iface_ip(ifname) if ifname else None

async def open_net() -> Net:
    vpn_ip = resolve_ip(VPN_IFACE)
    fb_ip = resolve_ip(FALLBACK_IFACE)
    vpn_conn = aiohttp.TCPConnector(local_addr=(vpn_ip, 0) if vpn_ip else None, ttl_dns_cache=300)
    fb_conn = aiohttp.TCPConnector(local_addr=(fb_ip, 0) if fb_ip else None, ttl_dns_cache=300)
    return Net(
        vpn=aiohttp.ClientSession(connector=vpn_conn),
        fb=aiohttp.ClientSession(connector=fb_conn),
        vpn_ip=vpn_ip,
        fb_ip=fb_ip,
    )

async def close_net(net: Net):
    for s in (net.vpn, net.fb):
        try: await s.close()
        except Exception: pass

async def robust_request(net: Net, url: str, headers: Optional[dict] = None, as_json: bool = True, silent: bool = False, method: str = "GET", data: dict = None):
    last_err = None
    for sess in (net.vpn, net.fb):
        try:
            kwargs = {
                "headers": headers or {"User-Agent": "curl/7.68.0"},
                "timeout": aiohttp.ClientTimeout(total=12)
            }
            if method.upper() == "POST":
                kwargs["json"] = data
                req = sess.post(url, **kwargs)
            else:
                req = sess.get(url, **kwargs)

            async with req as resp:
                raw_text = await resp.text()
                if "api.github.com" not in url and not silent:
                    short_resp = (raw_text[:250] + '...') if len(raw_text) > 250 else raw_text
                    short_resp = short_resp.replace("\n", " ")
                    logging.info(f"🌐 [CONNECT] {method} {url} | Status: {resp.status} | Resp: {short_resp}")

                if resp.status == 200:
                    if as_json:
                        try:
                            return json.loads(raw_text)
                        except Exception as e:
                            if not silent: logging.error(f"Ошибка парсинга JSON [{url}]: {e}")
                            return None
                    return raw_text
                last_err = f"HTTP {resp.status}"
        except Exception as e:
            last_err = e
            
    if last_err and not silent:
        logging.error(f"Ошибка запроса [{url}]: {last_err}")
    return None

async def send_ntfy(net: Net, message: str, title: str = "Release Notification"):
    payload = message.encode("utf-8")[:4000]
    headers = {"Title": title, "Tags": "rocket", "Content-Type": "text/plain; charset=utf-8"}
    for sess in (net.fb, net.vpn):
        try:
            async with sess.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=payload, headers=headers,
                                  timeout=aiohttp.ClientTimeout(total=10)) as r:
                if r.status < 300: return True
        except Exception as e:
            logging.warning(f"ntfy недоступен по одному из маршрутов: {e}")
    logging.error("ntfy: все маршруты недоступны")
    return False

async def send_alert(bot: Bot, net: Net, text: str, ntfy_title: str = "Release Notification"):
    try:
        await bot.send_message(ADMIN_ID, text, disable_web_page_preview=True)
    except Exception as e:
        logging.warning(f"Telegram недоступен ({e}), фолбэк в ntfy")
        plain = re.sub(r"<[^>]+>", "", text)
        await send_ntfy(net, plain, ntfy_title)

async def send_long_messages(bot: Bot, messages: List[str]):
    buffer = ""
    for msg in messages:
        if len(buffer) + len(msg) > 4000:
            if buffer.strip():
                await bot.send_message(ADMIN_ID, buffer, disable_web_page_preview=True)
            buffer = msg + "\n\n"
        else:
            buffer += msg + "\n\n"
    if buffer.strip():
        await bot.send_message(ADMIN_ID, buffer, disable_web_page_preview=True)

def clean_changelog(cl_text: str) -> str:
    if not cl_text: return ""
    cl_text = html.unescape(cl_text)
    cl_text = cl_text.replace("\\n", "\n").replace("<br>", "\n").replace("<br/>", "\n")
    cl_text = re.sub(r"<[^>]+>", "", cl_text)
    cl_text = re.sub(r"\n{3,}", "\n\n", cl_text)
    return cl_text.strip()

def strip_ansi(text: str) -> str:
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    return ansi_escape.sub('', text)

# ================= СИСТЕМНЫЕ УТИЛИТЫ И SSH =================
_cached_hw_status = "N/A"
_last_hw_check = 0

def get_sysinfo_text(last_cpu: dict) -> str:
    global _cached_hw_status, _last_hw_check
    
    try:
        with open('/proc/uptime', 'r') as f:
            up = float(f.read().split()[0])
        uptime = f"{int(up//86400)}d {int((up%86400)//3600)}h {int((up%3600)//60)}m"
    except Exception:
        uptime = "N/A"

    current_cpu = {}
    cpu_loads = []
    try:
        with open('/proc/stat', 'r') as f:
            for line in f:
                if line.startswith('cpu') and len(line.split()[0]) > 3:
                    parts = line.split()
                    name = parts[0]
                    idle = float(parts[4])
                    total = sum(float(x) for x in parts[1:])
                    current_cpu[name] = (idle, total)
                    
                    if name in last_cpu:
                        prev_idle, prev_total = last_cpu[name]
                        idle_delta = idle - prev_idle
                        total_delta = total - prev_total
                        if total_delta > 0:
                            load = 100.0 * (1.0 - idle_delta / total_delta)
                            cpu_loads.append(f"🖥 <b>{name.upper()}:</b> {load:.1f}%")
                    else:
                        cpu_loads.append(f"🖥 <b>{name.upper()}:</b> Вычисление...")
    except Exception:
        cpu_loads.append("Нет данных о CPU")
        
    last_cpu.clear()
    last_cpu.update(current_cpu)

    mem_total = mem_free = 0
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if 'MemTotal' in line: mem_total = int(line.split()[1])
                if 'MemAvailable' in line: mem_free = int(line.split()[1])
        mem_usage = 100.0 * (1.0 - mem_free / mem_total) if mem_total else 0
    except Exception:
        mem_usage = 0

    temp = "N/A"
    for path in ['/sys/class/thermal/thermal_zone0/temp', '/sys/devices/virtual/thermal/thermal_zone0/temp']:
        try:
            with open(path, 'r') as f:
                temp = f"{int(f.read().strip()) / 1000:.1f}°C"
                break
        except Exception:
            continue

    try:
        st = os.statvfs('/')
        free_mb = (st.f_bavail * st.f_frsize) / (1024*1024)
        total_mb = (st.f_blocks * st.f_frsize) / (1024*1024)
        disk = f"{free_mb:.1f} MB из {total_mb:.1f} MB"
    except Exception:
        disk = "N/A"

    wed_status = "N/A"
    try:
        # ОПТИМИЗАЦИЯ OPENWRT: Отказ от `subprocess.check_output('lsmod')` 
        # Это предотвращает нагрузку CPU на роутере каждые 3 секунды.
        with open('/proc/modules', 'r') as f:
            wed_status = "✅ Включено (Модуль активен)" if "mtk_wed" in f.read() else "❌ Выключено"
    except Exception:
        pass

    # ОПТИМИЗАЦИЯ OPENWRT: Кэшируем команду uci на 60 секунд.
    if time.time() - _last_hw_check > 60:
        try:
            hw_out = subprocess.check_output(['uci', 'get', 'firewall.@defaults[0].flow_offloading_hw'], stderr=subprocess.DEVNULL).decode().strip()
            _cached_hw_status = "✅ Включено" if hw_out == "1" else "❌ Выключено"
        except Exception:
            _cached_hw_status = "N/A"
        _last_hw_check = time.time()

    text = (
        f"📊 <b>Системный Монитор (GL-MT6000)</b>\n"
        f"──────────────────\n"
        f"⏱ <b>Uptime:</b> <code>{uptime}</code>\n"
        f"🌡 <b>Температура SoC:</b> <code>{temp}</code>\n"
        f"💾 <b>Загрузка RAM:</b> <code>{mem_usage:.1f}%</code>\n"
        f"💽 <b>Свободно памяти (/):</b> <code>{disk}</code>\n"
        f"──────────────────\n"
        f"⚡ <b>HW Offload:</b> {_cached_hw_status}\n"
        f"🚀 <b>WED (Wifi Dispatcher):</b> {wed_status}\n"
        f"──────────────────\n"
        f"🧠 <b>Нагрузка ядер:</b>\n" + "\n".join(cpu_loads)
    )
    return text

async def sysinfo_updater(bot: Bot, chat_id: int, message_id: int):
    last_cpu = {}
    try:
        while True:
            text = get_sysinfo_text(last_cpu)
            try:
                await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id)
            except TelegramRetryAfter as e: await asyncio.sleep(e.retry_after)
            except TelegramBadRequest as e:
                if "message is not modified" not in str(e): break
            except Exception: pass
            await asyncio.sleep(3.5)
    except asyncio.CancelledError:
        pass

async def process_ssh_command(message: Message, bot: Bot):
    global active_ssh_proc
    c = cfg.get("ssh", {})
    host = c.get("host", "192.168.8.1")
    user = c.get("user", "root")
    pwd = c.get("password", "")
    port = c.get("port", 22)
    cmds = message.text
    
    kb_active = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть SSH", callback_data="ssh_close"),
         InlineKeyboardButton(text="🛑 Отмена", callback_data="ssh_cancel")]
    ])
    kb_idle = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Закрыть SSH", callback_data="ssh_close")]
    ])
    
    out_msg = await message.answer(f"⏳ Выполняю запрос...\n<pre>{html.escape(cmds[:100])}</pre>", reply_markup=kb_active)
    
    output_buffer = ""
    last_sent_buffer = ""
    last_update_time = time.time()
    conn = None
    
    local_host = socket.gethostname()
    prompt_str = f"{user}@{local_host}:~# " if host in ("127.0.0.1", "localhost", "0.0.0.0") else f"{user}@{host}:~# "
    
    async def update_msg(final=False):
        nonlocal output_buffer, out_msg, last_sent_buffer
        current_kb = kb_idle if final else kb_active
        if len(output_buffer) > 3500:
            try: await out_msg.edit_text(f"💻 <b>SSH Вывод (часть):</b>\n<pre>{html.escape(output_buffer)}</pre>")
            except Exception: pass
            output_buffer = ""
            last_sent_buffer = ""
            out_msg = await message.answer("⏳ Продолжение вывода...", reply_markup=current_kb)
            return

        safe_res = html.escape(output_buffer)
        if final:
            if safe_res and not safe_res.endswith("\n"): safe_res += "\n"
            safe_res += prompt_str
            header = "💻 <b>SSH Вывод:</b>"
        else:
            header = "💻 <b>SSH Вывод (⏳ Выполняется...):</b>"
            
        try:
            await out_msg.edit_text(f"{header}\n<pre>{safe_res or prompt_str}</pre>", reply_markup=current_kb)
            last_sent_buffer = output_buffer
        except TelegramBadRequest: pass

    try:
        if host in ("127.0.0.1", "localhost", "0.0.0.0"):
            active_ssh_proc = await asyncio.create_subprocess_shell(
                cmds, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
        elif ASYNCSSH_AVAILABLE:
            conn = await asyncssh.connect(host, username=user, password=pwd, port=port, known_hosts=None, client_keys=None)
            active_ssh_proc = await conn.create_process(cmds, stderr=asyncssh.STDOUT)
        else:
            ssh_opts = "-tt -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR"
            if pwd:
                cmd = f"sshpass -p {shlex.quote(pwd)} ssh {ssh_opts} -p {port} {user}@{host} {shlex.quote(cmds)}"
            else:
                cmd = f"ssh {ssh_opts} -p {port} {user}@{host} {shlex.quote(cmds)}"
            active_ssh_proc = await asyncio.create_subprocess_shell(
                cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
            )
        
        while active_ssh_proc:
            try:
                chunk = await asyncio.wait_for(active_ssh_proc.stdout.read(1024), timeout=1.0)
                if not chunk: break
                chunk_str = chunk.decode('utf-8', errors='replace') if isinstance(chunk, bytes) else str(chunk)
                chunk_str = chunk_str.replace('\r\n', '\n').replace('\r', '')
                chunk_str = strip_ansi(chunk_str)
                output_buffer += chunk_str
            except asyncio.TimeoutError:
                if hasattr(active_ssh_proc, 'returncode') and active_ssh_proc.returncode is not None: break
                if hasattr(active_ssh_proc, 'exit_status') and active_ssh_proc.exit_status is not None: break
            except Exception as e:
                logging.error(f"SSH Read Error: {e}")
                break
            
            if time.time() - last_update_time > 1.5 and output_buffer != last_sent_buffer:
                await update_msg(final=False)
                last_update_time = time.time()
                
        if active_ssh_proc and hasattr(active_ssh_proc, 'wait'):
            try: await asyncio.wait_for(active_ssh_proc.wait(), timeout=2.0)
            except Exception: pass

        output_buffer = output_buffer.replace("Pseudo-terminal will not be allocated because stdin is not a terminal.\n", "")
    except Exception as e:
        output_buffer += f"\n\n[Ошибка: {e}]"
        if "No such file" in str(e) and not ASYNCSSH_AVAILABLE:
            output_buffer += "\n💡 Убедитесь, что установлен ssh. В Termux: pkg install openssh sshpass"
    finally:
        active_ssh_proc = None
        if ASYNCSSH_AVAILABLE and conn: conn.close()
        await update_msg(final=True)

@router.callback_query(F.data == "ssh_cancel")
async def cb_ssh_cancel(call: CallbackQuery):
    global active_ssh_proc
    if call.from_user.id != ADMIN_ID: return
    if active_ssh_proc:
        try:
            if hasattr(active_ssh_proc, 'kill'): active_ssh_proc.kill()
            elif hasattr(active_ssh_proc, 'terminate'): active_ssh_proc.terminate()
            elif hasattr(active_ssh_proc, 'close'): active_ssh_proc.close()
        except Exception: pass
        if hasattr(active_ssh_proc, 'wait'):
            try: await asyncio.wait_for(active_ssh_proc.wait(), timeout=1.0)
            except Exception: pass
        await call.answer("🛑 Сигнал завершения (SIGKILL) отправлен!")
    else:
        await call.answer("Нет активной задачи для отмены")

@router.callback_query(F.data == "ssh_close")
async def cb_ssh_close(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    global ssh_session_active, active_ssh_proc
    ssh_session_active = False
    if active_ssh_proc:
        try:
            if hasattr(active_ssh_proc, 'kill'): active_ssh_proc.kill()
            elif hasattr(active_ssh_proc, 'terminate'): active_ssh_proc.terminate()
            elif hasattr(active_ssh_proc, 'close'): active_ssh_proc.close()
        except Exception: pass
        if hasattr(active_ssh_proc, 'wait'):
            try: await asyncio.wait_for(active_ssh_proc.wait(), timeout=1.0)
            except Exception: pass
    await call.message.edit_text("🔌 <b>SSH соединение закрыто.</b>\nДля открытия введите /ssh")
    await call.answer("Соединение прервано")


# ================= МОДУЛЬ OZON TRACKING (WAF BYPASS) =================
OZON_STATUS_MAP = {
    "Created": {"title": "Создан", "desc": "Мы получили заказ, продавец уже собирает его."},
    "TransferringToDelivery": {"title": "Передается в доставку", "desc": "Продавец собрал заказ и передаёт его в доставку. Обычно это занимает до 10 дней."},
    "WayToCity": {"title": "Заказ принят перевозчиком", "desc": "Он отвезёт заказ на таможню. Товары пройдут таможенное оформление в стране отправления и в стране назначения."},
    "ExportCustomsStart": {"title": "Заказ везут на таможню в стране отправления", "desc": "Обычно это занимает до 10 дней"},
    "ExportCustomsArrived": {"title": "Заказ привезли на таможню для экспортного таможенного оформления", "desc": "Скорость оформления зависит от загруженности таможни"},
    "ExportCustomsCleared": {"title": "Заказ покинул зону экспортного таможенного оформления", "desc": "Заказ спешит в страну назначения"},
    "ExportFlight": {"title": "Заказ привезли в страну назначения", "desc": "Его отвезут на таможенное оформление"},
    "ImportCustomsStart": {"title": "Заказ передан на импортное таможенное оформление", "desc": "Его готовят к оформлению"},
    "ImportCustomsProcessing": {"title": "Заказ проходит импортное таможенное оформление", "desc": "Скорость оформления зависит от загруженности таможни"},
    "ImportCustomsCleared": {"title": "Заказ выпущен импортной таможней", "desc": "Его готовят к отправке на сортировочный терминал. Обычно это занимает от 8 до 12 дней"},
    "SortingCenterArrived": {"title": "Заказ отправили на сортировочный терминал", "desc": "Его подготовят к доставке в город получателя"},
    "SortingCenterLeft": {"title": "Заказ покинул сортировочный терминал", "desc": "Его подготовили к доставке в город получателя"},
    "LocalDeliveryStart": {"title": "Заказ ожидает отправки в город получателя", "desc": "Скорость отправки зависит от загруженности склада"},
    "LocalDeliveryWay": {"title": "Заказ везут в город получателя", "desc": "Его доставят в сортировочный центр"},
    "LocalDelivery": {"title": "Заказ везут", "desc": "Мы сообщим, когда его доставят"},
    "ArrivedToCity": {"title": "Прибыл в город", "desc": "Заказ прибыл в город назначения и готовится к выдаче."},
    "Delivering": {"title": "Передан курьеру", "desc": "Курьер везет заказ по вашему адресу."},
    "ReadyForPickUp": {"title": "Заказ в пункте выдачи", "desc": "Успейте забрать его в течение 14 дней."},
    "Delivered": {"title": "Заказ получен в пункте выдачи", "desc": "Заказ успешно доставлен."},
    "Cancelled": {"title": "Отменен", "desc": "Заказ был отменен."},
    "Returning": {"title": "Возвращается отправителю", "desc": "Заказ возвращается на склад."},
    "Returned": {"title": "Возвращен", "desc": "Заказ успешно возвращен продавцу."}
}

def get_ozon_sortable_date(ev: dict) -> str:
    return str(ev.get("moment", ""))

def format_ozon_date(iso_str: str) -> str:
    if not iso_str: return ""
    try:
        part1 = iso_str.split('T')[0]
        part2 = iso_str.split('T')[1].split('.')[0].split('+')[0]
        y, m, d = part1.split('-')
        h, minute, s = part2.split(':')
        h_local = str((int(h) + 3) % 24).zfill(2)
        y_short = y[-2:]
        return f"{d}.{m}.{y_short}, {h_local}:{minute}"
    except Exception:
        return iso_str

async def fetch_ozon_tracking(net: Net, track_num: str) -> Optional[dict]:
    url_api = f"https://tracking.ozon.ru/p-api/ozon-track-bff/tracking/{track_num}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:154.0) Gecko/20100101 Firefox/154.0",
        "Accept": "application/json, text/plain, */*",
        "X-O3-App-Name": "tpl-ui-ozon-track",
        "X-O3-App-Version": "release/TPLAPI-6773",
        "Referer": "https://tracking.ozon.ru/?__rr=2",
        "Cookie": cfg.get("ozon_cookie", "")
    }
    
    def extract_tracking_data(data):
        if not data: return None
        if isinstance(data, dict):
            if "incidentId" in data:
                logging.error(f"[OZON] WAF Блокировка (Qrator). Cookie протухла или недействительна. Обновите через /ozon_cookie")
                return None
            if "items" in data and isinstance(data["items"], list):
                return data
            if "events" in data and isinstance(data["events"], list):
                return data
            for v in data.values():
                e = extract_tracking_data(v)
                if e: return e
        return None

    res = await robust_request(net, url_api, headers=headers, as_json=True, silent=True)
    tracking_data = extract_tracking_data(res)
    
    if tracking_data: 
        logging.info(f"[OZON-API] Успех: Прямой запрос с Cookie для {track_num}")
        return tracking_data
        
    logging.error(f"[OZON-API] Не удалось получить данные по треку {track_num}")
    return None

def build_ozon_message(track: str, tracking_data: dict, is_new_track: bool = False) -> str:
    events = tracking_data.get("items") or tracking_data.get("events") or []
    events.sort(key=get_ozon_sortable_date, reverse=True)
    if not events: return ""

    latest_event = events[0]
    raw_event_name = str(latest_event.get("event", "Unknown"))
    info = OZON_STATUS_MAP.get(raw_event_name, {"title": raw_event_name, "desc": ""})
    event_moment = format_ozon_date(latest_event.get("moment", ""))

    def format_short_date(iso_str):
        if not iso_str: return ""
        try:
            y, m, d = iso_str.split('T')[0].split('-')
            return f"{d}.{m}.{y[-2:]}"
        except: return ""

    d_begin = format_short_date(tracking_data.get("deliveryDateBegin", ""))
    d_end = format_short_date(tracking_data.get("deliveryDateEnd", ""))
    period = ""
    if d_begin and d_end:
        period = f"{d_begin} - {d_end}" if d_begin != d_end else d_begin
    elif d_begin: period = d_begin

    header = "✅ <b>Ozon Smart Parser:</b>\n" if is_new_track else "📦 <b>Ozon Отслеживание:</b>\n"
    msg = f"{header}Трек-номер <code>{track}</code>\n\n"
    if period:
        msg += f"🚚 <b>Ожидаемая доставка:</b> {period}\n\n"

    msg += f"🟢 <b>Текущий статус:</b> <b>{html.escape(info['title'])}</b>\n"
    msg += f"🕒 <b>Время:</b> <code>{html.escape(event_moment)}</code>\n"
    if info["desc"]: msg += f"💬 <i>{html.escape(info['desc'])}</i>\n"

    # Полный глобальный жизненный цикл Ozon
    lifecycle = [
        "Created", "TransferringToDelivery", "WayToCity", 
        "ExportCustomsStart", "ExportCustomsArrived", "ExportCustomsCleared", 
        "ExportFlight", "ImportCustomsStart", "ImportCustomsProcessing", 
        "ImportCustomsCleared", "SortingCenterArrived", "SortingCenterLeft", 
        "LocalDeliveryStart", "LocalDeliveryWay", "LocalDelivery", 
        "ReadyForPickUp", "Delivered"
    ]
        
    try:
        current_idx = lifecycle.index(raw_event_name)
        upcoming = lifecycle[current_idx+1:current_idx+4] # Ровно 3 следующих шага
    except ValueError:
        upcoming = []

    if upcoming:
        msg += "\n⏳ <b>Ожидаемые этапы:</b>\n"
        for st in upcoming:
            st_info = OZON_STATUS_MAP.get(st, {"title": st})
            msg += f" 🔹 <i>{html.escape(st_info['title'])}</i>\n"

    if len(events) > 1:
        msg += "\n📜 <b>История статусов:</b>\n"
        for ev in events[1:]:
            raw_ev = str(ev.get("event", "Unknown"))
            ev_info = OZON_STATUS_MAP.get(raw_ev, {"title": raw_ev, "desc": ""})
            ev_mom = format_ozon_date(ev.get("moment", ""))
            msg += f"▫️ <code>{html.escape(ev_mom)}</code> — <b>{html.escape(ev_info['title'])}</b>\n"
            if ev_info["desc"]:
                msg += f"   └ <i>{html.escape(ev_info['desc'])}</i>\n"

    msg += f"\n🔗 <a href=\"https://tracking.ozon.ru/?track={track}\">Сайт Ozon</a>"
    return msg


async def check_packages(bot: Bot, net: Net, force_notify: bool = False):
    if not cfg.get("package_tracking"):
        return
        
    config_changed = False
    
    for track, data in list(cfg["package_tracking"].items()):
        try:
            tracking_data = await fetch_ozon_tracking(net, track)
            if not tracking_data:
                continue
            
            events = tracking_data.get("items") or tracking_data.get("events") or []
            if not events:
                continue
                
            events.sort(key=get_ozon_sortable_date, reverse=True)
            
            latest_event = events[0]
            raw_event_name = str(latest_event.get("event", "Unknown"))
            info = OZON_STATUS_MAP.get(raw_event_name, {"title": raw_event_name, "desc": ""})
            event_moment = format_ozon_date(latest_event.get("moment", ""))
            
            saved_event = data.get("last_event", "")
            saved_moment = data.get("last_moment", "")
            
            is_new = (raw_event_name != saved_event or event_moment != saved_moment)
            
            if is_new and not force_notify:
                if saved_event != "Добавлен" and saved_event != "":
                    msg = build_ozon_message(track, tracking_data, is_new_track=False)
                    await send_alert(bot, net, msg, ntfy_title=f"Ozon: {info['title']}")
            
            if is_new or force_notify:
                data["last_event"] = raw_event_name
                data["last_moment"] = event_moment
                hist_arr = [{"event": OZON_STATUS_MAP.get(ev.get("event", ""), {"title": ev.get("event", "")})["title"], "moment": format_ozon_date(ev.get("moment", ""))} for ev in events]
                data["history"] = hist_arr
                config_changed = True
                
        except Exception as e:
            logging.error(f"[OZON] Check error for {track}: {e}")
            
    if config_changed:
        save_config()


@router.message(F.text & ~F.text.startswith('/'))
async def handle_regular_text(message: Message, bot: Bot):
    if not admin_only(message): return
    
    global ssh_session_active
    
    # Режим SSH
    if ssh_session_active:
        await process_ssh_command(message, bot)
        return
        
    text = message.text.strip()
    
    # 1. Smart Parser: GitHub
    if text.startswith("http://github.com/") or text.startswith("https://github.com/"):
        await cancel_tasks()
        
        # Проверка на релизы
        rel_match = re.match(r'https?://github\.com/([^/]+/[^/]+)/releases', text, re.IGNORECASE)
        if rel_match:
            repo = rel_match.group(1)
            cfg["github_releases"].append({"repo": repo, "filter": "", "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""})
            save_config()
            await message.answer(f"✅ <b>Smart Parser:</b>\nРепозиторий <code>{html.escape(repo)}</code> успешно добавлен в мониторинг релизов!")
            return
            
        # Проверка на коммиты / ветки / папки
        com_match = re.match(r'https?://github\.com/([^/]+/[^/]+)/(?:commits?|tree)(?:/([^/]+)/?(.*))?', text, re.IGNORECASE)
        if com_match:
            repo = com_match.group(1)
            branch = com_match.group(2) or ""
            path = com_match.group(3) or ""
            
            cfg["github_commits"].append({"repo": repo, "path": path, "branch": branch, "last_ver": "", "last_url": "", "last_cl": ""})
            save_config()
            
            b_msg = f" (ветка/хэш: {html.escape(branch)})" if branch else ""
            p_msg = f" (путь: {html.escape(path)})" if path else ""
            await message.answer(f"✅ <b>Smart Parser:</b>\nКоммиты репозитория <code>{html.escape(repo)}</code>{b_msg}{p_msg} добавлены в мониторинг!")
            return
            
        await message.answer("⚠️ Ссылка на GitHub распознана, но формат не поддерживается.\nОтправьте ссылку, содержащую <code>/releases</code> или <code>/commits/имя_ветки</code>.")
        return

    # 2. Smart Parser: Ozon Tracker
    ozon_match = re.match(r'^(\d{8,15}-\d{1,5}(?:-\d{1,2})?)$', text)
    if ozon_match:
        await cancel_tasks()
        track_num = ozon_match.group(1).upper()
        
        wait_msg = await message.answer(f"🔍 Проверяю трек-номер <code>{track_num}</code> через API Ozon...")
        net = await open_net()
        try:
            tracking_data = await fetch_ozon_tracking(net, track_num)
            events = tracking_data.get("items") or tracking_data.get("events") or [] if tracking_data else []
            
            if events:
                events.sort(key=get_ozon_sortable_date, reverse=True)
                latest_event = events[0]
                raw_event_name = str(latest_event.get("event", "Unknown"))
                last_mom = format_ozon_date(latest_event.get("moment", ""))
                
                hist_arr = [{"event": OZON_STATUS_MAP.get(ev.get("event", ""), {"title": ev.get("event", "")})["title"], "moment": format_ozon_date(ev.get("moment", ""))} for ev in events]
                
                cfg["package_tracking"][track_num] = {
                    "last_event": raw_event_name,
                    "last_moment": last_mom,
                    "history": hist_arr
                }
                save_config()
                
                msg = build_ozon_message(track_num, tracking_data, is_new_track=True)
                await wait_msg.edit_text(msg)
            else:
                await wait_msg.edit_text(f"⚠️ Ozon отклонил запрос (WAF блокировка) или не вернул данные для <code>{track_num}</code>.\nУбедитесь что кука активна, посмотрите логи бота <code>/log</code>.")
        finally:
            await close_net(net)
        return

    await cancel_tasks()


# ================= МОДУЛЬ GL.iNet Community API =================
def is_newer_version(old_ver: str, new_ver: str) -> bool:
    if not old_ver: return True
    def parse(v): return [int(x) if x.isdigit() else x for x in re.split(r'[\.-]', str(v))]
    try: return parse(new_ver) > parse(old_ver)
    except TypeError: return new_ver != old_ver

def build_glinet_url(model: str, branch: str, version: str) -> str:
    branch = branch.lower()
    if branch in ['stable', 'release']: return f"https://dl.gl-inet.com/release/router/release/{model}/{version}"
    if branch in ['op24', 'openwrt24', 'open24', 'beta-open24', 'op25', 'openwrt25', 'open25', 'beta-open25']: return f"https://dl.gl-inet.com/release/router/testing/{model}-open/{version}"
    return f"https://dl.gl-inet.com/router/{model}/snapshot"

class GLiNetOfficialAPI:
    BASE_URL = "https://firmware-api.gl-inet.com/cloud-api/model/info"

    @classmethod
    async def get_branches(cls, net: Net, model: str) -> List[str]:
        branches = []
        d_std = await robust_request(net, f"{cls.BASE_URL}?model={model}", silent=True)
        if d_std and isinstance(d_std.get("info"), list):
            stages = {x.get("stage") for x in d_std["info"]}
            if "RELEASE" in stages: branches.append("release")
            if "SNAPSHOT" in stages: branches.append("snapshot")
        
        d_open = await robust_request(net, f"{cls.BASE_URL}?model={model}-open", silent=True)
        if d_open and isinstance(d_open.get("info"), list):
            for item in d_open["info"]:
                dl = item.get("download")
                if not dl or not isinstance(dl, list): continue
                name = dl[0].get("name", "").lower()
                if "op24" in name and "beta-open24" not in branches: branches.append("beta-open24")
                if "op25" in name and "beta-open25" not in branches: branches.append("beta-open25")
                
        return branches

    @classmethod
    async def get_stage_info(cls, net: Net, model: str, stage: str, fetch_all: bool = False) -> Optional[Dict[str, str]]:
        branch = stage.lower()
        query_model = model
        target_stage = None
        target_name = None

        if branch in ["stable", "release"]:
            target_stage = "RELEASE"
        elif branch == "snapshot":
            target_stage = "SNAPSHOT"
        elif branch in ["op24", "openwrt24", "open24", "beta-open24"]:
            query_model = f"{model}-open"
            target_name = "op24"
        elif branch in ["op25", "openwrt25", "open25", "beta-open25"]:
            query_model = f"{model}-open"
            target_name = "op25"
        else:
            return None

        data = await robust_request(net, f"{cls.BASE_URL}?model={query_model}", silent=True)
        if not data or not isinstance(data.get("info"), list):
            return None

        for item in data["info"]:
            if target_stage and item.get("stage") != target_stage:
                continue
            
            dl = item.get("download")
            if not dl or not isinstance(dl, list):
                continue
            
            name = dl[0].get("name", "").lower()
            if target_name and target_name not in name:
                continue

            info = {
                "model": model, 
                "stage": stage, 
                "version": item.get("version", "")
            }

            if fetch_all:
                cl_raw = item.get("release_note") or item.get("release_note_cn") or ""
                cl = cl_raw.replace("<h1>", "\n# ").replace("<h2>", "\n## ").replace("<h3>", "\n### ")
                cl = cl.replace("<li>", "- ").replace("</li>", "\n").replace("<p>", "").replace("</p>", "\n")
                cl = re.sub(r'<[^>]+>', '', cl).strip()
                
                info["date"] = item.get("release_time", "")
                info["url"] = dl[0].get("link", "")
                info["hash"] = dl[0].get("sha256", "")
                info["changelog"] = cl

            return info
            
        return None


# ================= ПРОВЕРКИ =================
async def check_github(bot: Bot, net: Net, force_notify: bool = False):
    gh_headers = get_gh_headers()
    config_changed = False

    for item in cfg["github_releases"]:
        try:
            data = await robust_request(net, f"https://api.github.com/repos/{item['repo']}/releases?per_page=10", headers=gh_headers)
            if not data or not isinstance(data, list) or len(data) == 0:
                single = await robust_request(net, f"https://api.github.com/repos/{item['repo']}/releases/latest", headers=gh_headers)
                data = [single] if isinstance(single, dict) and "tag_name" in single else None
            if not data: continue

            filtr = (item.get("filter") or "").strip()
            for release in data:
                if not isinstance(release, dict): continue
                name, tag = release.get("name") or "", release.get("tag_name") or ""
                body = release.get("body") or ""
                html_url = release.get("html_url") or f"https://github.com/{item['repo']}/releases"
                assets = " ".join(a.get("name", "") for a in release.get("assets", []) if isinstance(a, dict))
                haystack = f"{name} {tag} {assets}"

                if filtr:
                    try:
                        if not re.search(filtr, haystack, re.IGNORECASE): continue
                    except re.error: pass

                ver_id = f"{tag}-{release.get('id', '')}"
                display_ver = f"{tag} ({name})" if name and name != tag else (tag or "без тега")
                had_baseline = bool(item.get("last_ver"))
                is_new = had_baseline and item.get("last_ver") != ver_id

                if not had_baseline or is_new:
                    item["last_ver"] = ver_id
                    item["last_ver_display"] = display_ver
                    item["last_url"] = html_url
                    item["last_cl"] = clean_changelog(body) or "Чейнжлог отсутствует."
                    config_changed = True

                if had_baseline and is_new and not force_notify:
                    safe_body = html.escape(item["last_cl"])
                    if len(safe_body) > 3500: safe_body = safe_body[:3500] + "\n...[обрезано, полный чейнжлог по ссылке]"
                    msg = (f"📦 <b>Новый релиз на GitHub!</b>\n\n<b>Репо:</b> {item['repo']}\n"
                           f"<b>Версия:</b> {html.escape(display_ver)}\n\n<b>Changelog:</b>\n<pre>{safe_body}</pre>\n\n"
                           f"🔗 <a href=\"{html_url}\">Открыть на GitHub</a>")
                    await send_alert(bot, net, msg)
                break
        except Exception as e:
            logging.error(f"Ошибка GitHub releases ({item.get('repo')}): {e}")

    for item in cfg["github_commits"]:
        try:
            path = (item.get("path") or "").strip()
            branch = (item.get("branch") or "").strip()
            url = f"https://api.github.com/repos/{item['repo']}/commits?per_page=1"
            if path: url += f"&path={quote(path)}"
            if branch: url += f"&sha={quote(branch)}"
            data = await robust_request(net, url, headers=gh_headers)
            if not data or not isinstance(data, list) or len(data) == 0: continue

            commit = data[0]
            sha = commit.get("sha", "")
            msg_text = commit.get("commit", {}).get("message", "Без описания")
            html_url = commit.get("html_url") or f"https://github.com/{item['repo']}"

            had_baseline = bool(item.get("last_ver"))
            is_new = had_baseline and item.get("last_ver") != sha

            if not had_baseline or is_new:
                item["last_ver"] = sha
                item["last_url"] = html_url
                item["last_cl"] = clean_changelog(msg_text)
                config_changed = True

            if had_baseline and is_new and not force_notify:
                safe_msg = html.escape(item["last_cl"])
                branch_note = f" (ветка {html.escape(branch)})" if branch else ""
                text = (f"⚙️ <b>Обновление файла/коммита!</b>\n\n<b>Репо:</b> {item['repo']}\n"
                        f"<b>Файл:</b> {html.escape(path) or 'весь репозиторий'}{branch_note}\n"
                        f"<b>SHA:</b> <code>{sha[:7]}</code>\n\n<b>Сообщение:</b>\n<pre>{safe_msg}</pre>\n\n"
                        f"🔗 <a href=\"{html_url}\">Открыть коммит</a>")
                await send_alert(bot, net, text)
        except Exception as e:
            logging.error(f"Ошибка GitHub commits ({item.get('repo')}): {e}")
            
    if config_changed: save_config()


async def check_glinet(bot: Bot, net: Net, force_notify: bool = False):
    models_to_check = list(cfg.get("glinet", {}).keys())
    config_changed = False
    
    for model in models_to_check:
        try:
            available_branches = await GLiNetOfficialAPI.get_branches(net, model)
        except Exception as e:
            continue

        branches_to_check = list(cfg["glinet"][model].keys())
        for branch in branches_to_check:
            
            actual_branch = None
            branch_lower = branch.lower()
            
            aliases_op24 = ["op24", "openwrt24", "open24", "beta-open24"]
            aliases_op25 = ["op25", "openwrt25", "open25", "beta-open25"]
            aliases_release = ["release", "stable"]
            
            if branch_lower in available_branches:
                actual_branch = branch_lower
            else:
                if branch_lower in aliases_op24:
                    for alias in aliases_op24:
                        if alias in available_branches:
                            actual_branch = alias
                            break
                elif branch_lower in aliases_op25:
                    for alias in aliases_op25:
                        if alias in available_branches:
                            actual_branch = alias
                            break
                elif branch_lower in aliases_release:
                    for alias in aliases_release:
                        if alias in available_branches:
                            actual_branch = alias
                            break

            if not actual_branch: continue

            try:
                stage_info_basic = await GLiNetOfficialAPI.get_stage_info(net, model, actual_branch, fetch_all=False)
                if not stage_info_basic or not stage_info_basic.get("version"): continue
                    
                current_ver = stage_info_basic["version"]
                saved_data = cfg["glinet"][model][branch]
                saved_ver = saved_data.get("version", "")

                is_new = is_newer_version(saved_ver, current_ver)

                if not saved_ver:
                    full_info = await GLiNetOfficialAPI.get_stage_info(net, model, actual_branch, fetch_all=True)
                    if full_info:
                        saved_data["version"] = full_info.get("version", current_ver)
                        saved_data["date"] = full_info.get("date", "")
                        saved_data["changelog"] = full_info.get("changelog", "")
                        saved_data["url"] = full_info.get("url", "")
                        saved_data["hash"] = full_info.get("hash", "")
                        config_changed = True
                    continue

                if is_new or force_notify:
                    full_info = await GLiNetOfficialAPI.get_stage_info(net, model, actual_branch, fetch_all=True)
                    if not full_info: continue
                        
                    if not full_info.get("changelog") or len(full_info["changelog"].strip()) < 5:
                        if is_new and not force_notify:
                            await send_alert(bot, net, f"🌐 Замечена новая прошивка GL.iNet {model} ({branch}) v{current_ver}. Чейнжлог на сайте пока пуст. Жду 5 минут...")
                            await asyncio.sleep(300) 
                            full_info = await GLiNetOfficialAPI.get_stage_info(net, model, actual_branch, fetch_all=True) or full_info

                    branch_display = branch.upper()
                    if branch in ("release", "stable"): branch_display = "Stable"
                    elif branch in ("op24", "openwrt24", "beta-open24", "open24"): branch_display = "OpenWrt 24 (OP24)"
                    elif branch in ("op25", "openwrt25", "beta-open25", "open25"): branch_display = "OpenWrt 25 (OP25)"
                    
                    safe_ver = html.escape(full_info["version"])
                    safe_date = html.escape(full_info.get("date", ""))
                    safe_cl = html.escape(full_info.get("changelog", "") or "Нет данных")
                    safe_hash = html.escape(full_info.get("hash", ""))
                    
                    dl_link = full_info.get("url") or build_glinet_url(model, branch, current_ver)
                    
                    msg = (f"🌐 <b>GL.iNet {model.upper()} — {branch_display}</b>\n"
                           f"Новая прошивка: <code>{safe_ver}</code>\n"
                           f"Дата: {safe_date}\n\n"
                           f"<b>Changelog:</b>\n<pre>{safe_cl}</pre>\n\n"
                           f"🔗 <a href=\"{dl_link}\">Скачать прошивку</a>")
                    
                    if safe_hash: msg += f"\nMD5: <code>{safe_hash}</code>"

                    if is_new and not force_notify:
                        await send_alert(bot, net, msg, ntfy_title=f"New GL.iNet {branch_display} firmware")
                    
                    saved_data["version"] = full_info["version"]
                    saved_data["date"] = full_info.get("date", "")
                    saved_data["changelog"] = full_info.get("changelog", "")
                    saved_data["url"] = full_info.get("url", "")
                    saved_data["hash"] = full_info.get("hash", "")
                    config_changed = True

            except Exception: continue
                
    if config_changed: save_config()


async def background_checker(bot: Bot):
    while True:
        net = await open_net()
        try:
            await check_github(bot, net)
            await check_glinet(bot, net)
            await check_packages(bot, net)
        except Exception as e:
            logging.error(f"Глобальная ошибка фонового цикла: {e}")
        finally:
            await close_net(net)
        
        waited = 0
        while True:
            # ИНТЕРВАЛ применяется ко ВСЕМ источникам
            current_interval = max(30, cfg.get("check_interval", 300))
            if waited >= current_interval: break
            await asyncio.sleep(1)
            waited += 1


# ================= TELEGRAM UI =================
async def generate_status_blocks(net: Net) -> List[str]:
    blocks = []

    gh_status = "🔴 Не задан"
    if GITHUB_TOKEN:
        data = await robust_request(net, "https://api.github.com/rate_limit", headers=get_gh_headers(), silent=True)
        if data:
            d = data.get("resources", {}).get("core", {})
            gh_status = f"🟢 Активен (остаток: {d.get('remaining', 0)}/{d.get('limit', 0)})"
        else:
            gh_status = "🟡 Ошибка сети/токена"

    blocks.append(f"📊 <b>Отслеживаемые ресурсы</b>\n──────────────────\n🔑 <b>GitHub API:</b> {gh_status}")

    for i, it in enumerate(cfg.get("github_releases", [])):
        ver = html.escape(it.get("last_ver_display") or (it.get("last_ver", "нет").split("-")[0] or "нет"))
        url, cl = html.escape(it.get("last_url", "")), html.escape(it.get("last_cl", ""))
        text = f"🐙 <b>[{i}] {html.escape(it['repo'])}</b> (Релизы)\n└ Версия: <code>{ver}</code>\n"
        if url: text += f"└ 🔗 <a href=\"{url}\">Скачать / GitHub</a>\n"
        if cl: text += f"\n📝 <b>Чейнжлог:</b>\n<pre>{cl[:1000]}{'...' if len(cl)>1000 else ''}</pre>"
        blocks.append(text)

    for i, it in enumerate(cfg.get("github_commits", [])):
        sha = html.escape(it.get("last_ver", "нет")[:7])
        url, cl = html.escape(it.get("last_url", "")), html.escape(it.get("last_cl", ""))
        path_disp = html.escape(it.get('path') or 'весь репо')
        text = f"⚙️ <b>[{i}] {html.escape(it['repo'])}</b>\n└ Отслеживается: {path_disp}\n└ SHA: <code>{sha}</code>\n"
        if url: text += f"└ 🔗 <a href=\"{url}\">Посмотреть коммит</a>\n"
        if cl: text += f"\n📝 <b>Сообщение:</b>\n<pre>{cl[:1000]}{'...' if len(cl)>1000 else ''}</pre>"
        blocks.append(text)

    idx_gl = 0
    for model, branches in cfg.get("glinet", {}).items():
        for branch, data in branches.items():
            ver = html.escape(data.get("version") or "нет")
            date = html.escape(data.get("date") or "")
            url = html.escape(data.get("url") or "")
            cl = html.escape(data.get("changelog") or "")
            
            branch_display = branch.upper()
            if branch in ("release", "stable"): branch_display = "Stable"
            elif branch in ("op24", "openwrt24", "beta-open24", "open24"): branch_display = "OP24"
            elif branch in ("op25", "openwrt25", "beta-open25", "open25"): branch_display = "OP25"
            
            text = f"🌐 <b>[{idx_gl}] GL.iNet: {html.escape(model)} ({branch_display})</b>\n└ Версия: <code>{ver}</code> ({date})\n"
            if url: text += f"└ 🔗 <a href=\"{url}\">Прямая ссылка</a>\n"
            if cl: text += f"\n📝 <b>Чейнжлог:</b>\n<pre>{cl[:1000]}{'...' if len(cl)>1000 else ''}</pre>"
            blocks.append(text)
            idx_gl += 1
            
    idx_oz = 0
    for track, data in cfg.get("package_tracking", {}).items():
        raw_event = data.get("last_event", "Ожидание...")
        info = OZON_STATUS_MAP.get(raw_event, {"title": raw_event, "desc": ""})
        moment = html.escape(data.get("last_moment", ""))
        mom_str = f" ({moment})" if moment else ""
        
        block_text = f"📦 <b>[{idx_oz}] Ozon Трек:</b> <code>{track}</code>\n└ Статус: <b>{html.escape(info['title'])}</b>{mom_str}"
        if info["desc"]: block_text += f"\n   └ <i>{html.escape(info['desc'])}</i>"
        
        history = data.get("history", [])
        if history and len(history) > 1:
            block_text += "\n   <b>📜 Прошлые статусы:</b>"
            for h in history[1:]:
                h_mom = html.escape(h.get("moment", ""))
                h_ev = html.escape(h.get("event", ""))
                block_text += f"\n   ▫️ <code>{h_mom}</code> — <b>{h_ev}</b>"
                
        blocks.append(block_text)
        idx_oz += 1

    return blocks


def admin_only(message: Message) -> bool:
    if not message.from_user: return False
    if message.from_user.id == ADMIN_ID: return True
    if message.from_user.is_bot: return True
    return False


@router.message(Command("log"))
async def cmd_log(message: Message, bot: Bot):
    if not admin_only(message): return
    await cancel_tasks()
    global log_message_id
    if log_message_id:
        try: await bot.delete_message(ADMIN_ID, log_message_id)
        except Exception: pass
        log_message_id = None
    await init_log_window(bot)
    
@router.message(Command("loglevel"))
async def cmd_loglevel(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🐛 DEBUG", callback_data="log_DEBUG"),
         InlineKeyboardButton(text="ℹ️ INFO", callback_data="log_INFO")],
        [InlineKeyboardButton(text="⚠️ WARNING", callback_data="log_WARNING"),
         InlineKeyboardButton(text="🚨 ERROR", callback_data="log_ERROR")]
    ])
    curr_level = logging.getLevelName(logger.level)
    await message.answer(
        f"🎛 <b>Управление логгированием</b>\n"
        f"Текущий уровень: <code>{curr_level}</code>\n\n"
        f"Выберите новый уровень логирования для изменения поведения бота без его перезапуска. "
        f"Логи будут выводиться в прикрепленном окне (команда /log).",
        reply_markup=kb
    )

@router.callback_query(F.data.startswith("log_"))
async def cb_loglevel(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    new_level = call.data.split("_")[1]
    num_level = getattr(logging, new_level, logging.INFO)
    logger.setLevel(num_level)
    for handler in logger.handlers:
        handler.setLevel(num_level)
    await call.message.edit_text(f"✅ Уровень логгирования успешно изменен на <b>{new_level}</b>!")
    await call.answer(f"Установлен {new_level}")


@router.message(CommandStart())
async def cmd_start(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    await message.answer("👋 Бот запущен. Список команд — /menu")


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статус", callback_data="do_status"),
         InlineKeyboardButton(text="🔄 Принудительно", callback_data="do_force")],
        [InlineKeyboardButton(text="🛠 Управление (Удалить)", callback_data="do_manage")],
        [InlineKeyboardButton(text="🚀 Speedtest", callback_data="do_speedtest"),
         InlineKeyboardButton(text="📝 Логи", callback_data="do_log")],
        [InlineKeyboardButton(text="🔧 Сеть", callback_data="do_net"),
         InlineKeyboardButton(text="📈 Системный монитор", callback_data="do_sysinfo")],
        [InlineKeyboardButton(text="💻 SSH Терминал", callback_data="do_ssh"),
         InlineKeyboardButton(text="🎛 Уровень логов", callback_data="do_loglevel")],
        [InlineKeyboardButton(text="🔑 Настройки SSH", callback_data="do_sshset"),
         InlineKeyboardButton(text="⏱ Интервал", callback_data="do_interval")]
    ])
    
    text = (
        "<b>📋 Главное меню управления</b>\n\n"
        "<i>Интерактивные команды (или используйте кнопки):</i>\n"
        "🔹 <b>Ozon:</b> просто отправь трек-номер в чат\n"
        "🔹 <b>GL.iNet:</b> <code>/add_gl mt6000</code>\n"
        "🔹 <b>GitHub Rel:</b> <code>/add_release owner/repo</code>\n"
        "🔹 <b>GitHub Com:</b> <code>/add_commit owner/repo</code>\n"
        "🔹 <b>Настройки SSH:</b> <code>/ssh_set host user pass port</code>\n"
        "🔹 <b>Ozon Cookie:</b> <code>/ozon_cookie значение</code>\n"
        f"🔹 <b>Интервал опроса:</b> <code>/interval 300</code> (сейчас {cfg.get('check_interval', 300)}с)\n\n"
        "<i>Все действия доступны по кнопкам ниже:</i>"
    )
    await message.answer(text, reply_markup=keyboard)

@router.callback_query(F.data.startswith("do_"))
async def cb_do_action(call: CallbackQuery, bot: Bot):
    if call.from_user.id != ADMIN_ID: return
    action = call.data.split("_", 1)[1]
    
    if action == "status":
        await cmd_status(call.message, bot)
    elif action == "force":
        await cmd_force(call.message, bot)
    elif action == "manage":
        await cmd_manage(call.message)
    elif action == "speedtest":
        await cmd_speedtest(call.message)
    elif action == "log":
        await cmd_log(call.message, bot)
    elif action == "net":
        await cmd_net(call.message)
    elif action == "sysinfo":
        await cmd_sysinfo(call.message, bot)
    elif action == "ssh":
        await cmd_ssh(call.message)
    elif action == "loglevel":
        await cmd_loglevel(call.message)
    elif action == "sshset":
        await call.message.answer(
            "ℹ️ <b>Настройка доступа SSH:</b>\n"
            "Используйте команду для смены IP или данных пользователя.\n\n"
            "👉 <b>Пример:</b> <code>/ssh_set 192.168.8.1 root mypassword 22</code>\n"
            "👉 <b>Пример (без пароля, по ключу):</b> <code>/ssh_set 192.168.8.1 root</code>"
        )
    elif action == "interval":
        await call.message.answer(
            f"ℹ️ <b>Настройка интервала опроса серверов:</b>\n"
            f"Сейчас бот проверяет обновления каждые <b>{cfg.get('check_interval', 300)} сек.</b>\n\n"
            f"👉 <b>Пример изменения (5 минут):</b> <code>/interval 300</code>\n"
            f"👉 <b>Пример (1 минута):</b> <code>/interval 60</code>"
        )
        
    try:
        await call.answer()
    except Exception:
        pass

@router.message(Command("ozon_cookie"))
async def cmd_set_cookie(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer(
            "ℹ️ <b>Как обновить Cookie Ozon:</b>\n"
            "Скопируйте куки из браузера (например, с помощью Userscript) и отправьте команду:\n\n"
            "👉 <code>/ozon_cookie abt_data=...; __Secure-access-token=...</code>"
        )
        return
    cfg["ozon_cookie"] = args[1]
    save_config()
    await message.answer("✅ Cookie для Ozon успешно обновлена! Бот снова может обходить защиту Qrator.")

@router.message(Command("sysinfo"))
async def cmd_sysinfo(message: Message, bot: Bot):
    if not admin_only(message): return
    await cancel_tasks()
    msg = await message.answer("🔄 Подключение к датчикам роутера...")
    global sysinfo_task_ref
    sysinfo_task_ref = asyncio.create_task(sysinfo_updater(bot, message.chat.id, msg.message_id))


@router.message(Command("ssh"))
async def cmd_ssh(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    global ssh_session_active
    ssh_session_active = True
    c = cfg.get("ssh", {})
    host = html.escape(c.get("host", "192.168.8.1"))
    user = html.escape(c.get("user", "root"))
    local_host = socket.gethostname()
    prompt_str = f"{user}@{local_host}:~# " if host in ("127.0.0.1", "localhost", "0.0.0.0") else f"{user}@{host}:~# "
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Закрыть SSH", callback_data="ssh_close")]])
    await message.answer(
        f"🔌 <b>SSH Режим активирован</b>\n"
        f"Узел: <code>{user}@{host}</code>\n\n"
        f"Отправьте мне команды текстом. Можно вставить сразу целый блок команд (например, скрипт установки).\n\n"
        f"💻 <b>Терминал:</b>\n<pre>{prompt_str}</pre>",
        reply_markup=kb
    )


@router.message(Command("ssh_set"))
async def cmd_ssh_set(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()[1:]
    if len(args) < 1:
        await message.answer(
            "ℹ️ <b>Настройка доступа SSH:</b>\n"
            "Используйте команду для смены IP или данных пользователя.\n\n"
            "👉 <b>Пример:</b> <code>/ssh_set 192.168.8.1 root mypassword 22</code>\n"
            "👉 <b>Пример (без пароля, по ключу):</b> <code>/ssh_set 192.168.8.1 root</code>"
        )
        return
    cfg["ssh"]["host"] = args[0]
    cfg["ssh"]["user"] = args[1] if len(args) > 1 else "root"
    cfg["ssh"]["password"] = args[2] if len(args) > 2 else ""
    if len(args) > 3 and args[3].isdigit(): cfg["ssh"]["port"] = int(args[3])
    elif "port" not in cfg["ssh"]: cfg["ssh"]["port"] = 22
    save_config()
    await message.answer(f"✅ Данные SSH сохранены.\nХост: <code>{cfg['ssh']['host']}</code>\nПользователь: <code>{cfg['ssh']['user']}</code>\nПорт: <code>{cfg['ssh']['port']}</code>")




@router.message(Command("manage"))
async def cmd_manage(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Ozon", callback_data="mg_cat_ozon"),
         InlineKeyboardButton(text="🌐 GL.iNet", callback_data="mg_cat_gl")],
        [InlineKeyboardButton(text="🐙 GitHub Releases", callback_data="mg_cat_ghr"),
         InlineKeyboardButton(text="⚙️ GitHub Commits", callback_data="mg_cat_ghc")]
    ])
    await message.answer("🛠 <b>Управление отслеживаниями</b>\nВыберите категорию:", reply_markup=keyboard)

@router.callback_query(F.data.startswith("mg_cat_"))
async def cb_manage_cat(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await cancel_tasks()
    cat = call.data.split("_", 2)[2]
    
    buttons = []
    if cat == "ozon":
        for track in cfg.get("package_tracking", {}).keys():
            buttons.append([InlineKeyboardButton(text=f"❌ Озон: {track}", callback_data=f"mg_del_ozon_{track}")])
    elif cat == "gl":
        for model, branches in cfg.get("glinet", {}).items():
            for branch in branches.keys():
                buttons.append([InlineKeyboardButton(text=f"❌ GL: {model} ({branch})", callback_data=f"mg_del_gl_{model}_{branch}")])
    elif cat == "ghr":
        for i, item in enumerate(cfg.get("github_releases", [])):
            buttons.append([InlineKeyboardButton(text=f"❌ Rel: {item['repo']}", callback_data=f"mg_del_ghr_{i}")])
    elif cat == "ghc":
        for i, item in enumerate(cfg.get("github_commits", [])):
            buttons.append([InlineKeyboardButton(text=f"❌ Com: {item['repo']} ({item.get('branch','main')})", callback_data=f"mg_del_ghc_{i}")])
            
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="mg_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await call.message.edit_text("Выберите элемент для <b>удаления</b>:", reply_markup=keyboard)
    except Exception: pass

@router.callback_query(F.data == "mg_back")
async def cb_manage_back(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await cancel_tasks()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 Ozon", callback_data="mg_cat_ozon"),
         InlineKeyboardButton(text="🌐 GL.iNet", callback_data="mg_cat_gl")],
        [InlineKeyboardButton(text="🐙 GitHub Releases", callback_data="mg_cat_ghr"),
         InlineKeyboardButton(text="⚙️ GitHub Commits", callback_data="mg_cat_ghc")]
    ])
    try:
        await call.message.edit_text("🛠 <b>Управление отслеживаниями</b>\nВыберите категорию:", reply_markup=keyboard)
    except Exception: pass

@router.callback_query(F.data.startswith("mg_del_"))
async def cb_manage_del(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await cancel_tasks()
    parts = call.data.split("_", 3)
    t = parts[2]
    
    if t == "ozon":
        track = parts[3]
        if track in cfg.get("package_tracking", {}):
            del cfg["package_tracking"][track]
            save_config()
            await call.answer(f"Удален трек {track}")
    elif t == "gl":
        model, branch = parts[3].split("_", 1)
        if model in cfg.get("glinet", {}) and branch in cfg["glinet"][model]:
            del cfg["glinet"][model][branch]
            if not cfg["glinet"][model]: del cfg["glinet"][model]
            save_config()
            await call.answer(f"Удалена ветка {branch} для {model}")
    elif t == "ghr":
        idx = int(parts[3])
        if 0 <= idx < len(cfg.get("github_releases", [])):
            repo = cfg["github_releases"][idx]["repo"]
            cfg["github_releases"].pop(idx)
            save_config()
            await call.answer(f"Удален {repo}")
    elif t == "ghc":
        idx = int(parts[3])
        if 0 <= idx < len(cfg.get("github_commits", [])):
            repo = cfg["github_commits"][idx]["repo"]
            cfg["github_commits"].pop(idx)
            save_config()
            await call.answer(f"Удален {repo}")
            

    cat = t
    buttons = []
    if cat == "ozon":
        for track in cfg.get("package_tracking", {}).keys():
            buttons.append([InlineKeyboardButton(text=f"❌ Озон: {track}", callback_data=f"mg_del_ozon_{track}")])
    elif cat == "gl":
        for model, branches in cfg.get("glinet", {}).items():
            for branch in branches.keys():
                buttons.append([InlineKeyboardButton(text=f"❌ GL: {model} ({branch})", callback_data=f"mg_del_gl_{model}_{branch}")])
    elif cat == "ghr":
        for i, item in enumerate(cfg.get("github_releases", [])):
            buttons.append([InlineKeyboardButton(text=f"❌ Rel: {item['repo']}", callback_data=f"mg_del_ghr_{i}")])
    elif cat == "ghc":
        for i, item in enumerate(cfg.get("github_commits", [])):
            buttons.append([InlineKeyboardButton(text=f"❌ Com: {item['repo']} ({item.get('branch','main')})", callback_data=f"mg_del_ghc_{i}")])
            
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="mg_back")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    try:
        await call.message.edit_text("Выберите элемент для <b>удаления</b>:", reply_markup=keyboard)
    except Exception: pass



@router.message(Command("speedtest"))
async def cmd_speedtest(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🌐 Тест WAN", callback_data="speedtest_wan")],
        [InlineKeyboardButton(text="🛡 Тест VPN (br-vpnnet)", callback_data="speedtest_br-vpnnet")]
    ])
    await message.answer("🚀 Выберите интерфейс для замера скорости (скачивание 50 МБ):", reply_markup=keyboard)

@router.callback_query(F.data.startswith("speedtest_"))
async def cb_speedtest(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await cancel_tasks()
    
    iface = call.data.split("_", 1)[1]
    await call.message.edit_text(f"⏳ Начинаю замер скорости через интерфейс <b>{iface}</b>...\nОжидайте около 10-20 секунд.")
    
    url = "https://speed.cloudflare.com/__down?bytes=50000000"
    cmd = ["curl", "-s", "-o", "/dev/null", "-w", "%{speed_download}"]
    if iface != "wan":
        cmd.extend(["--interface", iface])
    cmd.append(url)
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = html.escape(stderr.decode('utf-8', 'ignore'))
            await call.message.edit_text(f"❌ Ошибка спидтеста через <b>{iface}</b>:\\n<pre>{err}</pre>")
            return
            
        speed_bytes_sec = float(stdout.decode('utf-8', 'ignore').strip() or "0")
        speed_mbps = (speed_bytes_sec * 8) / 1000000
        
        await call.message.edit_text(f"✅ <b>Результат Speedtest ({iface})</b>\n\n⬇️ Скорость скачивания: <b>{speed_mbps:.2f} Мбит/с</b>")
    except Exception as e:
        await call.message.edit_text(f"❌ Внутренняя ошибка: {e}")


@router.message(Command("status"))
async def cmd_status(message: Message, bot: Bot):
    if not admin_only(message): return
    await cancel_tasks()
    net = await open_net()
    try: blocks = await generate_status_blocks(net)
    finally: await close_net(net)
    await send_long_messages(bot, blocks)


@router.message(Command("force"))
async def cmd_force(message: Message, bot: Bot):
    if not admin_only(message): return
    await cancel_tasks()
    wait_msg = await message.answer("🔄 Принудительная проверка всех источников вне очереди...")
    net = await open_net()
    try:
        await check_github(bot, net, force_notify=True)
        await check_glinet(bot, net, force_notify=True)
        await check_packages(bot, net, force_notify=True)
        blocks = await generate_status_blocks(net)
    finally: await close_net(net)
    try: await wait_msg.delete()
    except Exception: pass
    await message.answer("✅ <b>Принудительная проверка завершена!</b>\nСвежие данные:")
    await send_long_messages(bot, blocks)


@router.message(Command("list"))
async def cmd_list(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    lines = ["<b>📦 GitHub релизы:</b>\n──────────────────"]
    for i, it in enumerate(cfg["github_releases"]):
        f = f" <i>(ф: {html.escape(it['filter'])})</i>" if it.get("filter") else ""
        lines.append(f"[{i}] {html.escape(it['repo'])}{f}")
        
    lines.append("\n<b>⚙️ GitHub коммиты/файлы:</b>\n──────────────────")
    for i, it in enumerate(cfg["github_commits"]):
        p = it.get("path") or "весь репозиторий"
        b = f" @{it['branch']}" if it.get("branch") else ""
        lines.append(f"[{i}] {html.escape(it['repo'])} ➞ {html.escape(p)}{html.escape(b)}")
    
    lines.append("\n<b>🌐 GL.iNet:</b>\n──────────────────")
    idx = 0
    for model, branches in cfg.get("glinet", {}).items():
        for branch in branches.keys():
            lines.append(f"[{idx}] {html.escape(model)} / {html.escape(branch)}")
            idx += 1
            
    tracks = cfg.get("package_tracking", {})
    if tracks:
        lines.append("\n<b>📦 Ozon Отслеживание:</b>\n──────────────────")
        idx_oz = 0
        for track in tracks.keys():
            lines.append(f"[{idx_oz}] {html.escape(track)}")
            idx_oz += 1
            
    await message.answer(
        "\n".join(lines) + 
        "\n\n<i>Для удаления используйте команды /del_release, /del_commit, /del_gl или /del_ozon с указанием индекса в квадратных скобках.</i>"
    )


@router.message(Command("del_ozon", "del_track"))
async def cmd_del_ozon(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()
    if len(args) < 2:
        await message.answer("ℹ️ <b>Удаление трека:</b>\nУкажите индекс посылки из /list или сам трек-номер.\n\n👉 <b>Пример:</b> <code>/del_ozon 0</code>\n👉 <b>Пример:</b> <code>/del_ozon 0269499446-0002-1</code>")
        return
        
    target = args[1].strip().upper()
    keys = list(cfg.get("package_tracking", {}).keys())
    removed = False
    if target in keys:
        track = target
        del cfg["package_tracking"][track]
        removed = True
    elif target.isdigit() and int(target) < len(keys):
        if int(target) < 1000 and target not in keys:
            track = keys[int(target)]
            del cfg["package_tracking"][track]
            removed = True
        
    if removed:
        save_config()
        await message.answer(f"🗑 Отслеживание Ozon для посылки <code>{html.escape(track)}</code> успешно удалено!")
    else:
        await message.answer("❌ Индекс или трек-номер не найден в базе. Проверьте список /list")


@router.message(Command("add_release"))
async def cmd_add_release(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split(maxsplit=2)[1:]
    if not args:
        await message.answer(
            "ℹ️ <b>Добавление репозитория (Релизы):</b>\n"
            "Укажите `Владелец/Репо`. Можно также добавить regex-фильтр (например, для игнорирования pre-release).\n\n"
            "👉 <b>Пример:</b> <code>/add_release v2fly/v2ray-core</code>\n"
            "👉 <b>Пример с фильтром:</b> <code>/add_release thundera/app macos|dmg</code>"
        )
        return
    repo = args[0].strip()
    filtr = args[1].strip() if len(args) > 1 else ""
    cfg["github_releases"].append({"repo": repo, "filter": filtr, "last_ver": "", "last_ver_display": "", "last_url": "", "last_cl": ""})
    save_config()
    await message.answer(f"✅ Репозиторий <b>{html.escape(repo)}</b> добавлен в мониторинг релизов!")


@router.message(Command("del_release"))
async def cmd_del_release(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("ℹ️ Укажите индекс из команды /list.\n👉 <b>Пример:</b> <code>/del_release 0</code>")
        return
    idx = int(args[1])
    if 0 <= idx < len(cfg["github_releases"]):
        removed = cfg["github_releases"].pop(idx)
        save_config()
        await message.answer(f"🗑 Мониторинг релизов для <b>{html.escape(removed['repo'])}</b> удален.")
    else:
        await message.answer("❌ Индекс вне диапазона.")


@router.message(Command("setfilter"))
async def cmd_setfilter(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split(maxsplit=2)[1:]
    if not args or not args[0].isdigit():
        await message.answer("ℹ️ Укажите индекс репозитория и регулярное выражение для фильтра.\n👉 <b>Пример:</b> <code>/setfilter 0 linux-amd64</code>")
        return
    idx = int(args[0])
    filtr = args[1] if len(args) > 1 else ""
    if 0 <= idx < len(cfg["github_releases"]):
        cfg["github_releases"][idx]["filter"] = filtr
        save_config()
        await message.answer(f"✅ Фильтр для репозитория обновлён:\n<code>{html.escape(filtr) or '(фильтр удален)'}</code>")
    else:
        await message.answer("❌ Индекс вне диапазона.")


@router.message(Command("add_commit"))
async def cmd_add_commit(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split(maxsplit=3)[1:]
    if not args:
        await message.answer(
            "ℹ️ <b>Отслеживание коммитов:</b>\n"
            "Позволяет следить за изменениями конкретного файла или целой ветки.\n\n"
            "👉 <b>Пример (весь репо):</b> <code>/add_commit Homebrew/homebrew-core</code>\n"
            "👉 <b>Пример (конкретный файл):</b> <code>/add_commit MetaCubeX/meta-rules-dat geo/geosite/category-ru.srs sing</code>"
        )
        return
    repo = args[0].strip()
    path = args[1].strip() if len(args) > 1 else ""
    branch = args[2].strip() if len(args) > 2 else ""
    cfg["github_commits"].append({"repo": repo, "path": path, "branch": branch, "last_ver": "", "last_url": "", "last_cl": ""})
    save_config()
    await message.answer(f"✅ Отслеживание коммитов для <b>{html.escape(repo)}</b> активировано!")


@router.message(Command("del_commit"))
async def cmd_del_commit(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("ℹ️ Укажите индекс из команды /list.\n👉 <b>Пример:</b> <code>/del_commit 0</code>")
        return
    idx = int(args[1])
    if 0 <= idx < len(cfg["github_commits"]):
        removed = cfg["github_commits"].pop(idx)
        save_config()
        await message.answer(f"🗑 Отслеживание коммитов <b>{html.escape(removed['repo'])}</b> удалено.")
    else:
        await message.answer("❌ Индекс вне диапазона.")


@router.message(Command("add_gl"))
async def cmd_add_gl(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split(maxsplit=1)[1:]
    if not args:
        await message.answer(
            "ℹ️ <b>Интерактивное добавление GL.iNet:</b>\n"
            "Введите команду и **кодовое имя** роутера (не маркетинговое 'Flint 2', а именно 'mt6000').\n\n"
            "👉 <b>Пример:</b> <code>/add_gl mt6000</code>\n"
            "👉 <b>Пример:</b> <code>/add_gl mt3000</code>\n\n"
            "Бот сам опросит сервер и предложит выбрать ветку для отслеживания кнопками."
        )
        return
        
    model = args[0].strip().lower()
    wait_msg = await message.answer(f"🔍 Запрашиваю список доступных веток для устройства <b>{html.escape(model)}</b> с серверов GL.iNet...")
    
    net = await open_net()
    try:
        branches = await GLiNetOfficialAPI.get_branches(net, model)
    except Exception as e:
        branches = []
        logging.error(f"Error fetching branches for {model}: {e}")
    finally:
        await close_net(net)
        
    if not branches:
        await wait_msg.edit_text(f"❌ Кодовое имя <b>{html.escape(model)}</b> не найдено на сервере обновлений, либо API сейчас недоступен.")
        return
        
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b.upper(), callback_data=f"addgl_{model}_{b}")] for b in branches
    ])
    await wait_msg.edit_text(f"🌐 <b>Выбор ветки для {html.escape(model)}</b>\nВыберите, какую версию прошивки добавить в мониторинг:", reply_markup=kb)

@router.callback_query(F.data.startswith("addgl_"))
async def cb_add_gl(call: CallbackQuery):
    if call.from_user.id != ADMIN_ID: return
    await cancel_tasks()
    try:
        _, model, branch = call.data.split("_", 2)
    except ValueError:
        return
        
    if "glinet" not in cfg: cfg["glinet"] = {}
    if model not in cfg["glinet"]: cfg["glinet"][model] = {}
    
    cfg["glinet"][model][branch] = {"version": "", "date": "", "url": "", "hash": "", "changelog": ""}
    save_config()
    
    await call.message.edit_text(f"✅ Прошивка <b>{html.escape(branch.upper())}</b> для роутера <b>{html.escape(model)}</b> успешно добавлена в мониторинг!")
    await call.answer(f"Добавлено: {branch}")


@router.message(Command("del_gl"))
async def cmd_del_gl(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer("ℹ️ Укажите индекс прошивки GL.iNet из команды /list.\n👉 <b>Пример:</b> <code>/del_gl 0</code>")
        return
    idx = int(args[1])
    current_idx = 0
    removed = False
    for model in list(cfg.get("glinet", {}).keys()):
        for branch in list(cfg["glinet"][model].keys()):
            if current_idx == idx:
                del cfg["glinet"][model][branch]
                if not cfg["glinet"][model]: del cfg["glinet"][model]
                save_config()
                await message.answer(f"🗑 Отслеживание прошивки <b>{html.escape(model)} / {html.escape(branch)}</b> удалено.")
                removed = True
                break
            current_idx += 1
        if removed: break
    if not removed: await message.answer("❌ Индекс вне диапазона.")


@router.message(Command("interval"))
async def cmd_interval(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    args = message.text.split()
    if len(args) < 2 or not args[1].isdigit():
        await message.answer(
            f"ℹ️ <b>Настройка интервала опроса серверов:</b>\n"
            f"Сейчас бот проверяет обновления каждые <b>{cfg.get('check_interval', 300)} сек.</b>\n\n"
            f"👉 <b>Пример изменения (5 минут):</b> <code>/interval 300</code>\n"
            f"👉 <b>Пример (1 минута):</b> <code>/interval 60</code>"
        )
        return
    seconds = max(30, int(args[1]))
    cfg["check_interval"] = seconds
    save_config()
    await message.answer(f"✅ Интервал проверки успешно изменен на <b>{seconds} сек.</b>")


@router.message(Command("net"))
async def cmd_net(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    wait_msg = await message.answer("🔄 Сканирование сетевых интерфейсов и проверка пинга...")
    try: ifaces = os.listdir('/sys/class/net/')
    except Exception: ifaces = ["Неизвестно"]
    vpn_ip = resolve_ip(VPN_IFACE)
    fb_ip = resolve_ip(FALLBACK_IFACE)
    async def check_conn(ip: str, iface_name: str):
        if not ip: return "🔴 Не активен (нет IP)"
        conn = aiohttp.TCPConnector(local_addr=(ip, 0), ttl_dns_cache=300)
        async with aiohttp.ClientSession(connector=conn) as sess:
            try:
                start = time.time()
                async with sess.get("https://1.1.1.1", timeout=5) as r:
                    ping = int((time.time() - start) * 1000)
                    return f"🟢 Работает (ping: {ping}ms)" if r.status else f"🟡 Ошибка HTTP {r.status}"
            except Exception as e: return f"🔴 Ошибка маршрута ({e})"

    vpn_status = await check_conn(vpn_ip, VPN_IFACE) if vpn_ip else "🔴 Отключен / Не найден"
    fb_status = await check_conn(fb_ip, FALLBACK_IFACE) if fb_ip else "🟢 Работает (Используется системный маршрут)" if not FALLBACK_IFACE else "🔴 Отключен / Не найден"
    ntfy_status = "🔴 Сервер недоступен"
    try:
        async with aiohttp.ClientSession() as sess:
            start = time.time()
            async with sess.get("https://ntfy.sh", timeout=5) as r:
                ping = int((time.time() - start) * 1000)
                if r.status == 200: ntfy_status = f"🟢 Доступен (ping: {ping}ms)"
    except Exception: pass
        
    text = (
        "<b>🌐 Состояние Сети и Маршрутов</b>\n"
        "──────────────────\n"
        f"🛡 <b>VPN Интерфейс</b> (<code>{html.escape(VPN_IFACE)}</code>):\n"
        f"└ IP: <code>{html.escape(vpn_ip) if vpn_ip else 'N/A'}</code>\n"
        f"└ Статус: {vpn_status}\n\n"
        f"🌍 <b>Резервный (Fallback)</b> (<code>{html.escape(FALLBACK_IFACE) or 'Системный'}</code>):\n"
        f"└ IP: <code>{html.escape(fb_ip) if fb_ip else 'N/A'}</code>\n"
        f"└ Статус: {fb_status}\n\n"
        f"🚀 <b>Сервер уведомлений (ntfy.sh):</b>\n"
        f"└ {ntfy_status}\n"
        "──────────────────\n"
        f"📜 <b>Все интерфейсы системы:</b>\n"
        f"<code>{', '.join(ifaces)}</code>"
    )
    await wait_msg.edit_text(text)


@router.message(Command("start"))
async def cmd_start_alias(message: Message):
    if not admin_only(message): return
    await cancel_tasks()
    await message.answer("👋 Бот запущен. Вызовите меню управления командой — /menu")


# ================= ЗАПУСК =================
class BoundAiohttpSession(AiohttpSession):
    def __init__(self, local_ip: Optional[str] = None, **kwargs):
        super().__init__(**kwargs)
        if local_ip:
            try:
                self._connector_init = dict(getattr(self, "_connector_init", {}) or {})
                self._connector_init["local_addr"] = (local_ip, 0)
                self._should_reset_connector = True
            except Exception as e: pass

def make_bot(token: str) -> Bot:
    vpn_ip = resolve_ip(VPN_IFACE)
    try: session = BoundAiohttpSession(local_ip=vpn_ip)
    except Exception as e: session = AiohttpSession()
    return Bot(token=token, session=session, default=DefaultBotProperties(parse_mode="HTML"))


async def main():
    load_config()
    bot = make_bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)

    await init_log_window(bot)

    asyncio.create_task(log_updater_task(bot))
    asyncio.create_task(background_checker(bot))

    logging.info("Бот запущен.")
    try:
        startup_net = await open_net()
        await send_ntfy(startup_net, "Бот мониторинга прошивок и сетей успешно запущен и готов к работе!", "✅ Бот запущен")
        await close_net(startup_net)
    except Exception as e: pass

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
