# -*- coding: utf-8 -*-
"""hCaptcha Monitor for AdsPower"""

# =========================
# CONFIG
# =========================
ADSPOWER_API_URL = "http://127.0.0.1:50326"
ADSPOWER_API_KEY = "804f0375f51c87c7e03b23ce9e38f196"

# Единственные «таймеры»/лимиты — для AdsPower API и TTL кэша профилей:
REQUEST_TIMEOUT_SEC = 10          # HTTP таймаут к AdsPower
REQUEST_DELAY_SEC = 1.5           # глобальный rate-limit для ЛЮБЫХ запросов к AdsPower
REQUEST_RETRY_MAX = 3             # ретраи HTTP к AdsPower
ALL_PROFILES_REFRESH_SEC = 180    # TTL локального кэша /user/list (снижение нагрузки на API)

LOG_LEVEL = "INFO"
MAX_JSON_LOG_CHARS = 800
LOG_TO_FILE = False
LOG_FILE_PATH = "hcaptcha_monitor.log"

# =========================
# IMPORTS
# =========================
import asyncio
import json
import logging
import random
import signal
import sys
import time
import traceback
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import requests
from playwright.async_api import async_playwright, Browser, Page, TimeoutError as PWTimeoutError

from hcaptcha_challenger.agent import AgentV, AgentConfig
from hcaptcha_challenger.models import CaptchaResponse

# =========================
# LOGGING
# =========================
class _Color:
    RESET = "\033[0m"
    RED = "\033[31m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    BLUE = "\033[34m"

class TTYColorFormatter(logging.Formatter):
    def __init__(self, fmt, datefmt=None, use_color=None):
        super().__init__(fmt, datefmt)
        self.use_color = sys.stderr.isatty() if use_color is None else use_color

    def format(self, record: logging.LogRecord) -> str:
        if self.use_color:
            if record.levelno >= logging.ERROR:
                record.levelname = f"{_Color.RED}{record.levelname}{_Color.RESET}"
            elif record.levelno >= logging.WARNING:
                record.levelname = f"{_Color.YELLOW}{record.levelname}{_Color.RESET}"
            elif record.levelno >= logging.INFO:
                record.levelname = f"{_Color.GREEN}{record.levelname}{_Color.RESET}"
            else:
                record.levelname = f"{_Color.BLUE}{record.levelname}{_Color.RESET}"
        return super().format(record)

def _setup_logger() -> logging.Logger:
    logger = logging.getLogger("HCaptchaMonitor")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    logger.handlers.clear()
    fmt, datefmt = "%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"

    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
    ch.setFormatter(TTYColorFormatter(fmt, datefmt))
    logger.addHandler(ch)

    if LOG_TO_FILE:
        fh = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
        fh.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.INFO))
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(fh)

    return logger

logger = _setup_logger()

# =========================
# UTILS
# =========================
def safe_json(data: dict, limit: int = MAX_JSON_LOG_CHARS) -> str:
    try:
        raw = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
        return raw if len(raw) <= limit else raw[:limit] + "...(truncated)"
    except Exception:
        return "<unserializable>"

def backoff_with_jitter(base: float, attempt: int, cap: float = 30.0) -> float:
    d = min(cap, base * (2 ** attempt))
    return d + random.uniform(0, min(0.5, d / 4.0))

async def to_thread(func, *args, **kwargs):
    return await asyncio.to_thread(func, *args, **kwargs)

def _short_url(u: str, n: int = 160) -> str:
    if not u:
        return "<unknown>"
    return u if len(u) <= n else u[:n] + "…"

# =========================
# DATA
# =========================
@dataclass(frozen=True)
class ProfileInfo:
    user_id: str
    name: str
    ws_endpoint: Optional[str] = None

