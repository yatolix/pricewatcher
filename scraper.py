import asyncio
import os
import re
import logging
import uuid
import requests
import aiohttp
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import urllib3

# Отключаем предупреждения о неверифицированных SSL-соединениях
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

GIGACHAT_API_KEY = os.getenv("GIGACHAT_API_KEY")
MODEL_NAME = "GigaChat-2-Lite"

async def fetch_and_clean_html(url: str) -> str:
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
        return text[:3000]
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
        # Получение токена
        token_url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
        token_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'RqUID': str(uuid.uuid4()),
            'Authorization': f'Basic {GIGACHAT_API_KEY}'
        }
        token_data = {'scope': 'GIGACHAT_API_PERS'}
        resp = requests.post(
            token_url,
            headers=token_headers,
            data=token_data,
            timeout=10,
            verify=False  # <-- Отключаем проверку SSL (на случай проблем с сертификатом)
        )
        resp.raise_for_status()
        access_token = resp.json()['access_token']
        logger.info("Токен GigaChat получен успешно")

        # Запрос к модели
        chat_url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        chat_headers = {
            'Authorization': f'Bearer {access_token}',
            'Content-Type': 'application/json'
        }
        chat_body = {
            "model": MODEL_NAME,
            "messages": [
                {"role": "system", "content": "Ты точный парсер цен. Отвечай только числом или 0."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.0,
            "max_tokens": 20
        }
        resp = requests.post(
            chat_url,
            headers=chat_headers,
            json=chat_body,
            timeout=30,
            verify=False  # <-- Здесь тоже отключаем проверку SSL
        )
        resp.raise_for_status()
        raw = resp.json()['choices'][0]['message']['content'].strip()
        logger.info(f"Ответ GigaChat: {raw!r}")

        match = re.search(r'\d+[\.,]?\d*', raw.replace(',', '.'))
        if match:
            price = float(match.group())
            logger.info(f"Извлечена цена: {price}")
            return price
        else:
            logger.warning(f"Не удалось распарсить число из ответа: {raw!r}")
            return None
    except Exception as e:
        logger.error(f"Ошибка обращения к GigaChat: {e}")
        return None