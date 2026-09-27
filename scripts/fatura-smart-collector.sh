#!/bin/bash

set -euo pipefail

PROVIDER="${1:-}"

case "$PROVIDER" in
    ck)
        LABEL="CK Bogazici"
        SCRIPT="/app/collector.py"
        ;;
    iski)
        LABEL="ISKI"
        SCRIPT="/app/iski.py"
        ;;
    igdas)
        LABEL="IGDAS"
        SCRIPT="/app/igdas.py"
        ;;
    *)
        echo "HATA: Gecersiz provider: $PROVIDER"
        exit 2
        ;;
esac

echo "========================================"
echo "=== ${LABEL} AKILLI FATURA KONTROLU ==="
echo "========================================"
echo "Tarih: $(date '+%d.%m.%Y %H:%M:%S')"

if /usr/local/sbin/fatura-period-check.sh "$PROVIDER"; then
    echo
    echo "${LABEL}: Bu aya ait fatura zaten mevcut."
    echo "Collector calistirilmadi."
    exit 0
fi

echo
echo "${LABEL}: Bu aya ait fatura bulunamadi."
echo "Collector baslatiliyor..."

INSTALL_DIR="${FATURA_TAKIP_DIR:-/opt/fatura-takip}"
cd "$INSTALL_DIR"

if [ "$PROVIDER" = "igdas" ]; then
    /usr/bin/docker compose run \
        --rm \
        -e IGDAS_START=1 \
        -e IGDAS_LIMIT=1 \
        -e IGDAS_WRITE_DB=1 \
        --entrypoint python \
        collector \
        "$SCRIPT"
else
    /usr/bin/docker compose run \
        --rm \
        --entrypoint python \
        collector \
        "$SCRIPT"
fi

RESULT=$?

if [ "$RESULT" -eq 0 ]; then
    echo
    echo "${LABEL}: Collector basariyla tamamlandi."
else
    echo
    echo "${LABEL}: Collector HATA ile sonlandi. Kod: ${RESULT}"
fi

exit "$RESULT"
