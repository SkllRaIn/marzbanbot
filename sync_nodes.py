#!/usr/bin/env python3
"""
Автоматическая синхронизация серверов из pool.txt с Marzban
Запускать по расписанию (каждый день)
"""
import re
import requests
import json
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('/var/log/blayvpn_sync.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

MARZBAN_URL = "https://panel.komissarovka.ru/api"
TOKEN = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJib3RhZG1pbiIsImFjY2VzcyI6InN1ZG8iLCJpYXQiOjE3Nzc1NDk3MTEsImV4cCI6MTc3NzYzNjExMX0.gQcNmLhaVdU81iKNhIvH9RhmINY3Hrx0uROx7WnsQzM"

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Content-Type": "application/json"
}

# Сопоставление стран
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

def parse_vless_link(line):
    """Парсинг vless ссылки из pool.txt"""
    line = line.strip()
    if not line or line.startswith('#'):
        return None
    
    match = re.match(r'vless://([^@]+)@([^:]+):(\d+)\?(.*)#(.+)', line)
    if match:
        uuid, address, port, params, name = match.groups()
        return {
            "uuid": uuid,
            "address": address,
            "port": int(port),
            "name": name,
            "params": params,
            "full_line": line
        }
    return None

def get_marzban_nodes():
    """Получение всех нод из Marzban"""
    try:
        response = requests.get(f"{MARZBAN_URL}/nodes", headers=HEADERS, timeout=30)
        data = response.json()
        if isinstance(data, dict):
            return data.get("response", [])
        return data
    except Exception as e:
        logger.error(f"Ошибка получения нод из Marzban: {e}")
        return []

def add_node_to_marzban(server):
    """Добавление новой ноды в Marzban"""
    try:
        node_data = {
            "name": f"🌍 {server['address']}",
            "address": server["address"],
            "port": server["port"]
        }
        response = requests.post(f"{MARZBAN_URL}/node", headers=HEADERS, json=node_data, timeout=30)
        if response.status_code == 200:
            logger.info(f"  ✅ Добавлен: {server['address']}")
            return True
        else:
            logger.warning(f"  ❌ Ошибка добавления {server['address']}: {response.status_code}")
            return False
    except Exception as e:
        logger.error(f"  ❌ Ошибка: {e}")
        return False

def cleanup_pool_file(servers_to_keep):
    """Перезапись pool.txt только с рабочими серверами"""
    try:
        with open('/opt/blayvpn/pool.txt', 'w', encoding='utf-8') as f:
            f.write("# Актуальные сервера после синхронизации\n")
            f.write(f"# Обновлено: {datetime.now()}\n\n")
            for server in servers_to_keep:
                f.write(server["full_line"] + "\n")
        logger.info(f"✅ pool.txt очищен - оставлено {len(servers_to_keep)} серверов")
    except Exception as e:
        logger.error(f"Ошибка записи pool.txt: {e}")

def sync():
    """Основная функция синхронизации"""
    logger.info("=" * 50)
    logger.info(f"Начало синхронизации - {datetime.now()}")
    
    # Загружаем сервера из pool.txt
    pool_servers = []
    try:
        with open('/opt/blayvpn/pool.txt', 'r', encoding='utf-8') as f:
            for line in f:
                server = parse_vless_link(line)
                if server:
                    pool_servers.append(server)
        logger.info(f"Загружено {len(pool_servers)} серверов из pool.txt")
    except Exception as e:
        logger.error(f"Ошибка чтения pool.txt: {e}")
        return
    
    if not pool_servers:
        logger.error("Нет серверов в pool.txt")
        return
    
    # Получаем текущие ноды из Marzban
    marzban_nodes = get_marzban_nodes()
    logger.info(f"В Marzban: {len(marzban_nodes)} нод")
    
    # Создаем список адресов в Marzban
    marzban_addresses = {node.get("address") for node in marzban_nodes if node.get("address")}
    
    # Фильтруем сервера: оставляем только те, что уже есть в Marzban
    servers_to_keep = []
    servers_to_add = []
    
    for server in pool_servers:
        if server["address"] in marzban_addresses:
            servers_to_keep.append(server)
        else:
            servers_to_add.append(server)
    
    logger.info(f"Уже в Marzban: {len(servers_to_keep)}")
    logger.info(f"Нужно добавить: {len(servers_to_add)}")
    
    # Добавляем новые сервера
    added = 0
    for server in servers_to_add:
        logger.info(f"Добавление новой ноды: {server['address']}")
        if add_node_to_marzban(server):
            added += 1
            servers_to_keep.append(server)
        else:
            logger.warning(f"  Сервер {server['address']} не будет добавлен в pool.txt")
    
    # Если были добавлены новые, обновляем pool.txt
    if added > 0:
        cleanup_pool_file(servers_to_keep)
    
    logger.info(f"✅ Синхронизация завершена: добавлено {added}")
    logger.info("=" * 50)

if __name__ == "__main__":
    sync()
