#!/bin/bash

set -euo pipefail

TYPE="${1:-unknown}"

INSTALL_DIR="${FATURA_TAKIP_DIR:-/opt/fatura-takip}"
cd "$INSTALL_DIR"

TOKEN="$(
    docker compose config |
    sed -n 's/^[[:space:]]*TELEGRAM_BOT_TOKEN:[[:space:]]*//p' |
    head -n1 |
    sed 's/^"//;s/"$//'
)"

CHAT_ID="$(
    docker compose config |
    sed -n 's/^[[:space:]]*TELEGRAM_CHAT_ID:[[:space:]]*//p' |
    head -n1 |
    sed 's/^"//;s/"$//'
)"

if [ -z "$TOKEN" ] || [ -z "$CHAT_ID" ]; then
    echo "HATA: Telegram ayarlari bulunamadi."
    exit 1
fi

case "$TYPE" in

    collector)
        MESSAGE="🔴 Fatura Collector Hatası

⚠️ Elektrik / su fatura kontrolü başarısız oldu.
🖥️ Sunucu: $(hostname)
🕒 Tarih: $(date '+%d.%m.%Y %H:%M:%S')

Collector loglarını kontrol et:
journalctl -u fatura-collector.service"
        ;;

    backup)
        MESSAGE="🔴 Fatura Yedekleme Hatası

⚠️ Fatura veritabanı veya belge yedeklemesi başarısız oldu.
🖥️ Sunucu: $(hostname)
🕒 Tarih: $(date '+%d.%m.%Y %H:%M:%S')

Backup loglarını kontrol et:
journalctl -u fatura-backup.service"
        ;;

    test)
        MESSAGE="🧪 Fatura Takip Telegram Testi

✅ Telegram hata bildirim sistemi çalışıyor.
🖥️ Sunucu: $(hostname)
🕒 Tarih: $(date '+%d.%m.%Y %H:%M:%S')"
        ;;

    *)
        MESSAGE="⚠️ Fatura Takip Uyarısı

Bilinmeyen alarm türü: $TYPE
🖥️ Sunucu: $(hostname)
🕒 Tarih: $(date '+%d.%m.%Y %H:%M:%S')"
        ;;
esac

python3 - "$TOKEN" "$CHAT_ID" "$MESSAGE" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

token = sys.argv[1]
chat_id = sys.argv[2]
message = sys.argv[3]

url = f"https://api.telegram.org/bot{token}/sendMessage"

data = urllib.parse.urlencode({
    "chat_id": chat_id,
    "text": message,
}).encode()

request = urllib.request.Request(
    url,
    data=data,
    method="POST",
)

with urllib.request.urlopen(request, timeout=20) as response:
    result = json.loads(response.read().decode())

if not result.get("ok"):
    raise SystemExit("Telegram API mesaji kabul etmedi.")

print("Telegram bildirimi gonderildi.")
PY
