# Используем официальный образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Устанавливаем curl для отладки сети
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем зависимости, не сохраняя кэш
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходный код бота в рабочую директорию
COPY src/bot.py .

# Указываем команду для запуска бота при старте контейнера
CMD ["python", "bot.py"]