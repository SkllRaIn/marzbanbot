#!/usr/bin/env python3
import re
import requests
import json

# Настройки
MARZBAN_URL = "https://panel.komissarovka.ru/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJib3RhZG1pbiIsImFjY2VzcyI6InN1ZG8iLCJpYXQiOjE3Nzc1NDk3MTEsImV4cCI6MTc3NzYzNjExMX0.gQcNmLhaVdU81iKNhIvH9RhmINY3Hrx0uROx7WnsQzM"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

def parse_vless_link(line):
    """Парсинг vless ссылки"""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    match = re.match(r'vless://([^@]+)@([^:]+):(\d+)\?(.*)#(.+)', line)
    if match:
        uuid, address, port, params, name = match.groups()
        return {
            "name": name[:50],  # Ограничиваем длину имени
            "uuid": uuid,
            "address": address,
            "port": int(port),
            "params": params
        }
    return None

def get_servers_from_pool():
    """Чтение серверов из pool.txt"""
    servers = []
    with open('/opt/blayvpn/pool.txt', 'r', encoding='utf-8') as f:
        for line in f:
            server = parse_vless_link(line)
            if server:
                servers.append(server)
    return servers

def get_existing_nodes():
    """Получение существующих нод из Marzban"""
    response = requests.get(f"{MARZBAN_URL}/nodes", headers=HEADERS)
    data = response.json()
    # Обработка разных форматов ответа
    if isinstance(data, dict):
        return data.get("response", [])
    elif isinstance(data, list):
        return data
    return []

def add_node_to_marzban(server):
    """Добавление ноды в Marzban"""
    node_data = {
        "name": server["name"],
        "address": server["address"],
        "port": server["port"]
    }
    try:
        response = requests.post(f"{MARZBAN_URL}/node", headers=HEADERS, json=node_data)
        if response.status_code == 200:
            print(f"    ✅ Успешно")
            return True
        else:
            print(f"    ❌ Ошибка: {response.status_code} - {response.text[:100]}")
            return False
    except Exception as e:
        print(f"    ❌ Ошибка: {e}")
        return False

def main():
    print("Загрузка серверов из pool.txt...")
    servers = get_servers_from_pool()
    print(f"Найдено {len(servers)} серверов")
    
    print("\nПолучение существующих нод из Marzban...")
    existing = get_existing_nodes()
    print(f"Существующих нод: {len(existing)}")
    
    existing_addresses = [node.get("address") for node in existing]
    
    print("\nДобавление новых серверов...")
    added = 0
    for server in servers:
        if server["address"] not in existing_addresses:
            print(f"  Добавление: {server['name'][:40]}... ({server['address']})")
            if add_node_to_marzban(server):
                added += 1
        else:
            print(f"  Пропуск (уже есть): {server['name'][:40]}...")
    
    print(f"\n✅ Добавлено {added} новых серверов")
    print(f"📊 Всего серверов в Marzban: {len(existing) + added}")

if __name__ == "__main__":
    main()