# =========================
# AdsPower API client (таймеры/лимиты — только здесь и в TTL кэша)
# =========================
class AdsPowerAPI:
    __slots__ = ("api_url", "api_key", "session", "_rl_lock", "_next_ts")

    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip("/")
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})
        # потокобезопасный глобальный rate-limit
        self._rl_lock = threading.Lock()
        self._next_ts = 0.0  # следующий допустимый момент (monotonic)

    def close(self):
        try:
            self.session.close()
        except Exception:
            pass

    def _throttle(self):
        # Гарантируем REQUEST_DELAY_SEC между ЛЮБЫМИ запросами к AdsPower (даже из разных потоков)
        with self._rl_lock:
            now = time.monotonic()
            wait = max(0.0, self._next_ts - now)
            if wait > 0:
                time.sleep(wait)
                now = time.monotonic()
            self._next_ts = now + REQUEST_DELAY_SEC

    def _request(self, method: str, path: str, *, params: Optional[dict] = None, json_: Optional[dict] = None) -> dict:
        url = f"{self.api_url}{path}"
        last_exc = None
        for attempt in range(REQUEST_RETRY_MAX):
            try:
                self._throttle()
                if method == "GET":
                    r = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT_SEC)
                else:
                    r = self.session.post(url, json=json_, timeout=REQUEST_TIMEOUT_SEC)
                r.raise_for_status()
                return r.json()
            except requests.Timeout as e:
                last_exc = e
                if attempt + 1 < REQUEST_RETRY_MAX:
                    d = backoff_with_jitter(0.75, attempt, cap=5.0)
                    logger.warning("AdsPower %s timeout — retry in %.2fs", path, d)
                    time.sleep(d)
                else:
                    logger.warning("AdsPower %s timeout (final)", path)
            except requests.RequestException as e:
                last_exc = e
                if attempt + 1 < REQUEST_RETRY_MAX:
                    d = backoff_with_jitter(0.75, attempt, cap=5.0)
                    logger.warning("AdsPower %s request error: %s — retry in %.2fs", path, e, d)
                    time.sleep(d)
                else:
                    logger.warning("AdsPower %s request error (final): %s", path, e)
            except Exception as e:
                last_exc = e
                logger.error("AdsPower %s unexpected: %s", path, e)
                break
        return {"code": -1, "msg": f"request_failed: {last_exc}"}

    def get_all_profiles(self, page: str = "1", page_size: str = "100") -> List[dict]:
        res = self._request("GET", "/api/v1/user/list", params={"page": page, "page_size": page_size})
        if res.get("code") == 0:
            return res.get("data", {}).get("list", [])
        logger.warning("AdsPower /user/list error: %s", res.get("msg"))
        return []

    def get_active_profiles(self) -> List[dict]:
        res = self._request("GET", "/api/v1/browser/local-active")
        if res.get("code") == 0:
            return res.get("data", {}).get("list", [])
        logger.warning("AdsPower /browser/local-active error: %s", res.get("msg"))
        return []

    def get_profile_debug_info(self, profile_id: str) -> dict:
        return self._request("GET", "/api/v1/browser/active", params={"user_id": str(profile_id)})

    def start_profile(self, profile_id: str) -> dict:
        return self._request("POST", "/api/v1/browser/start", json_={"user_id": str(profile_id)})

