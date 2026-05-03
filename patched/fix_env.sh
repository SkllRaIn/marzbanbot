#!/bin/bash
# Исправляем .env — убираем дублирование MARZBAN_USERNAME/PASSWORD
ENV_FILE="/opt/blayvpn/.env"

# Бэкап
cp "$ENV_FILE" "${ENV_FILE}.bak_$(date +%Y%m%d_%H%M%S)"

# Убираем дублированные строки (оставляем только уникальные)
awk '!seen[$0]++' "$ENV_FILE" > "${ENV_FILE}.tmp" && mv "${ENV_FILE}.tmp" "$ENV_FILE"

echo "✅ .env дедуплицирован:"
grep MARZBAN "$ENV_FILE"
