import random
import logging
from typing import List, Dict, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

POOL_FILE = "/opt/blayvpn/pool.txt"
FOREIGN_COUNT = 5
RUSSIAN_COUNT = 5


class VLESSConfig:
    """Генератор VLESS конфигураций из пула"""
    
    @staticmethod
    def load_all_links() -> List[str]:
        """Загрузка всех ссылок из файла"""
        links = []
        try:
            with open(POOL_FILE, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        links.append(line)
            logger.info(f"Loaded {len(links)} servers from pool")
        except Exception as e:
            logger.error(f"Failed to load servers: {e}")
        return links
    
    @staticmethod
    def load_servers() -> List[Dict]:
        """Загрузка серверов с разделением на иностранные и русские"""
        all_links = VLESSConfig.load_all_links()
        
        foreign = []
        russian = []
        
        # Эмодзи стран для определения русских серверов
        russian_flags = ['🇷🇺', 'Russia', 'Санкт-Петербург', 'Moscow', 'St Petersburg']
        
        for link in all_links:
            # Определяем по флагам и названиям
            is_russian = any(flag in link for flag in russian_flags)
            
            if is_russian:
                russian.append(link)
            else:
                foreign.append(link)
        
        logger.info(f"Loaded {len(foreign)} foreign servers, {len(russian)} russian servers")
        
        return {
            "foreign": foreign,
            "russian": russian
        }
    
    @staticmethod
    def generate_subscription(username: str) -> str:
        """Генерация подписки: 5 иностранных + 5 русских серверов"""
        servers = VLESSConfig.load_servers()
        
        foreign_servers = servers.get("foreign", [])
        russian_servers = servers.get("russian", [])
        
        # Выбираем случайные серверы
        selected_foreign = random.sample(foreign_servers, min(FOREIGN_COUNT, len(foreign_servers)))
        selected_russian = random.sample(russian_servers, min(RUSSIAN_COUNT, len(russian_servers)))
        
        all_selected = selected_foreign + selected_russian
        
        # Перемешиваем для случайного порядка
        random.shuffle(all_selected)
        
        header = (
            f"# Subscription for {username}\n"
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"# Foreign servers: {len(selected_foreign)}\n"
            f"# Russian servers: {len(selected_russian)}\n"
            f"# Total: {len(all_selected)} servers\n\n"
        )
        
        return header + "\n".join(all_selected)
    
    @staticmethod
    def get_stats() -> Dict:
        """Получение статистики серверов"""
        servers = VLESSConfig.load_servers()
        return {
            "foreign": len(servers.get("foreign", [])),
            "russian": len(servers.get("russian", [])),
            "total": len(servers.get("foreign", [])) + len(servers.get("russian", []))
        }


server_pool = VLESSConfig()
