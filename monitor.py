#!/usr/bin/env python3
"""
Мониторинг цен экскурсий на Tripster.
Проверяет цены и отправляет уведомление в Telegram при изменении.
Для использования в GitHub Actions.
"""


import requests
import json
import os
import base64
from datetime import datetime
import time # Добавляем импорт time для задержек


# Конфигурация из переменных окружения
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
GITHUB_REPO = os.getenv('GITHUB_REPO')


# Список экскурсий для мониторинга
EXCURSIONS = [
    {"id": 51192, "title": "Всё включено: магия Чёрного и Чарынского каньонов, экзотика озёр Кольсай и Каинды"},
    {"id": 57434, "title": "Природа Казахстана: 5 лучших мест за 1 день из Алматы"},
    {"id": 96862, "title": "Комфорт-маршрут по озёрам Каинды, Кольсай и Чарынскому каньону"},
    {"id": 51584, "title": "Озёра Каинды и Кольсай, Черный и Чарынский каньоны — все сокровища Алматы"},
    {"id": 85543, "title": "Топ-локации Казахстана: степи, скалы и горные озёра. Поездка из Алматы"},
    {"id": 83542, "title": "1 день красоты: каньоны Чарын и Чёрный, озёра Кольсай и Каинды"},
    {"id": 102873, "title": "В Чарынский каньон через Тигровые горы — из Алматы"},
    {"id": 62177, "title": "Из Алматы в Алтын-Эмель: горы Катутау, Актау и Поющий бархан"},
    {"id": 58617, "title": "Плато Ассы, озеро Иссык, страусиная ферма, водопад: комфорт-маршрут, джипы, мини-группа"},
    {"id": 53900, "title": "Чарынский и Лунный каньоны + озеро Кольсай: групповое фотопутешествие по окрестностям Алматы"},
    {"id": 58568, "title": "Комфорт-маршрут на внедорожнике: озёра Каинды, Кольсай, Чарынский и Чёрный каньоны"},
    {"id": 70193, "title": "Комфорт-маршрут на внедорожнике: плато Ассы, озеро Иссык и водопад"},
    {"id": 51600, "title": "Каньоны востока: приключение на внедорожнике"},
    {"id": 53155, "title": "Иссыкское озеро и Медвежий водопад"},
    {"id": 54971, "title": "Прогулка по Чарынскому и Чёрному каньонам и озеру Каинды в компании фотографа-гида"},
    {"id": 55575, "title": "Фотопрогулка по озеру Кольсай и Чарынскому каньону (в небольшой группе)"},
    {"id": 54209, "title": "Обсерватория на плато Ассы и озеро Иссык — джип-путешествие из Алматы"},
    {"id": 52987, "title": "Город кочевников, Тамгалы-Тас и Поющий бархан — за 1 день"},
    {"id": 75208, "title": "По следам древнего океана Тетис"},
    {"id": 117523, "title": "Три чуда Алматинской области: Чарын, Иссык и Медвежий водопад"},
    {"id": 120781, "title": "Чарынский каньон и озеро Кольсай с комфортом — из Алматы (всё включено)"},
    {"id": 117366, "title": "Кольсай, Каинды и каньоны Чарына — из Алматы"},
    {"id": 118832, "title": "Чарынский каньон и озеро Кольсай — из Алматы"},
    {"id": 109950, "title": "Из Алматы — к неземному Чарынскому каньону"},
]


HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}


PRICES_FILE = 'prices.json'
NOTIFICATIONS_FILE = 'sent_notifications.json'




def get_current_price(excursion_id, retries=3, delay=5):
    """Получить текущую цену экскурсии через API Tripster."""
    page_url = f'https://experience.tripster.ru/experience/{excursion_id}/'
    api_url = f'https://experience.tripster.ru/api/web/v2/experiences/{excursion_id}/'
    
    session = requests.Session()
    session.get(page_url, headers={'User-Agent': HEADERS['User-Agent']})
    
    for i in range(retries):
        try:
            resp = session.get(api_url, headers={**HEADERS, 'Referer': page_url}, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                    price_data = data.get('price', {})
                    return {
                        'value': price_data.get('value'),