# =========================
# Monitor/Solver (без таймеров/лимитов вне API AdsPower)
# =========================
class CaptchaMonitor:
    __slots__ = (
        "adspower", "playwright", "_running",
        "monitored_profiles", "active_tasks",
        "_profiles_cache", "_last_profiles_refresh",
        "_page_locks", "_solve_tasks"
    )

    def __init__(self, api_url: str = ADSPOWER_API_URL, api_key: str = ADSPOWER_API_KEY):
        self.adspower = AdsPowerAPI(api_url, api_key)
        self.playwright = None
        self._running = True

        self.monitored_profiles: Dict[str, ProfileInfo] = {}
        self.active_tasks: Set[asyncio.Task] = set()

        self._profiles_cache: Dict[str, str] = {}
        self._last_profiles_refresh = 0.0

        # пер-вкладочные блокировки и пул активных solve-задач
        self._page_locks: Dict[str, asyncio.Lock] = {}
        self._solve_tasks: Set[asyncio.Task] = set()

    # --- profiles cache (TTL относится к AdsPower API) ---
    async def _refresh_profiles_cache(self, force: bool = False) -> None:
        now = time.time()
        if not force and (now - self._last_profiles_refresh) < ALL_PROFILES_REFRESH_SEC:
            return
        profiles = await to_thread(self.adspower.get_all_profiles)
        for p in profiles:
            uid = str(p.get("user_id") or "")
            if not uid:
                continue
            name = p.get("name") or f"Profile_{p.get('serial_number', uid)}"
            self._profiles_cache[uid] = name
        self._last_profiles_refresh = now
        logger.debug("Profiles cache refreshed: %d", len(self._profiles_cache))

    async def _name(self, user_id: str) -> str:
        if user_id not in self._profiles_cache:
            await self._refresh_profiles_cache(force=True)
        return self._profiles_cache.get(user_id, f"Profile_{user_id}")

    # --- captcha detection/solve ---
    async def _has_hcaptcha(self, page: Page) -> bool:
        # быстрый фильтр по URL фреймов
        try:
            frames = page.frames
        except Exception:
            return False

        candidates = []
        for fr in frames:
            try:
                u = fr.url or ""
            except Exception:
                u = ""
            if "hcaptcha" in u:
                candidates.append(fr)

        if not candidates:
            return False

        # точечная проверка чекбокса
        for fr in candidates:
            try:
                locator = fr.locator('div#checkbox, .check, #checkbox, div.check').first
                if await locator.is_visible(timeout=800):
                    return True
            except PWTimeoutError:
                continue
            except Exception:
                continue
        return False

    async def _solve(self, page: Page, profile_id: str) -> bool:
        name = await self._name(profile_id)
        try:
            url = page.url
        except Exception:
            url = "<unknown>"
        short = _short_url(url)

        logger.info("🤖 [%s] Решение hCaptcha на %s", name, short)
        try:
            agent = AgentV(page=page, agent_config=AgentConfig())
            # 1) клик по чекбоксу
            await agent.robotic_arm.click_checkbox()
            # 2) ожидание/решение
            await agent.wait_for_challenge()

            cr_list = getattr(agent, "cr_list", None)
            if not isinstance(cr_list, list) or not cr_list:
                logger.warning("⚠️ [%s] Агент не вернул результат (cr_list=%r)", name, cr_list)
                return False

            cr = cr_list[-1]
            if not isinstance(cr, CaptchaResponse):
                logger.warning("⚠️ [%s] Неожиданный тип ответа: %r", name, type(cr))
                return False

            logger.info("✅ [%s] Капча решена: %s", name, safe_json(cr.model_dump(by_alias=True)))
            return True
        except asyncio.CancelledError:
            logger.info("⏹️ [%s] Решение отменено", name)
            raise
        except Exception:
            logger.exception("❌ [%s] Ошибка решения", name)
            return False

    async def _page_key(self, page: Page) -> str:
        # Стабильный ключ вкладки в пределах её жизни (JS-хэндл на window)
        try:
            return await page.evaluate(
                """() => {
                    if (!window.__hcap_page_key) {
                        const rnd = (self.crypto && self.crypto.randomUUID)
                            ? self.crypto.randomUUID()
                            : (Math.random().toString(36).slice(2)+Date.now().toString(36));
                        window.__hcap_page_key = rnd;
                    }
                    return window.__hcap_page_key;
                }"""
            )
        except Exception:
            # запасной вариант, если evaluate недоступен
            return f"py:{id(page)}"

    async def _solve_with_lock(self, page: Page, profile_id: str, key: str) -> None:
        lock = self._page_locks.setdefault(key, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            await self._solve(page, profile_id)

    async def _scan_pages(self, browser: Browser, profile_id: str) -> None:
        """Обходит все вкладки и запускает solve параллельно по вкладкам (пер-вкладочная синхронизация)."""
        name = await self._name(profile_id)
        try:
            for ctx in tuple(browser.contexts):
                for page in tuple(ctx.pages):
                    try:
                        if page.is_closed():
                            continue
                        if await self._has_hcaptcha(page):
                            logger.info("🧩 [%s] Найдена hCaptcha: %s", name, _short_url(page.url))
                            key = await self._page_key(page)
                            lock = self._page_locks.setdefault(key, asyncio.Lock())
                            if not lock.locked():
                                task = asyncio.create_task(self._solve_with_lock(page, profile_id, key))
                                self._solve_tasks.add(task)
                                task.add_done_callback(self._solve_tasks.discard)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        u = "<unknown>"
                        try:
                            u = page.url
                        except Exception:
                            pass
                        logger.debug("[%s] Ошибка обработки страницы %s: %s", name, _short_url(u), e)
        except Exception as e:
            logger.warning("[%s] Ошибка обхода страниц: %s", name, e)

    # --- CDP connect: без ретраев/backoff (одна попытка) ---
    async def _connect_over_cdp(self, ws_endpoint: str) -> Optional[Browser]:
        try:
            return await self.playwright.chromium.connect_over_cdp(ws_endpoint)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("CDP connect failed: %s", e)
            return None

    async def _monitor_profile(self, profile_id: str, ws_endpoint: str) -> None:
        name = await self._name(profile_id)
        logger.info("🚀 Мониторинг: %s (%s)", name, profile_id)
        browser: Optional[Browser] = None
        try:
            browser = await self._connect_over_cdp(ws_endpoint)
            if not browser:
                logger.error("Не удалось подключиться к %s — остановка", name)
                return

            # бесконечный горячий цикл; частоту обращений сдерживает только throttle в AdsPowerAPI
            while self._running:
                status = await to_thread(self.adspower.get_profile_debug_info, profile_id)
                if status.get("code") != 0:
                    logger.info("[%s] Профиль недоступен (%s) — выход", name, status.get("msg"))
                    break
                if status.get("data", {}).get("status", "").lower() == "inactive":
                    logger.info("[%s] Профиль Inactive — выход", name)
                    break

                await self._scan_pages(browser, profile_id)

        except asyncio.CancelledError:
            logger.info("⏹️ Мониторинг %s отменён", name)
            raise
        except Exception as e:
            logger.error("Критическая ошибка профиля %s: %s", name, e)
            logger.debug("Traceback:\n%s", traceback.format_exc())
        finally:
            self.monitored_profiles.pop(profile_id, None)
            if browser:
                try:
                    await browser.close()
                except Exception:
                    pass
            logger.info("🏁 Завершён мониторинг: %s", name)

    async def _scan_and_dispatch(self) -> None:
        logger.info("=" * 60)
        logger.info("🤖 hCaptcha Monitor для AdsPower")
        logger.info("📋 Автообнаружение и параллельное решение hCaptcha (per-tab)")
        logger.info("=" * 60)

        while self._running:
            try:
                await self._refresh_profiles_cache()

                active = await to_thread(self.adspower.get_active_profiles)
                known = set(self.monitored_profiles.keys())

                for it in active:
                    uid = str(it.get("user_id") or "")
                    ws = (it.get("ws", {}) or {}).get("puppeteer") \
                         or (it.get("ws", {}) or {}).get("playwright") \
                         or (it.get("ws", {}) or {}).get("devtools")
                    if not uid or not ws or uid in known:
                        continue

                    name = await self._name(uid)
                    self.monitored_profiles[uid] = ProfileInfo(user_id=uid, name=name, ws_endpoint=ws)
                    task = asyncio.create_task(self._monitor_profile(uid, ws))
                    self.active_tasks.add(task)
                    task.add_done_callback(self.active_tasks.discard)
                    logger.info("➕ Добавлен профиль: %s", name)

                if self.monitored_profiles:
                    names = ", ".join(p.name for p in self.monitored_profiles.values())
                    logger.info("Активных профилей: %d [%s]", len(self.monitored_profiles), names)
                else:
                    logger.info("Ожидание открытия профилей в AdsPower...")

                # без sleep; следующий цикл ограничит только AdsPower API троттлинг

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error("Ошибка discovery-цикла: %s", e)
                logger.debug("Traceback:\n%s", traceback.format_exc())
                # без sleep

    # --- lifecycle ---
    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                pass

        async with async_playwright() as p:
            self.playwright = p
            try:
                await self._scan_and_dispatch()
            finally:
                await self._shutdown()

    def stop(self) -> None:
        if self._running:
            logger.info("Получен сигнал остановки — завершаю...")
        self._running = False

    async def _shutdown(self) -> None:
        # задачи мониторинга профилей
        for t in tuple(self.active_tasks):
            if not t.done():
                t.cancel()
        if self.active_tasks:
            await asyncio.gather(*self.active_tasks, return_exceptions=True)

        # фоновые задачи solve (per-tab)
        for t in tuple(self._solve_tasks):
            if not t.done():
                t.cancel()
        if self._solve_tasks:
            await asyncio.gather(*self._solve_tasks, return_exceptions=True)

        # закрываем HTTP-сессию AdsPower
        try:
            self.adspower.close()
        except Exception:
            pass
        logger.info("Остановка завершена.")

# =========================
# ENTRY POINT
# =========================
async def main() -> None:
    monitor = CaptchaMonitor()
    try:
        await monitor.start()
    except asyncio.CancelledError:
        logger.info("Мониторинг отменён")
    except KeyboardInterrupt:
        logger.info("Остановка по запросу пользователя")
    except Exception as e:
        logger.error("Критическая ошибка: %s", e)
        logger.debug("Traceback:\n%s", traceback.format_exc())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
