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
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/json',
}

PRICES_FILE = 'prices.json'


def get_current_price(excursion_id):
    """Получить текущую цену экскурсии через API Tripster."""
    page_url = f'https://experience.tripster.ru/experience/{excursion_id}/'
    api_url = f'https://experience.tripster.ru/api/web/v2/experiences/{excursion_id}/'
    
    session = requests.Session()
    session.get(page_url, headers={'User-Agent': HEADERS['User-Agent']})
    
    resp = session.get(api_url, headers={**HEADERS, 'Referer': page_url})
    if resp.status_code == 200:
        data = resp.json()
        price_data = data.get('price', {})
        return {
            'value': price_data.get('value'),
            'currency': price_data.get('currency'),
            'unit_string': price_data.get('unit_string'),
            'value_string': price_data.get('value_string'),
            'discount': price_data.get('discount'),
        }
    else:
        raise Exception(f"API вернул статус {resp.status_code} для экскурсии {excursion_id}")


def load_last_prices():
    """Загрузить последние сохранённые цены из GitHub."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return {}
    
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{PRICES_FILE}"
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3.raw'
        }
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return json.loads(resp.text)
    except Exception as e:
        print(f"Ошибка при загрузке цен из GitHub: {e}")
    
    return {}


def save_prices(prices_data):
    """Сохранить текущие цены в GitHub."""
    if not GITHUB_TOKEN or not GITHUB_REPO:
        return
    
    try:
        owner, repo = GITHUB_REPO.split('/')
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{PRICES_FILE}"
        
        headers = {
            'Authorization': f'token {GITHUB_TOKEN}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        content = base64.b64encode(json.dumps(prices_data, ensure_ascii=False, indent=2).encode()).decode()
        
        # Получить SHA текущего файла
        resp = requests.get(url, headers=headers)
        sha = None
        if resp.status_code == 200:
            sha = resp.json().get('sha')
        
        payload = {
            'message': f'Update prices - {json.dumps({str(k): v.get("value") for k, v in prices_data.items()})}',
            'content': content,
        }
        if sha:
            payload['sha'] = sha
        
        requests.put(url, headers=headers, json=payload)
    except Exception as e:
        print(f"Ошибка при сохранении цен в GitHub: {e}")


def send_telegram_message(text):
    """Отправить сообщение в Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram не настроен")
        return False
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        'chat_id': TELEGRAM_CHAT_ID,
        'text': text,
        'parse_mode': 'HTML',
    }
    resp = requests.post(url, data=payload)
    return resp.status_code == 200


def format_price_change_message(excursion, old_price, new_price):
    """Сформировать сообщение об изменении цены."""
    old_val = old_price['value'] if old_price else "неизвестно"
    new_val = new_price['value']
    
    direction = ""
    if old_price and old_price['value'] is not None:
        if new_val > old_price['value']:
            direction = "📈 Цена выросла!"
        elif new_val < old_price['value']:
            direction = "📉 Цена снизилась!"
        else:
            direction = "🔄 Цена изменилась"
    
    page_url = f"https://experience.tripster.ru/experience/{excursion['id']}/"
    
    msg = f"""{direction}

<b>Экскурсия:</b> {excursion['title']}

<b>Была:</b> {old_val} ₽
<b>Стала:</b> {new_val} ₽"""

    if new_price.get('discount'):
        discount = new_price['discount']
        if discount.get('value'):
            msg += f"\n<b>Скидка:</b> {int(discount['value'] * 100)}% (до {discount.get('expiration_date', '?')})"
        if discount.get('original_price'):
            msg += f"\n<b>Цена без скидки:</b> {discount['original_price']} ₽"

    msg += f"\n\n🔗 <a href='{page_url}'>Открыть на Tripster</a>"
    return msg


def main():
    last_prices = load_last_prices()
    is_first_run = len(last_prices) == 0

    for excursion in EXCURSIONS:
        eid = str(excursion['id'])
        try:
            current_price = get_current_price(excursion['id'])
            old_price = last_prices.get(eid)

            if old_price is None:
                # Первый запуск для этой экскурсии
                last_prices[eid] = current_price
                print(f"[{excursion['id']}] Первый запуск. Цена: {current_price['value']} ₽")
            elif current_price['value'] != old_price['value']:
                # Цена изменилась!
                msg = format_price_change_message(excursion, old_price, current_price)
                send_telegram_message(msg)
                last_prices[eid] = current_price
                print(f"[{excursion['id']}] Цена изменилась: {old_price['value']} → {current_price['value']}. Уведомление отправлено.")
            else:
                # Проверим изменение скидки
                old_discount = old_price.get('discount') or {}
                new_discount = current_price.get('discount') or {}
                if old_discount != new_discount:
                    page_url = f"https://experience.tripster.ru/experience/{excursion['id']}/"
                    msg = f"ℹ️ Изменились условия скидки!\n\n"
                    msg += f"<b>Экскурсия:</b> {excursion['title']}\n"
                    msg += f"<b>Цена:</b> {current_price['value']} ₽\n"
                    if new_discount.get('value'):
                        msg += f"<b>Скидка:</b> {int(new_discount['value'] * 100)}% (до {new_discount.get('expiration_date', '?')})\n"
                    elif old_discount.get('value'):
                        msg += f"<b>Скидка снята</b>\n"
                    if new_discount.get('original_price'):
                        msg += f"<b>Цена без скидки:</b> {new_discount['original_price']} ₽\n"
                    msg += f"\n🔗 <a href='{page_url}'>Открыть на Tripster</a>"
                    send_telegram_message(msg)
                    last_prices[eid] = current_price
                    print(f"[{excursion['id']}] Скидка изменилась. Уведомление отправлено.")
                else:
                    last_prices[eid] = current_price
                    print(f"[{excursion['id']}] Цена не изменилась: {current_price['value']} ₽")

        except Exception as e:
            error_msg = f"⚠️ Ошибка мониторинга экскурсии {excursion['id']}:\n{str(e)}"
            print(error_msg)
            send_telegram_message(error_msg)

    save_prices(last_prices)

    if is_first_run:
        # Отправить сводку при первом запуске
        summary = "🔔 Мониторинг запущен на GitHub Actions!\n\n<b>Отслеживаемые экскурсии:</b>\n\n"
        for excursion in EXCURSIONS:
            eid = str(excursion['id'])
            price = last_prices.get(eid, {})
            page_url = f"https://experience.tripster.ru/experience/{excursion['id']}/"
            summary += f"• <a href='{page_url}'>{excursion['title'][:50]}</a>\n"
            summary += f"  Цена: {price.get('value', '?')} ₽"
            if price.get('discount') and price['discount'].get('value'):
                summary += f" (скидка {int(price['discount']['value'] * 100)}%)"
            summary += "\n\n"
        summary += "Проверка каждые 15 минут."
        send_telegram_message(summary)
        print("Первый запуск. Сводка отправлена.")


if __name__ == "__main__":
    main()
