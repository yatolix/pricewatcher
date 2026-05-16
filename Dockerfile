FROM python:3.11-slim

WORKDIR /app

# Копируем и устанавливаем зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаём папку для базы данных
RUN mkdir -p /app/data

# Копируем весь проект
COPY . .

CMD ["python", "bot.py"]