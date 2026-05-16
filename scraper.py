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

# Реальный User-Agent от обычного Chrome на Windows
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

async def fetch_rendered_html(url: str) -> str:
    """Открывает страницу через Chromium с анти-детект мерами."""
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                    '--disable-blink-features=AutomationControlled',  # убирает navigator.webdriver
                ]
            )
            context = await browser.new_context(
                user_agent=USER_AGENT,
                viewport={'width': 1920, 'height': 1080},
                locale='ru-RU'
            )
            page = await context.new_page()

            # Дополнительно скрываем факт автоматизации через JavaScript
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => false });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru'] });
                window.chrome = { runtime: {} };
            """)

            await page.goto(url, wait_until='domcontentloaded', timeout=30000)
            # Ждём ещё 3 секунды для подгрузки всех скриптов
            await asyncio.sleep(3)
            html = await page.content()
            await browser.close()
            logger.info(f"Playwright загрузил страницу, длина HTML: {len(html)} символов")
            return html
    except Exception as e:
        logger.error(f"Ошибка Playwright для {url}: {e}")
        return ""

def extract_price_from_html(html: str) -> float | None:
    """Ищет цену регуляркой в сыром HTML (без LLM)."""
    patterns = [
        r'\"price\"\s*:\s*(\d+[\.,]?\d*)',
        r'data-price\s*=\s*[\'"](\d+[\.,]?\d*)',
        r'\"цена\"\s*:\s*(\d+[\.,]?\d*)',
        r'itemprop\s*=\s*[\'"]price[\'"].+?(\d+[\.,]?\d+)',
        r'class\s*=\s*[\'"].*?price.*?[\'"].*?>.*?(\d+[\.,]?\d+)',
    ]
    for pat in patterns:
        match = re.search(pat, html, re.IGNORECASE | re.DOTALL)
        if match:
            num = match.group(1).replace(',', '.')
            try:
                price = float(num)
                if price > 0:
                    logger.info(f"Цена найдена регуляркой: {price}")
                    return price
            except ValueError:
                continue
    return None

async def fetch_price(url: str) -> float | None:
    html = await fetch_rendered_html(url)
    if not html:
        return None

    price = extract_price_from_html(html)
    if price is not None:
        return price

    # Если не вышло – очищаем и спрашиваем GigaChat
    soup = BeautifulSoup(html, 'html.parser')
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=' ', strip=True)
    text = re.sub(r'\s+', ' ', text)
    logger.info(f"Очищенный текст (первые 200 символов): {text[:200]}")
    text = text[:5000]

    prompt = (
        "Ты – парсер цен. Найди в тексте страницы актуальную цену товара в российских рублях.\n"
        "Цена может быть указана как целое число или с копейками, с пробелами, значком рубля, буквами 'руб', '₽', 'цена', 'price'.\n"
        "Извлеки только число. Если не можешь найти цену, верни 'нет'.\n\n"
        f"Текст:\n{text}"
    )

    try:
        with GigaChat(
            credentials=GIGACHAT_API_KEY,
            verify_ssl_certs=False,
            model=MODEL_NAME
        ) as giga:
            response = giga.chat(prompt)
            raw = response.choices[0].message.content.strip()
            logger.info(f"Ответ GigaChat: {raw!r}")
    except Exception as e:
        logger.error(f"Ошибка обращения к GigaChat: {e}")
        return None

    if raw.lower() == 'нет':
        return None
    match = re.search(r'\d+[\.,]?\d*', raw.replace(',', '.'))
    if match:
        return float(match.group())
    return None