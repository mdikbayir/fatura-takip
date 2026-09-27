#!/bin/bash

set -euo pipefail

INSTALL_DIR="${FATURA_TAKIP_DIR:-/opt/fatura-takip}"
DB="${INSTALL_DIR}/data/faturalar.db"
BACKUP_DIR="${INSTALL_DIR}/backups"
DATE="$(date '+%Y-%m-%d_%H-%M-%S')"

BACKUP="${BACKUP_DIR}/faturalar-${DATE}.db"
TMP="${BACKUP}.tmp"

echo "=== FATURA BACKUP ==="
echo "Tarih : $(date '+%d.%m.%Y %H:%M:%S')"
echo "Kaynak: ${DB}"

if [ ! -f "$DB" ]; then
    echo "HATA: Veritabani bulunamadi: $DB"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

echo
echo "1/4 Veritabani kontrol ediliyor..."

CHECK="$(sqlite3 "$DB" 'PRAGMA integrity_check;')"

if [ "$CHECK" != "ok" ]; then
    echo "HATA: Veritabani integrity_check basarisiz:"
    echo "$CHECK"
    exit 1
fi

echo "OK"

echo
echo "2/4 SQLite online backup aliniyor..."

sqlite3 "$DB" ".backup '$TMP'"

echo
echo "3/4 Yedek kontrol ediliyor..."

BACKUP_CHECK="$(sqlite3 "$TMP" 'PRAGMA integrity_check;')"

if [ "$BACKUP_CHECK" != "ok" ]; then
    echo "HATA: Olusturulan yedek bozuk:"
    echo "$BACKUP_CHECK"
    rm -f "$TMP"
    exit 1
fi

mv "$TMP" "$BACKUP"

echo "OK"

echo
echo "4/4 Eski yedekler temizleniyor..."

find "$BACKUP_DIR" \
    -maxdepth 1 \
    -type f \
    -name 'faturalar-*.db' \
    -mtime +30 \
    -delete

echo
echo "YEDEK BASARILI"
echo "Dosya: $BACKUP"
echo "Boyut: $(du -h "$BACKUP" | cut -f1)"

echo
echo "Mevcut yedekler:"
ls -lh "$BACKUP_DIR"/faturalar-*.db 2>/dev/null || true
