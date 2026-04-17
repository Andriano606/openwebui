"""
title: Chrome Browser Control
author: local
version: 1.0.0
description: >
  Керує браузером Chrome у Docker-контейнері через CDP (Chrome DevTools Protocol).
  Дозволяє відкривати сторінки, читати вміст, отримувати посилання,
  клікати, вводити текст та прокручувати.

  Налаштування у Valves:
    CHROME_HOST — chrome-vnc (якщо OpenWebUI у тій самій docker network)
                  або localhost (якщо запущено без Docker)
    CHROME_PORT — 9222 (за замовчуванням)
requirements: websocket-client
"""

import json
import time

import requests as _requests
import websocket
from pydantic import BaseModel, Field


class Tools:

    class Valves(BaseModel):
        CHROME_HOST: str = Field(
            default="chrome-vnc",
            description=(
                "Хост Chrome-контейнера. "
                "Використовуй 'chrome-vnc' якщо OpenWebUI в тій самій docker network, "
                "'localhost' якщо запускаєш локально."
            ),
        )
        CHROME_PORT: int = Field(
            default=9222,
            description="CDP-порт Chrome (default: 9222).",
        )
        PAGE_LOAD_TIMEOUT: float = Field(
            default=12.0,
            description="Скільки секунд чекати завантаження сторінки.",
        )
        MAX_CONTENT_LENGTH: int = Field(
            default=6000,
            description="Максимум символів у відповіді (щоб не переповнити контекст).",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _base_url(self) -> str:
        return f"http://{self.valves.CHROME_HOST}:{self.valves.CHROME_PORT}"

    def _get_tab_ws_url(self) -> str:
        """Повертає WebSocket URL першої активної вкладки."""
        try:
            tabs = _requests.get(f"{self._base_url()}/json", timeout=5).json()
        except Exception as e:
            raise RuntimeError(
                f"Не вдалося з'єднатися з Chrome на {self._base_url()}. "
                f"Перевір що контейнер запущений і порт 9222 відкритий. ({e})"
            )
        pages = [t for t in tabs if t.get("type") == "page"]
        if not pages:
            raise RuntimeError("Chrome запущений, але відкритих вкладок немає.")
        return pages[0]["webSocketDebuggerUrl"]

    def _ws_connect(self) -> websocket.WebSocket:
        return websocket.create_connection(self._get_tab_ws_url(), timeout=30)

    def _send(self, ws, cmd_id: int, method: str, params: dict = None):
        ws.send(json.dumps({"id": cmd_id, "method": method, "params": params or {}}))

    def _read_until(
        self, ws, target_ids: set, extra_events: set = None, timeout: float = 15.0
    ) -> dict:
        """
        Читає повідомлення CDP поки не отримає всі target_ids (відповіді на команди)
        і опціонально extra_events (event-методи, наприклад 'Page.loadEventFired').
        Повертає словник id → result.
        """
        results = {}
        events_seen = set()
        extra_events = extra_events or set()
        deadline = time.time() + timeout
        pending_ids = set(target_ids)
        pending_events = set(extra_events)

        while time.time() < deadline and (pending_ids or pending_events):
            try:
                ws.settimeout(min(2.0, deadline - time.time()))
                msg = json.loads(ws.recv())
            except Exception:
                break
            msg_id = msg.get("id")
            method = msg.get("method", "")
            if msg_id in pending_ids:
                results[msg_id] = msg.get("result", {})
                pending_ids.discard(msg_id)
            if method in pending_events:
                events_seen.add(method)
                pending_events.discard(method)

        return results

    # JavaScript що вставляється у кожну сторінку перед її завантаженням.
    # Прибирає всі маркери автоматизації які перевіряє Cloudflare.
    _STEALTH_JS = """
    (() => {
      // Прибрати navigator.webdriver
      Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

      // Підробити navigator.plugins (порожній у headless)
      Object.defineProperty(navigator, 'plugins', {
        get: () => [1, 2, 3, 4, 5],
      });

      // Підробити navigator.languages
      Object.defineProperty(navigator, 'languages', {
        get: () => ['uk-UA', 'uk', 'en-US', 'en'],
      });

      // Прибрати chrome.runtime ознаки автоматизації
      if (window.chrome) {
        const originalQuery = window.chrome.runtime?.connect;
        if (originalQuery) {
          window.chrome.runtime.connect = (...args) => originalQuery(...args);
        }
      }

      // Фіксуємо WebGL vendor (у Docker може бути підозрілим)
      const getParam = WebGLRenderingContext.prototype.getParameter;
      WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Intel Inc.';
        if (param === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.call(this, param);
      };
    })();
    """

    def _inject_stealth(self, ws):
        """Вставляє stealth-скрипт у кожну нову сторінку через Page.addScriptToEvaluateOnNewDocument."""
        self._send(ws, 98, "Page.enable")
        self._send(
            ws,
            99,
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": self._STEALTH_JS},
        )
        self._read_until(ws, {98, 99}, timeout=5)

    def _navigate_and_wait(self, ws, url: str):
        """Вставляє stealth, відкриває URL і чекає на Page.loadEventFired."""
        self._inject_stealth(ws)
        self._send(ws, 2, "Page.navigate", {"url": url})
        self._read_until(
            ws,
            target_ids={2},
            extra_events={"Page.loadEventFired"},
            timeout=self.valves.PAGE_LOAD_TIMEOUT,
        )

    def _js(self, ws, cmd_id: int, expression: str) -> str:
        """Виконує JavaScript і повертає рядковий результат."""
        self._send(
            ws,
            cmd_id,
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
            },
        )
        results = self._read_until(ws, {cmd_id}, timeout=10)
        return results.get(cmd_id, {}).get("result", {}).get("value", "")

    def _truncate(self, text: str) -> str:
        limit = self.valves.MAX_CONTENT_LENGTH
        if len(text) > limit:
            return (
                text[:limit]
                + f"\n\n[... скорочено: показано {limit} з {len(text)} символів ...]"
            )
        return text

    # ── Public tools ──────────────────────────────────────────────────────────

    def navigate(self, url: str) -> str:
        """
        Відкрити URL у браузері та повернути текстовий вміст сторінки.
        Використовуй коли потрібно відвідати сайт і прочитати його вміст.
        :param url: повна URL-адреса, наприклад https://example.com
        :return: заголовок та текстовий вміст сторінки
        """
        ws = self._ws_connect()
        try:
            self._navigate_and_wait(ws, url)
            title = self._js(ws, 10, "document.title")
            text = self._js(ws, 11, "document.body.innerText")
            current_url = self._js(ws, 12, "location.href")
            return self._truncate(f"# {title}\nURL: {current_url}\n\n{text}")
        finally:
            ws.close()

    def get_page_content(self) -> str:
        """
        Отримати текстовий вміст поточної відкритої сторінки без навігації.
        Використовуй щоб перечитати вже відкриту сторінку або після кліку.
        :return: заголовок та текстовий вміст поточної сторінки
        """
        ws = self._ws_connect()
        try:
            title = self._js(ws, 1, "document.title")
            text = self._js(ws, 2, "document.body.innerText")
            url = self._js(ws, 3, "location.href")
            return self._truncate(f"# {title}\nURL: {url}\n\n{text}")
        finally:
            ws.close()

    def get_links(self) -> str:
        """
        Отримати список посилань з поточної сторінки.
        Корисно для навігації по сайту або знаходження потрібних розділів.
        :return: список посилань у форматі Markdown
        """
        ws = self._ws_connect()
        try:
            expr = """JSON.stringify(
              Array.from(document.querySelectorAll('a[href]'))
                .map(a => ({
                  text: a.innerText.trim().replace(/\\s+/g, ' '),
                  href: a.href
                }))
                .filter(l => l.href.startsWith('http') && l.text.length > 0 && l.text.length < 150)
                .slice(0, 60)
            )"""
            raw = self._js(ws, 1, expr)
            links = json.loads(raw) if raw else []
            if not links:
                return "Посилань не знайдено на поточній сторінці."
            return "\n".join(f"- [{l['text']}]({l['href']})" for l in links)
        finally:
            ws.close()

    def click_element(self, selector: str) -> str:
        """
        Клікнути на елемент за CSS-селектором.
        Наприклад: 'button#submit', 'a[href*="login"]', '.nav-item:first-child'
        :param selector: CSS-селектор елемента для кліку
        :return: результат — знайдено та натиснуто чи ні
        """
        ws = self._ws_connect()
        try:
            safe = selector.replace("\\", "\\\\").replace("'", "\\'")
            expr = f"""(() => {{
              const el = document.querySelector('{safe}');
              if (!el) return 'не знайдено: {safe}';
              el.scrollIntoView({{behavior: 'instant', block: 'center'}});
              el.click();
              const label = (el.innerText || el.value || el.getAttribute('aria-label') || '').trim().slice(0, 60);
              return 'натиснуто: <' + el.tagName.toLowerCase() + '> "' + label + '"';
            }})()"""
            return self._js(ws, 1, expr) or "Невідомий результат"
        finally:
            ws.close()

    def click_by_text(self, text: str, tag: str = "*") -> str:
        """
        Клікнути на елемент за його видимим текстом.
        Використовуй коли не знаєш CSS-селектор, але знаєш текст кнопки або посилання.
        Наприклад: text='Увійти', text='Submit', text='Далі'
        :param text: видимий текст елемента (точний або частковий)
        :param tag: HTML-тег для звуження пошуку: 'button', 'a', '*' (будь-який, за замовчуванням)
        :return: результат — знайдено та натиснуто чи ні
        """
        ws = self._ws_connect()
        try:
            safe_text = text.replace("\\", "\\\\").replace("'", "\\'")
            safe_tag = tag.replace("'", "\\'")
            expr = f"""(() => {{
              const INTERACTIVE = ['a', 'button', 'input', 'label', 'summary'];
              const tag = '{safe_tag}';
              const selectors = tag === '*'
                ? [...INTERACTIVE, '*']
                : [tag];
              let el = null;
              for (const sel of selectors) {{
                const candidates = Array.from(document.querySelectorAll(sel));
                el = candidates.find(e => e.innerText.trim() === '{safe_text}')
                  || candidates.find(e => e.innerText.trim().includes('{safe_text}'));
                if (el) break;
              }}
              if (!el) return 'не знайдено елемент з текстом: {safe_text}';
              el.scrollIntoView({{behavior: 'instant', block: 'center'}});
              el.click();
              const label = (el.innerText || '').trim().slice(0, 60);
              return 'натиснуто: <' + el.tagName.toLowerCase() + '> "' + label + '"';
            }})()"""
            return self._js(ws, 1, expr) or "Невідомий результат"
        finally:
            ws.close()

    def type_text(self, selector: str, text: str) -> str:
        """
        Ввести текст у поле введення (input, textarea, search) за CSS-селектором.
        :param selector: CSS-селектор поля, наприклад 'input[name="q"]' або '#search-box'
        :param text: текст для введення
        :return: результат операції
        """
        ws = self._ws_connect()
        try:
            safe_sel = selector.replace("\\", "\\\\").replace("'", "\\'")
            safe_text = text.replace("\\", "\\\\").replace("'", "\\'")
            expr = f"""(() => {{
              const el = document.querySelector('{safe_sel}');
              if (!el) return 'поле не знайдено: {safe_sel}';
              el.focus();
              el.value = '{safe_text}';
              el.dispatchEvent(new Event('input', {{bubbles: true}}));
              el.dispatchEvent(new Event('change', {{bubbles: true}}));
              return 'введено у <' + el.tagName.toLowerCase() + '> id="' + (el.id || el.name || '?') + '"';
            }})()"""
            return self._js(ws, 1, expr)
        finally:
            ws.close()

    def scroll(self, direction: str = "down", amount: int = 500) -> str:
        """
        Прокрутити сторінку вгору або вниз.
        :param direction: напрямок — 'down' (вниз) або 'up' (вгору)
        :param amount: кількість пікселів (default: 500)
        :return: нова позиція прокрутки
        """
        ws = self._ws_connect()
        try:
            px = amount if direction == "down" else -amount
            pos = self._js(
                ws, 1, f"window.scrollBy(0, {px}); Math.round(window.scrollY)"
            )
            return f"Прокручено {direction} на {abs(px)}px. Позиція від верху: {pos}px."
        finally:
            ws.close()
