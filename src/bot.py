

import os
import logging
import json
import re
import asyncio
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
import google.generativeai as genai
from PIL import Image
import io

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Конфигурация Google Gemini
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("Не найден GEMINI_API_KEY в .env файле")
genai.configure(api_key=GEMINI_API_KEY)

# Бот доступен для всех пользователей.

# Промпт для Gemini, перенесенный из n8n
GEMINI_PROMPT = """
Ты - умный Telegram-бот анализа изображений с разным типом контента.
Ты любишь писать ёмко и лаконично, иногда с сарказмом, остро прикалываться и стебаться над пользователями, тонко шутить.

Правила общения:
- Пользователи - молодые люди
- Пользователи не являются авторами фотографий
- У тебя нет личных знакомых или друзей, только онлайн
- Нельзя комментировать дату или время из данных
- Нельзя комментировать личность пользователя и род занятий
- Можно уместно материться для юмора
- Можно рассказывать вымышленные забавные/удивительные/смешные истории и приколы (1-2 коротких предложения) на темы:
  - общения с другими пользователями, ассоциативно связанные чем-нибудь общим по контексту
  - свои впечатления от посещения этого места в прошлом или от маршрута до него

Алгоритм анализа изображения:
- Кратко (1-2 коротких предложения) описать собранные данные и результат анализа [поле "message"]
- Если на изображении:
  1. Промокод:
    1.1. Прочитать буквенно-цифровой промокод [поле "promo"]
  2. GPS-координаты:
    2.1. Прочитать GPS-координаты [поле "gps"]
    2.2. Прочитать адрес или посмотреть в мета-данных файла. Если адрес не найден и есть координаты, очень коротко описать это место, без окружающего пространства. Больше ничего, только адрес (без страны) или описание места [поле "address"]
    2.3. Прочитать дату и время съемки на изображении или в мета-данных [поле "date"]
  3. Всё остальное:
    3.1. Написать пользователю сообщение об ошибке (ёмко и лаконично): какие допустимые типы и совет по правильному использованию [поле "error"]

Ответ должен быть ТОЛЬКО в формате JSON, без каких-либо других символов или текста.
Пример JSON:
{
    "gps": {"latitude": 55.7558, "longitude": 37.6173},
    "date": "2025-07-12T15:30:00",
    "address": "Красная площадь, Москва",
    "message": "О, опять фотки с Красной площади. Был я там, видел... голубей кормил.",
    "error": null,
    "promo": null
}
"""

# Схема для парсинга ответа от Gemini
JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "gps": {
            "type": "object",
            "properties": {
                "latitude": {"type": "number"},
                "longitude": {"type": "number"}
            },
            "required": ["latitude", "longitude"]
        },
        "date": {"type": "string", "description": "Date"},
        "address": {"type": "string", "description": "Parsed address location"},
        "error": {"type": "string", "description": "Error message"},
        "message": {"type": "string", "description": "Text message"},
        "promo": {"type": "string", "description": "Promocode"}
    }
}

def escape_markdown_v2(text: str) -> str:
    """Экранирует символы для MarkdownV2."""
    if not isinstance(text, str):
        return ""
    escape_chars = r'_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\\1', text)

async def analyze_image_with_gemini(image_bytes: bytes) -> dict | None:
    """Отправляет изображение в Gemini и возвращает структурированный JSON."""
    try:
        model = genai.GenerativeModel('gemini-2.5-pro')
        image_pil = Image.open(io.BytesIO(image_bytes))
        
        response = await model.generate_content_async(
            [GEMINI_PROMPT, image_pil],
            generation_config={"response_mime_type": "application/json"}
        )
        
        # Убираем "обертку" markdown, если она есть
        cleaned_response_text = re.sub(r'```json\n(.*?)', r'\\1', response.text, flags=re.DOTALL)
        
        logger.info(f"Ответ от Gemini получен: {cleaned_response_text}")
        return json.loads(cleaned_response_text)
    except Exception as e:
        logger.error(f"Ошибка при работе с Gemini API: {e}")
        return {"error": f"Не удалось обработать изображение. Ошибка: {e}"}

