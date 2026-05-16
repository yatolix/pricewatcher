import asyncio
import aiohttp
import re
import os
import logging
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from gigachat import GigaChat

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

# Конфигурация GigaChat
GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
MODEL_NAME = "gigachat-2-lite"  # Самая дешёвая и быстрая модель

async def fetch_and_clean_html(url: str) -> str:
    """Загружает страницу и извлекает видимый текст, убирая мусор."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=20, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }) as resp:
                html = await resp.text()
                logger.info(f"Страница загружена, длина HTML: {len(html)} символов")
        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=' ', strip=True)
        text = re.sub(r'\s+', ' ', text)
        logger.info(f"Очищенный текст (первые 200 символов): {text[:200]}")
        return text[:3000]  # Ограничиваем длину для экономии токенов
    except Exception as e:
        logger.error(f"Ошибка загрузки страницы {url}: {e}")
        return ""

async def fetch_price(url: str) -> float | None:
    page_text = await fetch_and_clean_html(url)
    if not page_text:
        return None

    prompt = (
        "Внимательно прочитай текст страницы товара и найди актуальную цену в рублях. "
        "Цена может быть указана как целое число или с копейками (десятичная точка). "
        "Верни ТОЛЬКО число, например: 2499.99 или 1500. "
        "Если цены нет в тексте, верни 0.\n\n"
        f"Текст страницы:\n{page_text}"
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

    # Извлекаем число
    match = re.search(r'\d+[\.,]?\d*', raw.replace(',', '.'))
    if match:
        price = float(match.group())
        logger.info(f"Извлечена цена: {price}")
        return price
    else:
        logger.warning(f"Не удалось распарсить число из ответа: {raw!r}")
        return None