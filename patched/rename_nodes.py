#!/usr/bin/env python3
import re
import requests
import json

MARZBAN_URL = "https://panel.komissarovka.ru/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJib3RhZG1pbiIsImFjY2VzcyI6InN1ZG8iLCJpYXQiOjE3Nzc1NDk3MTEsImV4cCI6MTc3NzYzNjExMX0.gQcNmLhaVdU81iKNhIvH9RhmINY3Hrx0uROx7WnsQzM"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Сопоставление стран и их флагов
COUNTRY_FLAGS = {
    "Estonia": "🇪🇪",
    "Finland": "🇫🇮",
    "France": "🇫🇷",
    "Germany": "🇩🇪",
    "Greece": "🇬🇷",
    "Latvia": "🇱🇻",
    "Lithuania": "🇱🇹",
    "Moldova": "🇲🇩",
    "Poland": "🇵🇱",
    "Sweden": "🇸🇪",
    "Netherlands": "🇳🇱",
    "United Kingdom": "🇬🇧",
    "United States": "🇺🇸",
    "Russia": "🇷🇺",
    "Anycast": "🌍"
}

# Города для разных стран
CITIES = {
    "Estonia": "Tallinn",
    "Finland": "Helsinki",
    "France": ["Paris", "Orléans"],
    "Germany": ["Frankfurt", "Falkenstein", "Frankfurt am Main"],
    "Greece": "Thessaloniki",
    "Latvia": "Riga",
    "Lithuania": "Šiauliai",
    "Moldova": "Chisinau",
    "Poland": "Warsaw",
    "Sweden": "Stockholm",
    "Netherlands": "Amsterdam",
    "United Kingdom": "London",
    "United States": "Miami",
    "Russia": ["St Petersburg", "Moscow"]
}

def get_country_from_name(name):
    """Определение страны по имени"""
    for country in COUNTRY_FLAGS:
        if country in name:
            return country
    return "Anycast"

def get_city_from_name(name):
    """Определение города по имени"""
    for country, cities in CITIES.items():
        if country in name:
            if isinstance(cities, list):
                for city in cities:
                    if city in name:
                        return city
            else:
                if cities in name:
                    return cities
    return ""

def clean_name_old(name):
    """Очистка старого имени"""
    # Убираем URL-кодировку
    name = name.replace('%F0%9F%87%AA%F0%9F%87%AA', '')
    name = name.replace('%F0%9F%87%AB%F0%9F%87%AE', '')
    name = name.replace('%F0%9F%87%AB%F0%9F%87%B7', '')
    name = name.replace('%F0%9F%87%A9%F0%9F%87%AA', '')
    name = name.replace('%F0%9F%87%AC%F0%9F%87%B7', '')
    name = name.replace('%F0%9F%87%B1%F0%9F%87%BB', '')
    name = name.replace('%F0%9F%87%B1%F0%9F%87%B9', '')
    name = name.replace('%F0%9F%87%B2%F0%9F%87%A9', '')
    name = name.replace('%F0%9F%87%B5%F0%9F%87%B1', '')
    name = name.replace('%F0%9F%87%B8%F0%9F%87%AA', '')
    name = name.replace('%F0%9F%87%B3%F0%9F%87%B1', '')
    name = name.replace('%F0%9F%87%AC%F0%9F%87%A7', '')
    name = name.replace('%F0%9F%87%BA%F0%9F%87%B8', '')
    name = name.replace('%F0%9F%87%B7%F0%9F%87%BA', '')
    name = name.replace('%F0%9F%8C%90', '')
    
    # Убираем лишнее
    name = re.sub(r'\s*\|\s*[^\s]+\s*$', '', name)
    name = re.sub(r'\s*\|\s*[🌍🇪🇺]+\s*$', '', name)
    name = re.sub(r'\s*\[BBL\]\s*$', '', name)
    name = name.strip()
    
    return name

def generate_new_name(node):
    """Генерация нового имени для ноды"""
    old_name = node.get("name", "")
    country = get_country_from_name(old_name)
    city = get_city_from_name(old_name)
    flag = COUNTRY_FLAGS.get(country, "🌍")
    
    # Особая обработка для России
    if country == "Russia":
        if city == "St Petersburg":
            return f"{flag} LTE Russia #1 (Saint Petersburg)"
        elif city == "Moscow":
            return f"{flag} LTE Russia #2 (Moscow)"
        else:
            return f"{flag} LTE Russia #{node.get('id', '')}"
    
    # Для остальных стран
    if city:
        return f"{flag} {country} - {city}"
    else:
        return f"{flag} {country}"

def get_nodes():
    """Получение всех нод"""
    response = requests.get(f"{MARZBAN_URL}/nodes", headers=HEADERS)
    data = response.json()
    if isinstance(data, dict):
        return data.get("response", [])
    return data

def update_node_name(node_id, new_name):
    """Обновление имени ноды"""
    try:
        response = requests.put(
            f"{MARZBAN_URL}/node/{node_id}",
            headers=HEADERS,
            json={"name": new_name}
        )
        if response.status_code in [200, 204]:
            return True
        else:
            print(f"      Ошибка {response.status_code}: {response.text}")
            return False
    except Exception as e:
        print(f"      Ошибка: {e}")
        return False

def main():
    print("📡 Получение списка нод из Marzban...")
    nodes = get_nodes()
    print(f"Найдено {len(nodes)} нод\n")
    
    print("🔄 Переименование нод...\n")
    renamed = 0
    
    for node in nodes:
        old_name = node.get("name", "")
        node_id = node.get("id")
        
        if not node_id:
            continue
        
        new_name = generate_new_name(node)
        
        if old_name != new_name:
            print(f"  Нода #{node_id}:")
            print(f"    Было: {old_name[:60]}...")
            print(f"    Стало: {new_name}")
            if update_node_name(node_id, new_name):
                renamed += 1
                print(f"    ✅ Переименовано")
            else:
                print(f"    ❌ Ошибка")
            print()
        else:
            print(f"  Нода #{node_id}: {old_name[:50]}... (без изменений)")
    
    print(f"\n✅ Переименовано {renamed} нод")

if __name__ == "__main__":
    main()
