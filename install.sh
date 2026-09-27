#!/bin/bash

set -euo pipefail

# ============================================================
# FATURA TAKIP PUBLIC INSTALLER
# ============================================================

DEFAULT_INSTALL_DIR="/opt/fatura-takip"
INSTALL_DIR="${FATURA_TAKIP_DIR:-$DEFAULT_INSTALL_DIR}"
SCRIPT_DIR="/usr/local/sbin"
SYSTEMD_DIR="/etc/systemd/system"

SOURCE_DIR="$(
    cd "$(dirname "${BASH_SOURCE[0]}")"
    pwd
)"


# ============================================================
# READ-ONLY CHECK MODE
# ============================================================

run_check_mode() {

    echo "============================================================"
    echo "=== FATURA TAKIP PUBLIC PAKET KONTROLU ==="
    echo "============================================================"
    echo
    echo "Kaynak: $SOURCE_DIR"
    echo
    echo "Bu mod sistemde degisiklik yapmaz."
    echo

    ERRORS=0

    ok() {
        echo "[OK] $*"
    }

    fail() {
        echo "[HATA] $*"
        ERRORS=$((ERRORS + 1))
    }

    # --------------------------------------------------------
    # 1. PAKET DOSYALARI
    # --------------------------------------------------------

    echo "=== 1/10 PAKET YAPISI ==="

    CHECK_FILES=(
        ".env.example"
        ".gitignore"
        "docker-compose.yml"
        "Dockerfile.collector"
        "database/init.sql"
        "app/collector.py"
        "app/iski.py"
        "app/requirements.txt"
        "igdas.py"
        "dashboard/Dockerfile"
        "dashboard/app.py"
        "dashboard/requirements.txt"
        "scripts/fatura-smart-collector.sh"
        "scripts/fatura-period-check.sh"
        "scripts/fatura-backup.sh"
        "scripts/fatura-document-backup.sh"
        "scripts/fatura-telegram-alert.sh"
        "systemd/fatura-alert@.service"
        "systemd/fatura-backup.service"
        "systemd/fatura-backup.timer"
        "systemd/fatura-ck.service"
        "systemd/fatura-ck.timer"
        "systemd/fatura-iski.service"
        "systemd/fatura-iski.timer"
        "systemd/fatura-igdas.service"
        "systemd/fatura-igdas.timer"
        "install.sh"
    )

    for file in "${CHECK_FILES[@]}"; do
        if [ -f "$SOURCE_DIR/$file" ]; then
            :
        else
            fail "Eksik dosya: $file"
        fi
    done

    if [ "$ERRORS" -eq 0 ]; then
        ok "Paket dosyalari eksiksiz"
    fi

    # --------------------------------------------------------
    # 2. HASSAS DOSYALAR
    # --------------------------------------------------------

    echo
    echo "=== 2/10 HASSAS DOSYA KONTROLU ==="

    SENSITIVE_FOUND=0

    if [ -f "$SOURCE_DIR/.env" ]; then
        fail "Public pakette .env bulundu"
        SENSITIVE_FOUND=1
    fi

    if find "$SOURCE_DIR/data" \
        -type f \
        ! -name '.gitkeep' \
        -print -quit 2>/dev/null |
        grep -q .
    then
        fail "data/ altinda kullanici verisi bulundu"
        SENSITIVE_FOUND=1
    fi

    if find "$SOURCE_DIR/pdfs" \
        -type f \
        ! -name '.gitkeep' \
        -print -quit 2>/dev/null |
        grep -q .
    then
        fail "pdfs/ altinda belge bulundu"
        SENSITIVE_FOUND=1
    fi

    if find "$SOURCE_DIR/auth/chromium" \
        -type f \
        ! -name '.gitkeep' \
        -print -quit 2>/dev/null |
        grep -q .
    then
        fail "auth/chromium altinda profil verisi bulundu"
        SENSITIVE_FOUND=1
    fi

    if [ "$SENSITIVE_FOUND" -eq 0 ]; then
        ok "Hassas runtime dosyasi bulunmadi"
    fi

    # --------------------------------------------------------
    # 3. BAGIMLILIKLAR
    # --------------------------------------------------------

    echo
    echo "=== 3/10 BAGIMLILIKLAR ==="

    COMMANDS=(
        docker
        sqlite3
        curl
        python3
        sed
        grep
        find
    )

    for cmd in "${COMMANDS[@]}"; do
        if command -v "$cmd" >/dev/null 2>&1; then
            ok "$cmd"
        else
            fail "Komut bulunamadi: $cmd"
        fi
    done

    if command -v docker >/dev/null 2>&1; then
        if docker compose version >/dev/null 2>&1; then
            ok "Docker Compose plugin"
        else
            fail "Docker Compose plugin bulunamadi"
        fi
    fi

    # --------------------------------------------------------
    # 4. SHELL SYNTAX
    # --------------------------------------------------------

    echo
    echo "=== 4/10 SHELL SYNTAX ==="

    SHELL_OK=1

    for file in \
        "$SOURCE_DIR/install.sh" \
        "$SOURCE_DIR"/scripts/*.sh
    do
        if bash -n "$file"; then
            :
        else
            fail "Shell syntax: ${file#$SOURCE_DIR/}"
            SHELL_OK=0
        fi
    done

    if [ "$SHELL_OK" -eq 1 ]; then
        ok "Tum shell scriptleri"
    fi

    # --------------------------------------------------------
    # 5. PYTHON SYNTAX
    # --------------------------------------------------------

    echo
    echo "=== 5/10 PYTHON SYNTAX ==="

    PYTHON_OK=1

    if command -v python3 >/dev/null 2>&1; then

        PYTHON_FILES=(
            "$SOURCE_DIR/app/collector.py"
            "$SOURCE_DIR/app/iski.py"
            "$SOURCE_DIR/igdas.py"
            "$SOURCE_DIR/dashboard/app.py"
        )

        for file in "${PYTHON_FILES[@]}"; do

            if PYTHONDONTWRITEBYTECODE=1 \
                python3 -m py_compile "$file"
            then
                :
            else
                fail "Python syntax: ${file#$SOURCE_DIR/}"
                PYTHON_OK=0
            fi

        done

        # py_compile yine cache olusturabilirse temizle.
        find "$SOURCE_DIR" \
            -type d \
            -name '__pycache__' \
            -prune \
            -exec rm -rf {} + 2>/dev/null || true

        if [ "$PYTHON_OK" -eq 1 ]; then
            ok "Tum Python dosyalari"
        fi

    else
        fail "Python syntax kontrolu yapilamadi"
    fi

    # --------------------------------------------------------
    # 6. DATABASE INIT
    # --------------------------------------------------------

    echo
    echo "=== 6/10 DATABASE SEMA ==="

    if command -v sqlite3 >/dev/null 2>&1; then

        TEST_DB="$(
            mktemp /tmp/fatura-public-check.XXXXXX.db
        )"

        trap 'rm -f "$TEST_DB" "$TEST_ENV" "$COMPOSE_OUT"' RETURN

        if sqlite3 "$TEST_DB" \
            < "$SOURCE_DIR/database/init.sql"
        then
            ok "init.sql calisti"
        else
            fail "init.sql calistirilamadi"
        fi

        TABLE_COUNT="$(
            sqlite3 "$TEST_DB" \
                "SELECT COUNT(*) FROM sqlite_master
                 WHERE type='table'
                   AND name IN (
                       'invoices',
                       'notifications',
                       'system_alerts'
                   );" 2>/dev/null || echo 0
        )"

        INVOICE_COLUMNS="$(
            sqlite3 "$TEST_DB" \
                "SELECT COUNT(*)
                 FROM pragma_table_info('invoices');" \
                 2>/dev/null || echo 0
        )"

        NOTIFICATION_COLUMNS="$(
            sqlite3 "$TEST_DB" \
                "SELECT COUNT(*)
                 FROM pragma_table_info('notifications');" \
                 2>/dev/null || echo 0
        )"

        ALERT_COLUMNS="$(
            sqlite3 "$TEST_DB" \
                "SELECT COUNT(*)
                 FROM pragma_table_info('system_alerts');" \
                 2>/dev/null || echo 0
        )"

        [ "$TABLE_COUNT" -eq 3 ] \
            && ok "3 uygulama tablosu" \
            || fail "Tablo sayisi: $TABLE_COUNT / beklenen 3"

        [ "$INVOICE_COLUMNS" -eq 41 ] \
            && ok "invoices: 41 kolon" \
            || fail "invoices kolon: $INVOICE_COLUMNS / beklenen 41"

        [ "$NOTIFICATION_COLUMNS" -eq 5 ] \
            && ok "notifications: 5 kolon" \
            || fail "notifications kolon: $NOTIFICATION_COLUMNS / beklenen 5"

        [ "$ALERT_COLUMNS" -eq 5 ] \
            && ok "system_alerts: 5 kolon" \
            || fail "system_alerts kolon: $ALERT_COLUMNS / beklenen 5"

        DB_CHECK="$(
            sqlite3 "$TEST_DB" \
                'PRAGMA integrity_check;' \
                2>/dev/null || true
        )"

        if [ "$DB_CHECK" = "ok" ]; then
            ok "SQLite integrity_check"
        else
            fail "SQLite integrity_check"
        fi

        rm -f "$TEST_DB"

    else
        fail "Database testi yapilamadi"
    fi

    # --------------------------------------------------------
    # 7. SYSTEMD TEMPLATE
    # --------------------------------------------------------

    echo
    echo "=== 7/10 SYSTEMD TEMPLATE ==="

    SYSTEMD_OK=1

    for file in "$SOURCE_DIR"/systemd/*.service; do

        if grep -q '/opt/fatura-takip' "$file"; then
            fail "Sabit kurulum path'i: ${file#$SOURCE_DIR/}"
            SYSTEMD_OK=0
        fi

    done

    for file in \
        "$SOURCE_DIR/systemd/fatura-ck.service" \
        "$SOURCE_DIR/systemd/fatura-iski.service" \
        "$SOURCE_DIR/systemd/fatura-igdas.service"
    do
        if grep -q '@INSTALL_DIR@' "$file" &&
           grep -q '@SCRIPT_DIR@' "$file"
        then
            :
        else
            fail "Placeholder eksik: ${file#$SOURCE_DIR/}"
            SYSTEMD_OK=0
        fi
    done

    if [ "$SYSTEMD_OK" -eq 1 ]; then
        ok "Systemd template'leri portable"
    fi

    # --------------------------------------------------------
    # 8. COMPOSE CONFIG
    # --------------------------------------------------------

    echo
    echo "=== 8/10 DOCKER COMPOSE ==="

CHECK_ENV_CREATED=0

cleanup_check_env() {
    if [ "$CHECK_ENV_CREATED" -eq 1 ]; then
        rm -f "$SOURCE_DIR/.env"
    fi
}

# Compose dosyasinda collector icin:
#
#   env_file:
#     - .env
#
# kullanildigi icin docker compose config proje
# dizininde gercek bir .env dosyasi bekler.
#
# Public pakette .env bulunmamasi normaldir.
# Kontrol amaciyla yalnizca gecici bir .env olusturulur.
#
# Eger kullanicinin gercek .env dosyasi zaten varsa
# ona kesinlikle dokunulmaz.

if [ ! -e "$SOURCE_DIR/.env" ]; then
    cp "$SOURCE_DIR/.env.example" "$SOURCE_DIR/.env"
    CHECK_ENV_CREATED=1
fi

COMPOSE_OUT="$(mktemp)"

set +e

(
    cd "$SOURCE_DIR"
    docker compose config
) >"$COMPOSE_OUT" 2>&1

COMPOSE_RESULT=$?

set -e

cleanup_check_env

if [ "$COMPOSE_RESULT" -ne 0 ]; then
    echo "[HATA] docker compose config basarisiz:"
    cat "$COMPOSE_OUT"
    rm -f "$COMPOSE_OUT"
    return 1
fi

rm -f "$COMPOSE_OUT"

echo "[OK] docker compose config"
echo

echo "=== 9/10 ESKI REFERANS KONTROLU ==="

    OLD_REFS="$(
        grep -RniE \
            --exclude-dir=backups \
            --exclude='install.sh' \
            'fatura-collector:2\.[01]|fatura-dashboard:2\.0|docker-compose\.igdas' \
            "$SOURCE_DIR" \
            2>/dev/null || true
    )"

    if [ -z "$OLD_REFS" ]; then
        ok "Eski image/override referansi yok"
    else
        fail "Eski image/override referansi bulundu"
        echo "$OLD_REFS"
    fi

    # --------------------------------------------------------
    # 10. SONUC
    # --------------------------------------------------------

    echo
    echo "=== 10/10 SONUC ==="
    echo

    if [ "$ERRORS" -eq 0 ]; then

        echo "============================================================"
        echo "=== PUBLIC PAKET KONTROLU BASARILI ==="
        echo "============================================================"
        echo
        echo "Toplam hata: 0"
        echo
        echo "Bu kontrolde:"
        echo " - Docker image build edilmedi."
        echo " - Container baslatilmadi."
        echo " - Systemd degistirilmedi."
        echo " - /usr/local/sbin degistirilmedi."
        echo " - /opt/fatura-takip degistirilmedi."
        echo
        exit 0

    else

        echo "============================================================"
        echo "=== PUBLIC PAKET KONTROLU BASARISIZ ==="
        echo "============================================================"
        echo
        echo "Toplam hata: $ERRORS"
        echo
        exit 1

    fi
}


case "${1:-}" in

    --check)
        run_check_mode
        ;;

    --help|-h)
        echo "Kullanim:"
        echo "  sudo ./install.sh"
        echo "  ./install.sh --check"
        echo
        echo "Secenekler:"
        echo "  --check   Sistemde degisiklik yapmadan paketi kontrol eder."
        echo "  --help    Bu yardimi gosterir."
        exit 0
        ;;

    "")
        ;;

    *)
        echo "HATA: Bilinmeyen parametre: $1"
        echo "Kullanim: $0 [--check]"
        exit 2
        ;;

esac


echo "============================================================"
echo "=== FATURA TAKIP PUBLIC KURULUM ==="
echo "============================================================"
echo
echo "Kaynak       : $SOURCE_DIR"
echo "Kurulum      : $INSTALL_DIR"
echo "Script dizini: $SCRIPT_DIR"
echo

# ------------------------------------------------------------
# 1. ROOT KONTROLU
# ------------------------------------------------------------

if [ "$(id -u)" -ne 0 ]; then
    echo "HATA: Bu installer root olarak calistirilmalidir."
    echo
    echo "Ornek:"
    echo "  sudo ./install.sh"
    exit 1
fi

# ------------------------------------------------------------
# 2. GEREKLI KOMUTLAR
# ------------------------------------------------------------

echo "=== 1/10 BAGIMLILIK KONTROLU ==="

REQUIRED=(
    docker
    sqlite3
    curl
    python3
    sed
)

MISSING=()

for cmd in "${REQUIRED[@]}"; do
    if command -v "$cmd" >/dev/null 2>&1; then
        echo "OK: $cmd"
    else
        echo "EKSIK: $cmd"
        MISSING+=("$cmd")
    fi
done

if [ "${#MISSING[@]}" -gt 0 ]; then
    echo
    echo "HATA: Eksik bagimliliklar var:"
    printf ' - %s\n' "${MISSING[@]}"
    echo
    echo "Debian/Ubuntu ornegi:"
    echo "  apt update"
    echo "  apt install -y sqlite3 curl python3"
    echo
    echo "Docker Engine + Docker Compose plugin ayrica kurulu olmalidir."
    exit 1
fi

if ! docker compose version >/dev/null 2>&1; then
    echo "HATA: Docker Compose plugin bulunamadi."
    exit 1
fi

echo "OK: docker compose"

# ------------------------------------------------------------
# 3. KAYNAK PAKET KONTROLU
# ------------------------------------------------------------

echo
echo "=== 2/10 PAKET KONTROLU ==="

REQUIRED_FILES=(
    "docker-compose.yml"
    "Dockerfile.collector"
    ".env.example"
    "database/init.sql"
    "app/collector.py"
    "app/iski.py"
    "igdas.py"
    "dashboard/Dockerfile"
    "dashboard/app.py"
    "scripts/fatura-smart-collector.sh"
    "scripts/fatura-period-check.sh"
    "scripts/fatura-backup.sh"
    "scripts/fatura-document-backup.sh"
    "scripts/fatura-telegram-alert.sh"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$SOURCE_DIR/$file" ]; then
        echo "HATA: Paket dosyasi eksik: $file"
        exit 1
    fi
done

echo "Paket dosyalari: OK"

# ------------------------------------------------------------
# 4. MEVCUT KURULUM KORUMASI
# ------------------------------------------------------------

echo
echo "=== 3/10 KURULUM DIZINI ==="

if [ "$SOURCE_DIR" != "$INSTALL_DIR" ]; then

    if [ -e "$INSTALL_DIR" ]; then
        echo
        echo "HATA: Hedef dizin zaten mevcut:"
        echo "  $INSTALL_DIR"
        echo
        echo "Mevcut kurulum guvenlik nedeniyle ezilmedi."
        echo
        echo "Baska dizine kurmak icin:"
        echo "  FATURA_TAKIP_DIR=/opt/fatura-takip-test ./install.sh"
        exit 1
    fi

    mkdir -p "$INSTALL_DIR"

    cp -a "$SOURCE_DIR"/. "$INSTALL_DIR"/

    echo "Paket kopyalandi."
else
    echo "Paket zaten hedef dizinde."
fi

cd "$INSTALL_DIR"

mkdir -p \
    data \
    pdfs \
    backups \
    auth/chromium

# Public paket gelistirme yedeklerini kurulumdan temizle.
if [ -d backups ]; then
    find backups -mindepth 1 -maxdepth 1 \
        -name '*.before-*' \
        -exec rm -rf {} + 2>/dev/null || true
fi

# ------------------------------------------------------------
# 5. ENV
# ------------------------------------------------------------

echo
echo "=== 4/10 ENV DOSYASI ==="

if [ ! -f .env ]; then
    cp .env.example .env
    chmod 600 .env

    echo "Yeni .env olusturuldu."
else
    echo "Mevcut .env korundu."
fi

# ------------------------------------------------------------
# 6. DATABASE
# ------------------------------------------------------------

echo
echo "=== 5/10 DATABASE ==="

DB="$INSTALL_DIR/data/faturalar.db"

if [ ! -f "$DB" ]; then
    sqlite3 "$DB" < database/init.sql
    chmod 600 "$DB"
    echo "Yeni database olusturuldu."
else
    echo "Mevcut database korundu."
fi

CHECK="$(
    sqlite3 "$DB" 'PRAGMA integrity_check;'
)"

if [ "$CHECK" != "ok" ]; then
    echo "HATA: Database integrity_check basarisiz:"
    echo "$CHECK"
    exit 1
fi

TABLE_COUNT="$(
    sqlite3 "$DB" \
        "SELECT COUNT(*)
         FROM sqlite_master
         WHERE type='table'
           AND name IN (
               'invoices',
               'notifications',
               'system_alerts'
           );"
)"

COLUMN_COUNT="$(
    sqlite3 "$DB" \
        "SELECT COUNT(*)
         FROM pragma_table_info('invoices');"
)"

if [ "$TABLE_COUNT" -ne 3 ]; then
    echo "HATA: Beklenen 3 ana tablo bulunamadi."
    exit 1
fi

if [ "$COLUMN_COUNT" -ne 41 ]; then
    echo "HATA: invoices tablosunda 41 kolon bekleniyordu."
    echo "Bulunan: $COLUMN_COUNT"
    exit 1
fi

echo "Database integrity : OK"
echo "Ana tablo sayisi   : $TABLE_COUNT"
echo "Invoices kolon     : $COLUMN_COUNT"

# ------------------------------------------------------------
# 7. SCRIPT KURULUMU
# ------------------------------------------------------------

echo
echo "=== 6/10 SCRIPT KURULUMU ==="

SCRIPTS=(
    fatura-smart-collector.sh
    fatura-period-check.sh
    fatura-backup.sh
    fatura-document-backup.sh
    fatura-telegram-alert.sh
)

for script in "${SCRIPTS[@]}"; do

    install \
        -m 0755 \
        "$INSTALL_DIR/scripts/$script" \
        "$SCRIPT_DIR/$script"

    echo "OK: $SCRIPT_DIR/$script"
done

# Scriptlerin custom INSTALL_DIR'i bilmesini saglayan
# systemd Environment satiri daha sonra unitlere eklenecek.

# ------------------------------------------------------------
# 8. SYSTEMD UNIT KURULUMU
# ------------------------------------------------------------

echo
echo "=== 7/10 SYSTEMD ==="

for src in "$INSTALL_DIR"/systemd/*.service \
           "$INSTALL_DIR"/systemd/*.timer
do
    [ -f "$src" ] || continue

    name="$(basename "$src")"
    dest="$SYSTEMD_DIR/$name"

    sed \
        -e "s|@INSTALL_DIR@|$INSTALL_DIR|g" \
        -e "s|@SCRIPT_DIR@|$SCRIPT_DIR|g" \
        "$src" > "$dest"

    # Service'lere portable script yolu icin environment ekle.
    if [[ "$name" == *.service ]]; then

        python3 - "$dest" "$INSTALL_DIR" <<'PY'
from pathlib import Path
import sys

p = Path(sys.argv[1])
install_dir = sys.argv[2]

s = p.read_text()

marker = "[Service]\n"

if marker in s and "Environment=FATURA_TAKIP_DIR=" not in s:
    s = s.replace(
        marker,
        marker + f'Environment=FATURA_TAKIP_DIR={install_dir}\n',
        1
    )

p.write_text(s)
PY

    fi

    chmod 644 "$dest"

    echo "OK: $dest"
done

systemctl daemon-reload

# Backup timer guvenle aktif edilebilir.
systemctl enable fatura-backup.timer >/dev/null

# Collector timerlari bilerek otomatik enable edilmiyor.
systemctl disable fatura-ck.timer >/dev/null 2>&1 || true
systemctl disable fatura-iski.timer >/dev/null 2>&1 || true
systemctl disable fatura-igdas.timer >/dev/null 2>&1 || true

echo "Systemd unitleri kuruldu."
echo "Backup timer enable edildi."
echo "Collector timerlari henuz enable edilmedi."

# ------------------------------------------------------------
# 9. DOCKER BUILD
# ------------------------------------------------------------

echo
echo "=== 8/10 DOCKER BUILD ==="

docker compose build collector dashboard

echo
echo "Docker image build: OK"

# ------------------------------------------------------------
# 10. BROWSER + DASHBOARD
# ------------------------------------------------------------

echo
echo "=== 9/10 SERVISLER ==="

docker compose up -d browser dashboard

echo
echo "Containerlar:"
docker compose ps

# ------------------------------------------------------------
# 11. HEALTH CHECK
# ------------------------------------------------------------

echo
echo "=== 10/10 HEALTH CHECK ==="

HEALTH_OK=0

for attempt in $(seq 1 30); do

    if curl \
        -fsS \
        http://127.0.0.1:8180/health \
        >/tmp/fatura-health.txt 2>/dev/null
    then
        HEALTH_OK=1
        break
    fi

    sleep 1
done

if [ "$HEALTH_OK" -ne 1 ]; then
    echo
    echo "HATA: Dashboard health check basarisiz."
    echo
    echo "Kontrol:"
    echo "  cd $INSTALL_DIR"
    echo "  docker compose logs dashboard"
    exit 1
fi

echo "Dashboard health: $(cat /tmp/fatura-health.txt)"

rm -f /tmp/fatura-health.txt

echo
echo "============================================================"
echo "=== KURULUM BASARILI ==="
echo "============================================================"
echo
echo "Kurulum dizini:"
echo "  $INSTALL_DIR"
echo
echo "Dashboard:"
echo "  http://SUNUCU_IP:8180"
echo
echo "Chromium:"
echo "  http://SUNUCU_IP:3100"
echo
echo "ONEMLI:"
echo
echo "1. Once kullanici bilgilerini girin:"
echo
echo "   nano $INSTALL_DIR/.env"
echo
echo "2. Ardindan collectorlari TEK TEK manuel test edin:"
echo
echo "   systemctl start fatura-ck.service"
echo "   systemctl start fatura-iski.service"
echo "   systemctl start fatura-igdas.service"
echo
echo "3. Testler basariliysa otomasyonu etkinlestirin:"
echo
echo "   systemctl enable --now fatura-ck.timer"
echo "   systemctl enable --now fatura-iski.timer"
echo "   systemctl enable --now fatura-igdas.timer"
echo
echo "4. Timerlari kontrol edin:"
echo
echo "   systemctl list-timers 'fatura-*'"
echo
echo "NOT:"
echo "Collector timerlari guvenlik nedeniyle kurulum sirasinda"
echo "otomatik etkinlestirilmedi."
echo
echo "============================================================"
