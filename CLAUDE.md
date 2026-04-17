# OpenWebUI — робоча документація

## Загальна архітектура

Два Docker-контейнери в спільній мережі `chrome-vnc_default`:

```
[Користувач]
     │
     ▼
open-webui  (localhost:3000)
     │  chrome-vnc_default network
     ▼
chrome-vnc  (chrome-vnc:9222 / chrome:9222)
     │
     ▼  CDP
  Google Chrome
```

**Мета цього проекту:** розширювати можливості бота — писати Tools, промти, pipelines — щоб Open WebUI мав доступ до інтернету та інших можливостей через Chrome.

---

## Контейнери

### open-webui

- **Image:** `ghcr.io/open-webui/open-webui:main`
- **URL:** http://localhost:3000
- **Мережі:** `bridge` + `chrome-vnc_default`
- **DNS-імена:** `open-webui`
- **Volume:** `open-webui:/app/data`
- **Ollama:** вбудований (`OLLAMA_BASE_URL=/ollama`)

### chrome-vnc

- **Image:** `chrome-vnc:latest`
- **Розташування:** `/home/andrii/Documents/docker/chrome-vnc`
- **Мережі:** `chrome-vnc_default`
- **DNS-імена:** `chrome-vnc`, `chrome`
- **Порти:**

| Порт | Призначення |
|------|-------------|
| 6080 | noVNC web UI (`http://localhost:6080/vnc.html`) |
| 5900 | VNC-клієнт |
| 9222 | CDP зовнішній → 9221 внутрішній |

---

## Папка tools/

Тут зберігаються всі Tools для Open WebUI — як вже наявні (скопійовані з контейнера), так і нові що розробляються.

**Встановлення в Open WebUI:** Workspace → Tools → + New Tool → вставити вміст файлу.

| Файл | Назва | Опис |
|------|-------|------|
| `chrome_browser_control.py` | Chrome Browser Control | Керування браузером через CDP: navigate, click, type, scroll |
| `telegram_notifier.py` | Telegram Notifier | Надсилання повідомлень у Telegram чат |

---

## chrome-vnc — внутрішня архітектура

```
Xvfb (:1) → Chrome (:9221) → cdp_proxy.py (:9222)
                  ↓
         x11vnc → noVNC (:6080)
```

- **`start.sh`** — запуск стека + watchdog авторестарту Chrome
- **`cdp_proxy.py`** — TCP reverse proxy: переписує `Host` і `ws://localhost` → `ws://chrome-vnc:9222`
- **`example.py`** — приклади: CDP підключення + undetected-chromedriver для Cloudflare

