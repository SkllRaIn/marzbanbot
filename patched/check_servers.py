#!/usr/bin/env python3
import socket
import ssl
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

POOL_FILE = "/opt/blayvpn/pool.txt"

def check_vless_server(server):
    """Проверка VLESS сервера на доступность"""
    try:
        # Извлекаем адрес и порт
        match = re.search(r'@([^:]+):(\d+)', server)
        if match:
            host, port = match.groups()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            return result == 0
    except:
        pass
    return False

def check_http_server(server):
    """Проверка HTTP/HTTPS сервера"""
    try:
        match = re.search(r'@([^:]+):(\d+)', server)
        if match:
            host, port = match.groups()
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3)
            result = sock.connect_ex((host, int(port)))
            sock.close()
            return result == 0
    except:
        pass
    return False

def check_server(server):
    """Проверка сервера"""
    if 'vless://' in server:
        return check_vless_server(server)
    return check_http_server(server)

def main():
    print("Загрузка серверов из pool.txt...")
    with open(POOL_FILE, 'r') as f:
        servers = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    
    print(f"Всего серверов: {len(servers)}")
    print("Проверка доступности (таймаут 3 сек)...")
    
    working = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(check_server, s): s for s in servers}
        for i, future in enumerate(as_completed(futures), 1):
            server = futures[future]
            if future.result():
                working.append(server)
                print(f"✅ [{i}/{len(servers)}] Работает")
            else:
                print(f"❌ [{i}/{len(servers)}] Не работает")
    
    print(f"\nРабочих серверов: {len(working)} из {len(servers)}")
    
    # Сохраняем только рабочие
    with open(POOL_FILE, 'w') as f:
        f.write("# Рабочие сервера после проверки\n")
        f.write(f"# Проверено: {time.ctime()}\n")
        f.write(f"# Рабочих: {len(working)}\n\n")
        for server in working:
            f.write(server + "\n")
    
    print("✅ pool.txt обновлен - оставлены только рабочие сервера")

if __name__ == "__main__":
    main()
