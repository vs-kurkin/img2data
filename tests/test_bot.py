import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

# Добавляем путь к исходникам в sys.path для импорта
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../src')))

from bot import escape_markdown_v2, render_response, analyze_image_with_gemini, handle_image

# Тесты для вспомогательных функций

def test_escape_markdown_v2():
    assert escape_markdown_v2("Hello. World!") == "Hello\\. World\\!"
    assert escape_markdown_v2("_*[]()~`>#+-=|{}.!") == "\\_\\*\[\]\\(\\)\\~\\`\\>\\#\\+\\-\\=\\|\\{\}\\.\\!"
    assert escape_markdown_v2("No special chars") == "No special chars"
    assert escape_markdown_v2("") == ""

def test_render_response_full_data():
    data = {
        'message': 'Test message',
        'gps': {'latitude': 12.34, 'longitude': 56.78},
        'address': 'Test address',
        'date': '2025-01-01',
        'promo': 'TESTPROMO', # Этот ключ будет проигнорирован, так как есть GPS
        'error': 'Test error'
    }
    expected = "🔮 Test message\\n\\n❗️ Test error\\n\\n🌎 `12.34 56.78`\\n\\n🚩 `Test address`\\n\\n📸 `2025-01-01`"
    assert render_response(data) == expected

def test_render_response_only_promo():
    data = {'promo': 'PROMO123', 'message': 'Got a promo!'}
    expected = "🔮 Got a promo!\\n\\n💰 `PROMO123`"
    assert render_response(data) == expected

def test_render_response_only_error():
    data = {'error': 'Something went wrong'}
    expected = "❗️ Something went wrong"
    assert render_response(data) == expected

def test_render_response_empty():
    assert render_response({}) == ""

# Тесты для асинхронных функций с использованием pytest-asyncio и моков

@pytest.mark.asyncio
@patch('bot.genai.GenerativeModel')
async def test_analyze_image_with_gemini_success(MockGenerativeModel):
    # Настройка мока
    mock_response = MagicMock()
    mock_response.text = '```json\n{"message": "Success"}\n```'
    
    mock_model_instance = MockGenerativeModel.return_value
    mock_model_instance.generate_content_async = AsyncMock(return_value=mock_response)

    # Вызов функции
    image_bytes = b'fake-image-data'
    result = await analyze_image_with_gemini(image_bytes)

    # Проверки
    assert result == {"message": "Success"}
    mock_model_instance.generate_content_async.assert_called_once()

@pytest.mark.asyncio
@patch('bot.genai.GenerativeModel')
async def test_analyze_image_with_gemini_api_error(MockGenerativeModel):
    # Настройка мока для вызова исключения
    mock_model_instance = MockGenerativeModel.return_value
    mock_model_instance.generate_content_async.side_effect = Exception("API Failure")

    # Вызов функции
    result = await analyze_image_with_gemini(b'fake-image-data')

    # Проверки
    assert "error" in result
    assert "API Failure" in result["error"]

@pytest.mark.asyncio
async def test_handle_image_flow():
    # --- Создание мок-объектов Telegram ---
    update = MagicMock()
    context = MagicMock()
    
    # Мок для chat
    update.message.chat.id = 12345 # ID чата теперь не важен, но нужен для вызовов API
    update.message.message_id = 54321
    
    # Мок для photo
    photo_size = MagicMock()
    photo_size.file_id = 'file_id_123'
    update.message.photo = [photo_size]
    
    # Мок для bot
    context.bot = AsyncMock()
    context.bot.get_file.return_value.download_as_bytearray = AsyncMock(return_value=b'fake_image')
    
    # Мок для отправленного сообщения
    sent_message = MagicMock()
    sent_message.message_id = 54322
    context.bot.send_message.return_value = sent_message # Используем send_message для простоты мока
    update.message.reply_text = AsyncMock(return_value=sent_message)

    # --- Мокирование зависимостей --- 
    with patch('bot.analyze_image_with_gemini', new_callable=AsyncMock) as mock_analyze:
        # Настраиваем, что вернет Gemini
        gemini_result = {
            'message': 'Анализ успешен',
            'gps': {'latitude': 55.75, 'longitude': 37.61}
        }
        mock_analyze.return_value = gemini_result

        # --- Вызов обработчика ---
        await handle_image(update, context)

        # --- Проверки ---
        
        # 1. Проверяем, что было отправлено начальное сообщение
        update.message.reply_text.assert_called_once_with(
            "👀 Смотрю\\.\\.\\.",
            reply_to_message_id=54321,
            parse_mode='MarkdownV2'
        )

        # 2. Проверяем, что был вызван анализ изображения
        mock_analyze.assert_called_once_with(b'fake_image')

        # 3. Проверяем, что сообщение было отредактировано с правильным текстом и кнопками
        final_text_call = context.bot.edit_message_text.call_args
        assert final_text_call.kwargs['chat_id'] == 12345
        assert final_text_call.kwargs['message_id'] == 54322
        assert "Анализ успешен" in final_text_call.kwargs['text']
        assert "55.75 37.61" in final_text_call.kwargs['text']
        assert final_text_call.kwargs['reply_markup'] is not None # Проверяем, что клавиатура была создана
