#!/bin/bash

set -euo pipefail

PROVIDER="${1:-}"
INSTALL_DIR="${FATURA_TAKIP_DIR:-/opt/fatura-takip}"
DB="${INSTALL_DIR}/data/faturalar.db"

YEAR="$(date '+%Y')"
MONTH="$(date '+%m')"

case "$PROVIDER" in

    ck)
        DB_PROVIDER="ck-bogazici"
        PERIOD="${MONTH}-${YEAR}"
        ;;

    iski)
        DB_PROVIDER="iski"
        PERIOD="${YEAR}${MONTH}"
        ;;

    igdas)
        DB_PROVIDER="igdas"
        PERIOD="${MONTH}-${YEAR}"
        ;;

    *)
        echo "Kullanim:"
        echo "  $0 ck"
        echo "  $0 iski"
        echo "  $0 igdas"
        exit 2
        ;;
esac

COUNT="$(
    sqlite3 "$DB" \
        "SELECT COUNT(*)
         FROM invoices
         WHERE provider='${DB_PROVIDER}'
           AND period='${PERIOD}';"
)"

echo "Provider : ${DB_PROVIDER}"
echo "Donem    : ${PERIOD}"
echo "Kayit    : ${COUNT}"

if [ "$COUNT" -gt 0 ]; then
    echo "SONUC    : FATURA MEVCUT"
    exit 0
else
    echo "SONUC    : FATURA YOK"
    exit 1
fi
