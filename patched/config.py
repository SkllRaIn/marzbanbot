from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    BOT_TOKEN_USER: str
    BOT_TOKEN_ADMIN: str
    ADMIN_TG_IDS: str

    YOOKASSA_SHOP_ID: str
    YOOKASSA_SECRET_KEY: str
    WEBHOOK_SECRET: str

    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379/0"

    REQUIRED_CHANNEL_ID: int          # ИСПРАВЛЕНО: было объявлено дважды
    REQUIRED_CHANNEL: str = "@vpnBlay"

    SERVER_DOMAIN: str                 # Без https://, пример: panel.komissarovka.ru
    WEBHOOK_PATH: str = "/webhook/blayvpn"
    WEBHOOK_PORT: int = 8080

    MARZBAN_API_URL: str = "https://panel.komissarovka.ru"
    MARZBAN_USERNAME: str = "botadmin"
    MARZBAN_PASSWORD: str = "admin123"

    class Config:
        env_file = ".env"
        extra = "ignore"

    @property
    def admin_ids(self) -> List[int]:
        return [int(x.strip()) for x in self.ADMIN_TG_IDS.split(",") if x.strip()]

    @property
    def webhook_url(self) -> str:
        # ИСПРАВЛЕНО: убираем дублирование https:// если оно есть в SERVER_DOMAIN
        domain = self.SERVER_DOMAIN.replace("https://", "").replace("http://", "").rstrip("/")
        return f"https://{domain}{self.WEBHOOK_PATH}"


settings = Settings()
