#!/bin/bash
set -e
APP_DIR="/opt/blayvpn"
PATCH_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== BlayVPN Patch v4 ==="

# Бэкап
BACKUP_DIR="$APP_DIR/backup_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
for f in subscription_server.py core/scheduler.py core/marzban.py core/pool_manager.py bots/admin_bot/handlers/users.py; do
    cp "$APP_DIR/$f" "$BACKUP_DIR/" 2>/dev/null && echo "  backed up $f" || true
done

# Патч файлов
cp "$PATCH_DIR/subscription_server.py"              "$APP_DIR/subscription_server.py"
cp "$PATCH_DIR/core/scheduler.py"                   "$APP_DIR/core/scheduler.py"
cp "$PATCH_DIR/core/marzban.py"                     "$APP_DIR/core/marzban.py"
cp "$PATCH_DIR/core/pool_manager.py"                "$APP_DIR/core/pool_manager.py"
cp "$PATCH_DIR/bots/admin_bot/handlers/users.py"    "$APP_DIR/bots/admin_bot/handlers/users.py"
echo "✅ Файлы скопированы"

# Исправляем .env — убираем дублирование
awk '!seen[$0]++' "$APP_DIR/.env" > /tmp/.env_fixed && mv /tmp/.env_fixed "$APP_DIR/.env"
echo "✅ .env дедуплицирован"

# Перезапуск
systemctl restart blayvpn
sleep 3
echo ""
echo "=== Статус ==="
systemctl status blayvpn --no-pager | head -15
echo ""
echo "✅ Готово! Проверьте: journalctl -u blayvpn -f"
