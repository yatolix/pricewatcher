import asyncio
import os
import re
import logging
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from gigachat import GigaChat
from playwright.async_api import async_playwright

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
MODEL_NAME = "GigaChat-2"  # Lite

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

async def fetch_rendered_html(url: str) -> str:
    """Запускает браузер с пониженным потреблением памяти и повторной попыткой при падении."""
    for attempt in range(2):
        try:
            async with async_playwright() as p:
                # Первая попытка — с легковесными флагами
                args = [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-features=TranslateUI,BlinkGenPropertyTrees',
                    '--disable-ipc-flooding-protection',
                    '--memory-pressure-off',
                    '--disable-background-timer-throttling',
                    '--disable-renderer-backgrounding',
                    '--disable-hang-monitor',
                ]
                if attempt == 1:
                    # Вторая попытка — ещё агрессивнее (один процесс)
                    args.append('--single-process')

                browser = await p.chromium.launch(headless=True, args=args)
                context = await browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={'width': 1280, 'height': 720},  # уменьшили разрешение
                    locale='ru-RU'
                )
                page = await context.new_page()

                # Отключаем загрузку изображений, чтобы сэкономить трафик и память
                await page.route("**/*.{png,jpg,jpeg,gif,svg,webp}", lambda route: route.abort())
                # Отключаем шрифты (необязательно, можно закомментировать)
                await page.route("**/*.{woff,woff2,ttf,otf,eot}", lambda route: route.abort())

                # Скрываем автоматизацию
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => false });
                """)

                await page.goto(url, wait_until='domcontentloaded', timeout=30000)
                await asyncio.sleep(2)
                html = await page.content()
                await browser.close()
                logger.info(f"Playwright загрузил страницу, длина HTML: {len(html)} символов")
                return html
        except Exception as e:
            logger.error(f"Попытка {attempt+1} не удалась: {e}")
            if attempt == 1:
                logger.error("Все попытки исчерпаны.")
                return ""
            # Ждём перед повтором
            await asyncio.sleep(1)

    return ""

# ... остальные функции без изменений (extract_price_from_html, fetch_price) ...