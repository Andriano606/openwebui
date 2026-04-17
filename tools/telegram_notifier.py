"""
title: Telegram Notifier
description: Надсилає текстові повідомлення в Telegram чат через бота. Підтримує HTML теги.
version: 1.0.0
"""

import requests
from pydantic import BaseModel, Field


class Tools:
    def __init__(self):
        self.bot_token = "8764368618:AAGO8ok1cyDofBR8XBfnRYZ1OhADBS8D7LY"
        self.chat_id = "364543512"

    def send_message(
        self,
        text: str = Field(
            ..., description="Будь-який текст повідомлення для відправки в Telegram"
        ),
    ) -> str:
        """
        Універсальна функція для надсилання будь-яких текстових повідомлень у Telegram.
        Підтримує HTML теги (<b>, <i>, <code>).
        """
        if not self.bot_token:
            return "Помилка: Налаштуйте TELEGRAM_BOT_TOKEN."

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        try:
            response = requests.post(url, json=payload, timeout=10)
            response.raise_for_status()
            return "Повідомлення успішно надіслано."
        except Exception as e:
            return f"Помилка при відправці в Telegram: {str(e)}"
