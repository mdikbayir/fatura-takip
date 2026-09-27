#!/bin/bash

set -euo pipefail

INSTALL_DIR="${FATURA_TAKIP_DIR:-/opt/fatura-takip}"
SOURCE="${INSTALL_DIR}/pdfs"
DEST="${INSTALL_DIR}/backups/documents"

echo "=== FATURA BELGE BACKUP ==="
echo "Tarih  : $(date '+%d.%m.%Y %H:%M:%S')"
echo "Kaynak : $SOURCE"
echo "Hedef  : $DEST"

if [ ! -d "$SOURCE" ]; then
    echo "HATA: Kaynak klasor bulunamadi: $SOURCE"
    exit 1
fi

mkdir -p "$DEST"

echo
echo "1/3 Belgeler artimli kopyalaniyor..."

cp -a -n "$SOURCE"/. "$DEST"/

echo "OK"

echo
echo "2/3 Dosya sayilari kontrol ediliyor..."

SOURCE_COUNT="$(
    find "$SOURCE" -type f | wc -l
)"

DEST_COUNT="$(
    find "$DEST" -type f | wc -l
)"

echo "Kaynak dosya : $SOURCE_COUNT"
echo "Yedek dosya  : $DEST_COUNT"

if [ "$DEST_COUNT" -lt "$SOURCE_COUNT" ]; then
    echo "HATA: Yedekte kaynak klasorden daha az dosya var."
    exit 1
fi

echo "OK"

echo
echo "3/3 Boyut kontrolu..."

SOURCE_SIZE="$(du -sh "$SOURCE" | cut -f1)"
DEST_SIZE="$(du -sh "$DEST" | cut -f1)"

echo "Kaynak : $SOURCE_SIZE"
echo "Yedek  : $DEST_SIZE"

echo
echo "BELGE YEDEGI BASARILI"

echo
echo "Yedeklenen dosyalar:"
find "$DEST" \
    -type f \
    -printf '%P\n' \
    | sort