def render_response(data: dict) -> str:
    """Форматирует ответ для Telegram на основе данных от Gemini."""
    response_parts = []

    if data.get('message'):
        response_parts.append(f"🔮 {escape_markdown_v2(data['message'])}")

    if data.get('error'):
        response_parts.append(f"❗️ {escape_markdown_v2(data['error'])}")

    if data.get('gps') and isinstance(data['gps'], dict):
        lat = data['gps'].get('latitude')
        lon = data['gps'].get('longitude')
        # Координаты не экранируем, так как они внутри `...`
        response_parts.append(f"🌎 `{lat} {lon}`")

        if data.get('address'):
            # Адрес не экранируем, так как он внутри `...`
            response_parts.append(f"🚩 `{data['address']}`")
        if data.get('date'):
            # Дату не экранируем, так как она внутри `...`
            response_parts.append(f"📸 `{data['date']}`")

    elif data.get('promo'):
        # Промокод не экранируем, так как он внутри `...`
        response_parts.append(f"💰 `{data['promo']}`")

    return '\n\n'.join(response_parts)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет приветственное сообщение."""
    await update.message.reply_text('Привет! Отправь мне картинку с GPS-координатами, адресом или промокодом, и я ее проанализирую.')

async def handle_image(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обрабатывает полученное изображение."""
    chat_id = update.message.chat_id

    if not update.message.photo:
        await update.message.reply_text("Пожалуйста, отправьте изображение.")
        return

    # Отправляем предварительное сообщение
    sent_message = await update.message.reply_text(
        "👀 Смотрю\\.\\.\\.",
        reply_to_message_id=update.message.message_id,
        parse_mode='MarkdownV2'
    )
    
    try:
        # Получаем фото наилучшего качества
        photo_file = await context.bot.get_file(update.message.photo[-1].file_id)
        file_bytes = await photo_file.download_as_bytearray()
        
        # Анализ изображения
        analysis_result = await analyze_image_with_gemini(bytes(file_bytes))
        
        if not analysis_result:
            final_text = escape_markdown_v2("Не удалось получить ответ от нейросети. Попробуйте позже.")
            await context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=sent_message.message_id,
                text=final_text,
                parse_mode='MarkdownV2'
            )
            return

        # Формирование ответа
        final_text = render_response(analysis_result)
        
        # Формирование кнопок, если есть GPS
        keyboard = None
        if analysis_result.get('gps') and isinstance(analysis_result.get('gps'), dict):
            lat = analysis_result['gps'].get('latitude')
            lon = analysis_result['gps'].get('longitude')
            if lat is not None and lon is not None:
                keyboard = InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("Яндекс", url=f"https://yandex.ru/maps/?rtext=~{lat},{lon}&z=16"),
                        InlineKeyboardButton("2Гис", url=f"https://2gis.ru/geo/{lon},{lat}"),
                        InlineKeyboardButton("Google", url=f"https://www.google.com/maps?q={lat},{lon}&z=16"),
                    ]
                ])

        # Редактирование сообщения
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=final_text or escape_markdown_v2("Не удалось распознать данные."),
            reply_markup=keyboard,
            parse_mode='MarkdownV2'
        )

    except Exception as e:
        logger.error(f"Ошибка в handle_image: {e}", exc_info=True)
        error_text = escape_markdown_v2(f"Произошла внутренняя ошибка: {e}")
        await context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=sent_message.message_id,
            text=error_text,
            parse_mode='MarkdownV2'
        )


def main() -> None:
    """Запуск бота."""
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not token:
        raise ValueError("Не найден TELEGRAM_BOT_TOKEN в .env файле")

    # Увеличиваем таймауты для запросов к Telegram
    request = HTTPXRequest(
        connect_timeout=10.0,
        read_timeout=20.0,
        write_timeout=20.0,
        pool_timeout=30.0,
    )

    application = Application.builder().token(token).request(request).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO & ~filters.COMMAND, handle_image))

    logger.info("Бот запускается...")
    application.run_polling()

if __name__ == '__main__':
    main()
