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