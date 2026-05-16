FROM python:3.11-slim

# Системные зависимости для Chromium
RUN apt-get update && apt-get install -y \
    wget gnupg ca-certificates fonts-liberation \
    libasound2 libatk-bridge2.0-0 libatk1.0-0 libcups2 \
    libdrm2 libgbm1 libgtk-3-0 libnspr4 libnss3 \
    libx11-xcb1 libxcomposite1 libxdamage1 libxrandr2 \
    xdg-utils --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN pip install playwright && playwright install --with-deps chromium

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /app/data
COPY . .

# Добавьте эту переменную окружения, чтобы Chromium работал в ограниченной памяти
ENV PLAYWRIGHT_CHROMIUM_ARGS="--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage --disable-gpu --single-process"

CMD ["python", "bot.py"]