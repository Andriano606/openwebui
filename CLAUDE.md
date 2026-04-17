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

| Порт | Призначення                                     |
| ---- | ----------------------------------------------- |
| 6080 | noVNC web UI (`http://localhost:6080/vnc.html`) |
| 5900 | VNC-клієнт                                      |
| 9222 | CDP зовнішній → 9221 внутрішній                 |

---
