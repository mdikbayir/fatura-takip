import base64
import json
import os
import sqlite3
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import requests
import websocket
from websocket import WebSocketTimeoutException


CDP = "http://127.0.0.1:9222"
DB_PATH = "/data/faturalar.db"
PDF_ROOT = "/pdfs/ck-bogazici"
PROVIDER = "ck-bogazici"

ACCOUNT_ID = os.environ.get("CK_ACCOUNT_ID")
BILL_COUNT = int(os.environ.get("CK_BILL_COUNT", "12"))

if not ACCOUNT_ID:
    raise SystemExit("HATA: CK_ACCOUNT_ID tanımlı değil.")


def to_float(value):
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", "."))
    except (ValueError, TypeError):
        return None


def parse_date(value):
    if not value:
        return None

    value = str(value)

    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass

    return value


def reading_days(first_date, last_date):
    if not first_date or not last_date:
        return None

    try:
        a = datetime.strptime(first_date, "%Y-%m-%d").date()
        b = datetime.strptime(last_date, "%Y-%m-%d").date()
        return (b - a).days
    except ValueError:
        return None


def find_page():
    pages = requests.get(f"{CDP}/json/list", timeout=10).json()

    return next(
        (
            p for p in pages
            if p.get("type") == "page"
            and "online.ckenerji.com.tr" in p.get("url", "")
        ),
        None
    )


def wait_for_id(ws, command_id):
    while True:
        msg = json.loads(ws.recv())
        if msg.get("id") == command_id:
            return msg


def evaluate(ws, command_id, expression):
    ws.send(json.dumps({
        "id": command_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True
        }
    }))

    response = wait_for_id(ws, command_id)

    result = response.get("result", {}).get("result", {})

    if "value" not in result:
        raise RuntimeError("CDP JavaScript sonucu alınamadı.")

    return json.loads(result["value"])


def api_post(ws, command_id, path, payload, token, region):
    payload_js = json.dumps(payload)
    token_js = json.dumps(token)
    region_js = json.dumps(region)

    expression = f"""
    (async () => {{
        const r = await fetch({json.dumps(path)}, {{
            method: 'POST',
            credentials: 'include',
            headers: {{
                'Accept': 'application/json, text/plain, */*',
                'Content-Type': 'application/json',
                'token': {token_js},
                'x-region': {region_js}
            }},
            body: JSON.stringify({payload_js})
        }});

        return JSON.stringify({{
            status: r.status,
            body: await r.text()
        }});
    }})()
    """

    result = evaluate(ws, command_id, expression)

    if result["status"] != 200:
        raise RuntimeError(
            f"{path} HTTP {result['status']}: "
            f"{result['body'][:300]}"
        )

    return json.loads(result["body"])


def capture_session_headers(ws, max_attempts=3):
    """
    CK faturalar sayfasini acarak account/detail isteginden
    oturum headerlarini yakalar.

    Network olaylarini kaybetmeden ayni dongude hem API
    istegini hem de /login yonlendirmesini kontrol eder.
    """

    import time

    ws.settimeout(3)
    command_id = 10000

    for attempt in range(1, max_attempts + 1):
        print(
            f"CK oturum bilgisi yakalama "
            f"denemesi {attempt}/{max_attempts}..."
        )

        command_id += 1
        ws.send(json.dumps({
            "id": command_id,
            "method": "Network.enable"
        }))

        try:
            wait_for_id(ws, command_id)
        except WebSocketTimeoutException:
            print("  Network.enable zaman asimi.")
            continue

        # Ana sayfaya git.
        command_id += 1
        ws.send(json.dumps({
            "id": command_id,
            "method": "Page.navigate",
            "params": {
                "url": "https://online.ckenerji.com.tr/"
            }
        }))

        try:
            wait_for_id(ws, command_id)
        except WebSocketTimeoutException:
            print("  CK ana sayfa gecisi zaman asimi.")
            continue

        time.sleep(2)

        # Fatura sayfasina git.
        command_id += 1
        ws.send(json.dumps({
            "id": command_id,
            "method": "Page.navigate",
            "params": {
                "url": (
                    "https://online.ckenerji.com.tr"
                    "/account/bills"
                )
            }
        }))

        try:
            wait_for_id(ws, command_id)
        except WebSocketTimeoutException:
            print("  Fatura sayfasi gecisi zaman asimi.")
            continue

        deadline = time.monotonic() + 20
        last_route_check = 0

        while time.monotonic() < deadline:
            # Route'u periyodik kontrol et.
            if time.monotonic() - last_route_check >= 1:
                command_id += 1
                route_id = command_id

                ws.send(json.dumps({
                    "id": route_id,
                    "method": "Runtime.evaluate",
                    "params": {
                        "expression": "location.pathname",
                        "returnByValue": True
                    }
                }))

                last_route_check = time.monotonic()
            else:
                route_id = None

            try:
                msg = json.loads(ws.recv())

            except WebSocketTimeoutException:
                continue

            # API istegini kacirmadan yakala.
            if (
                msg.get("method")
                == "Network.requestWillBeSent"
            ):
                req = (
                    msg.get("params", {})
                    .get("request", {})
                )

                if (
                    "/api/account/detail"
                    in req.get("url", "")
                ):
                    headers = {
                        str(k).lower(): v
                        for k, v in
                        req.get("headers", {}).items()
                    }

                    token = headers.get("token")
                    region = headers.get("x-region")

                    if token and region:
                        print(
                            "  CK oturum bilgileri yakalandi."
                        )
                        ws.settimeout(90)
                        return token, region

            # Bu turdaki route cevabi geldiyse kontrol et.
            if (
                route_id is not None
                and msg.get("id") == route_id
            ):
                pathname = (
                    msg.get("result", {})
                    .get("result", {})
                    .get("value", "")
                )

                if pathname == "/login":
                    ws.settimeout(90)
                    raise CKSessionExpiredError(
                        "CK Enerji oturumu sona erdi."
                    )

        print(
            "  CK API istegi beklenirken zaman asimi."
        )

    ws.settimeout(90)

    raise RuntimeError(
        "CK oturum bilgileri "
        f"{max_attempts} denemede yakalanamadi."
    )


def named_values(items):
    result = {}

    if not isinstance(items, list):
        return result

    for item in items:
        if not isinstance(item, dict):
            continue

        name = item.get("name")

        if name:
            result[str(name).lower()] = item.get("value")

    return result



def valid_pdf(path):
    try:
        if not os.path.isfile(path):
            return False

        if os.path.getsize(path) < 100:
            return False

        with open(path, "rb") as f:
            return f.read(5) == b"%PDF-"

    except OSError:
        return False


def save_bill_pdf(ws, command_id, bill_id, period, token, region):
    if not period:
        raise RuntimeError("Fatura dönemi bulunamadı.")

    parts = str(period).split("-")

    if len(parts) != 2:
        raise RuntimeError(f"Geçersiz dönem: {period}")

    month, year = parts

    directory = os.path.join(PDF_ROOT, year)
    os.makedirs(directory, exist_ok=True)

    path = os.path.join(
        directory,
        f"{year}-{month.zfill(2)}.pdf"
    )

    # Daha önce indirilmiş geçerli PDF varsa dokunma.
    if valid_pdf(path):
        return path, "mevcut"

    data = api_post(
        ws,
        command_id,
        "/api/bill/pdf",
        {"billId": bill_id},
        token,
        region
    )

    response = data.get("response", {})

    if not isinstance(response, dict):
        raise RuntimeError("PDF response geçersiz.")

    encoded = response.get("base64Pdf")

    if not encoded:
        raise RuntimeError("base64Pdf bulunamadı.")

    # data:application/pdf;base64,... biçimi ihtimalini de destekle.
    if "," in encoded:
        encoded = encoded.split(",", 1)[1]

    try:
        pdf = base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise RuntimeError(
            f"Base64 çözülemedi: {exc}"
        ) from exc

    if not pdf.startswith(b"%PDF-"):
        raise RuntimeError("İndirilen veri PDF değil.")

    tmp = path + ".tmp"

    with open(tmp, "wb") as f:
        f.write(pdf)
        f.flush()
        os.fsync(f.fileno())

    os.replace(tmp, path)

    return path, "indirildi"

def create_database(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS invoices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            provider TEXT NOT NULL,
            bill_id TEXT NOT NULL,
            bill_no TEXT,

            period TEXT,
            invoice_date TEXT,
            due_date TEXT,

            amount_tl REAL,

            status_code TEXT,
            payment_status TEXT,
            payment_date TEXT,

            reading_days INTEGER,
            consumption_kwh REAL,
            daily_kwh REAL,

            day_kwh REAL,
            peak_kwh REAL,
            night_kwh REAL,

            first_index REAL,
            last_index REAL,

            first_read_date TEXT,
            last_read_date TEXT,

            demand_kw REAL,
            installed_power_kw REAL,
            contract_power_kw REAL,

            previous_year_kwh REAL,
            current_year_kwh REAL,

            pdf_path TEXT,

            collected_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            UNIQUE(provider, bill_id)
        )
    """)

    conn.commit()



def create_notifications_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            provider TEXT NOT NULL,
            bill_id TEXT NOT NULL,
            notification_type TEXT NOT NULL,
            sent_at TEXT NOT NULL,
            UNIQUE(provider, bill_id, notification_type)
        )
    """)


def notification_sent(
    conn,
    provider,
    bill_id,
    notification_type="new_invoice"
):
    row = conn.execute("""
        SELECT 1
        FROM notifications
        WHERE provider = ?
          AND bill_id = ?
          AND notification_type = ?
        LIMIT 1
    """, (
        provider,
        bill_id,
        notification_type
    )).fetchone()

    return row is not None


def mark_notification_sent(
    conn,
    provider,
    bill_id,
    notification_type="new_invoice"
):
    sent_at = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    conn.execute("""
        INSERT OR IGNORE INTO notifications (
            provider,
            bill_id,
            notification_type,
            sent_at
        )
        VALUES (?, ?, ?, ?)
    """, (
        provider,
        bill_id,
        notification_type,
        sent_at
    ))


def telegram_send(message):
    token = os.environ.get(
        "TELEGRAM_BOT_TOKEN",
        ""
    ).strip()

    chat_id = os.environ.get(
        "TELEGRAM_CHAT_ID",
        ""
    ).strip()

    if not token or not chat_id:
        raise RuntimeError(
            "Telegram yapılandırması eksik."
        )

    url = (
        "https://api.telegram.org/bot"
        + token
        + "/sendMessage"
    )

    payload = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": message
    }).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=payload,
        method="POST"
    )

    with urllib.request.urlopen(
        request,
        timeout=15
    ) as response:
        result = json.load(response)

    if not result.get("ok"):
        raise RuntimeError(
            "Telegram API mesajı kabul etmedi."
        )

    return True


def format_tr_date(value):
    if not value:
        return "-"

    try:
        year, month, day = value.split("-")
        return f"{day}.{month}.{year}"
    except Exception:
        return value


def percent_change(current, previous):
    if current is None or previous in (None, 0):
        return None

    return (
        (current - previous)
        / previous
        * 100
    )


def format_change(value):
    if value is None:
        return "-"

    return f"{value:+.1f}%"







def evaluate_value(ws, command_id, expression):
    """
    Runtime.evaluate sonucunu JSON parse etmeye calismadan
    dogrudan Python degeri olarak dondurur.
    """
    ws.send(json.dumps({
        "id": command_id,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True
        }
    }))

    while True:
        msg = json.loads(ws.recv())

        if msg.get("id") != command_id:
            continue

        result = (
            msg.get("result", {})
            .get("result", {})
        )

        if "exceptionDetails" in msg.get("result", {}):
            raise RuntimeError(
                "Runtime.evaluate JavaScript hatasi."
            )

        return result.get("value")



def ck_auto_login(ws):
    """
    CK login formunu mevcut Chromium oturumu icinde
    otomatik doldurur ve giris yapar.
    """
    import time

    login_id = os.environ.get(
        "CK_LOGIN_ID", ""
    ).strip()

    login_password = os.environ.get(
        "CK_LOGIN_PASSWORD", ""
    )

    if not login_id or not login_password:
        print(
            "CK otomatik giris bilgileri tanimli degil."
        )
        return False

    print("CK otomatik giris deneniyor...")

    # Login sayfasina git.
    ws.send(json.dumps({
        "id": 20001,
        "method": "Page.navigate",
        "params": {
            "url":
            "https://online.ckenerji.com.tr/login"
        }
    }))

    try:
        wait_for_id(ws, 20001)
    except WebSocketTimeoutException:
        print(
            "CK login sayfasi gecisi zaman asimi."
        )
        return False

    # Sayfanin ve React formunun tamamen gelmesini bekle.
    deadline = time.monotonic() + 25

    form_ready = False

    while time.monotonic() < deadline:
        time.sleep(1)

        try:
            state = evaluate_value(
                ws,
                20002,
                """
                (() => {
                    const id =
                        document.querySelector('#TCKN');

                    const pw =
                        document.querySelector('#password');

                    const buttons =
                        Array.from(
                            document.querySelectorAll(
                                'button[type="submit"]'
                            )
                        );

                    const loginButton =
                        buttons.find(
                            b =>
                            b.innerText.trim()
                            === 'Giriş Yap'
                        );

                    return {
                        path: location.pathname,
                        ready: document.readyState,
                        tckn: !!id,
                        password: !!pw,
                        loginButton: !!loginButton
                    };
                })()
                """
            )

        except Exception:
            continue

        if state.get("path") != "/login":
            print("CK oturumu zaten aktif.")
            return True

        if (
            state.get("ready") == "complete"
            and state.get("tckn")
            and state.get("password")
            and state.get("loginButton")
        ):
            form_ready = True
            break

    if not form_ready:
        print("CK login formu bulunamadi.")
        return False

    login_id_js = json.dumps(login_id)
    password_js = json.dumps(login_password)

    expression = f"""
    (() => {{
        const setValue = (el, value) => {{
            const setter =
                Object.getOwnPropertyDescriptor(
                    HTMLInputElement.prototype,
                    'value'
                ).set;

            setter.call(el, value);

            el.dispatchEvent(
                new Event(
                    'input',
                    {{bubbles: true}}
                )
            );

            el.dispatchEvent(
                new Event(
                    'change',
                    {{bubbles: true}}
                )
            );

            el.dispatchEvent(
                new Event(
                    'blur',
                    {{bubbles: true}}
                )
            );
        }};

        const id =
            document.querySelector('#TCKN');

        const pw =
            document.querySelector('#password');

        const button =
            Array.from(
                document.querySelectorAll(
                    'button[type="submit"]'
                )
            ).find(
                b =>
                b.innerText.trim()
                === 'Giriş Yap'
            );

        if (!id || !pw || !button) {{
            return false;
        }}

        setValue(id, {login_id_js});
        setValue(pw, {password_js});

        button.click();

        return true;
    }})()
    """

    try:
        clicked = evaluate_value(
            ws,
            20003,
            expression
        )

    except Exception as exc:
        print(
            "CK login formu doldurulamadi: "
            f"{type(exc).__name__}"
        )
        return False

    if not clicked:
        print(
            "CK Giris Yap butonu bulunamadi."
        )
        return False

    # Giris sonucunu bekle.
    deadline = time.monotonic() + 30

    while time.monotonic() < deadline:
        time.sleep(1)

        try:
            path = evaluate_value(
                ws,
                20004,
                "location.pathname"
            )
        except Exception:
            continue

        if path != "/login":
            print("CK otomatik giris basarili.")
            return True

    print(
        "CK otomatik giris basarisiz; "
        "login sayfasinda kalindi."
    )

    return False



class CKSessionExpiredError(RuntimeError):
    pass


def create_system_alerts_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS system_alerts (
            alert_type TEXT PRIMARY KEY,
            active INTEGER NOT NULL DEFAULT 0,
            first_seen TEXT,
            last_seen TEXT,
            notified_at TEXT
        )
    """)


def session_alert_active():
    conn = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(conn)

        row = conn.execute("""
            SELECT active
            FROM system_alerts
            WHERE alert_type = 'ck_session_expired'
        """).fetchone()

        return bool(row and row[0])

    finally:
        conn.close()


def mark_session_alert():
    now = datetime.now(
        timezone.utc
    ).isoformat(timespec="seconds")

    conn = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(conn)

        conn.execute("""
            INSERT INTO system_alerts (
                alert_type,
                active,
                first_seen,
                last_seen,
                notified_at
            )
            VALUES (
                'ck_session_expired',
                1,
                ?,
                ?,
                ?
            )

            ON CONFLICT(alert_type)
            DO UPDATE SET
                active = 1,
                last_seen = excluded.last_seen,
                notified_at = excluded.notified_at
        """, (now, now, now))

        conn.commit()

    finally:
        conn.close()


def clear_session_alert():
    conn = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(conn)

        conn.execute("""
            UPDATE system_alerts
            SET active = 0
            WHERE alert_type = 'ck_session_expired'
        """)

        conn.commit()

    finally:
        conn.close()


def notify_session_expired():
    # Aynı oturum problemi devam ettiği sürece
    # yalnızca ilk tespitte Telegram mesajı gönder.
    if session_alert_active():
        print(
            "CK oturum uyarısı daha önce gönderilmiş."
        )
        return

    message = (
        "⚠️ CK Enerji Oturum Uyarısı\n\n"
        "CK Enerji otomatik giriş işlemi başarısız oldu.\n"
        "Fatura takibinin devam edebilmesi için "
        "manuel giriş yapılması gerekiyor."
    )

    try:
        telegram_send(message)
        mark_session_alert()

        print(
            "CK oturum uyarısı Telegram'a gönderildi."
        )

    except Exception as exc:
        # Başarısız bildirimi aktif olarak işaretlemiyoruz;
        # sonraki çalışmada tekrar denenebilir.
        print(
            "CK oturum uyarısı gönderilemedi: "
            f"{type(exc).__name__}"
        )


def main():
    page = find_page()

    if not page:
        raise SystemExit("HATA: CK Enerji sekmesi bulunamadı.")

    print("CK fatura sekmesi bulundu.")

    ws = websocket.create_connection(
        page["webSocketDebuggerUrl"],
        timeout=90
    )

    try:
        print("CK oturumu kontrol ediliyor...")

        try:
            token, region = capture_session_headers(ws)

        except CKSessionExpiredError:
            print(
                "CK Enerji oturumu sona erdi."
            )

            # Once otomatik yeniden giris dene.
            if not ck_auto_login(ws):
                print(
                    "HATA: CK otomatik giris basarisiz. "
                    "Manuel mudahale gerekiyor."
                )

                notify_session_expired()

                ws.close()

                raise SystemExit(2)

            # Giris basarili. Yeni oturumun token ve
            # x-region bilgilerini tekrar yakala.
            print(
                "CK oturum bilgileri yeniden aliniyor..."
            )

            try:
                token, region = capture_session_headers(ws)

            except CKSessionExpiredError:
                print(
                    "HATA: Otomatik giris sonrasi "
                    "CK oturumu olusturulamadi."
                )

                notify_session_expired()

                ws.close()

                raise SystemExit(2)

        # Buraya geldiysek CK oturumu yeniden saglikli.
        # Onceki session-expired alarmini sifirla.
        clear_session_alert()

        print("token: bulundu")
        print("x-region: bulundu")

        account_data = api_post(
            ws,
            10,
            "/api/account/detail",
            {
                "accountId": ACCOUNT_ID,
                "billCount": BILL_COUNT
            },
            token,
            region
        )

        bills = (
            account_data.get("response", {})
            .get("mainData", {})
            .get("billList", {})
            .get("bill", [])
        )

        if not bills:
            raise RuntimeError("CK hesabında fatura bulunamadı.")

        print(f"Fatura listesi: {len(bills)} kayıt")

        valid_bills = [
            bill for bill in bills
            if isinstance(bill, dict) and bill.get("billId")
        ]

        import time

        detail_by_id = {}
        annual = []

        print("Fatura detayları tek tek alınıyor...")

        for index, bill in enumerate(valid_bills, start=1):
            print(
                f"  [{index}/{len(valid_bills)}] "
                f"{bill.get('billDate', '-')} detayı alınıyor..."
            )

            try:
                detail_data = api_post(
                    ws,
                    100 + index,
                    "/api/bill/detail",
                    {
                        "accountId": ACCOUNT_ID,
                        "billIdList": [
                            {
                                "billId": bill["billId"]
                            }
                        ]
                    },
                    token,
                    region
                )

            except RuntimeError as exc:
                # Tek bir eski faturadaki CK API hatası
                # bütün collector çalışmasını durdurmasın.
                #
                # billId, accountId, token veya diğer kişisel
                # bilgiler loglanmaz.
                error_text = str(exc)

                if (
                    "BILL_NOT_FOUND" in error_text
                    or "HTTP 400" in error_text
                ):
                    print(
                        f"  [{index}/{len(valid_bills)}] "
                        "detay CK tarafından bulunamadı; "
                        "atlandı."
                    )

                    time.sleep(0.4)
                    continue

                # Beklenmeyen API hatalarını gizlemeyelim.
                raise

            response_items = detail_data.get("response", [])

            # Her bill/detail çağrısında yalnızca tek fatura
            # gönderiyoruz. CK'nin detail cevabındaki billId,
            # account/detail billId'sinden farklı formatta olduğu
            # için ID'leri birbirine eşleştirmiyoruz.
            # Dönen ilk detail kaydını sorguladığımız faturaya bağlıyoruz.
            if (
                isinstance(response_items, list)
                and response_items
                and isinstance(response_items[0], dict)
            ):
                detail_by_id[bill["billId"]] = response_items[0]

            # Yıllık özet her detail cevabında geliyor.
            if not annual:
                candidate = detail_data.get(
                    "lastTwoYearConsuption",
                    []
                )

                if isinstance(candidate, list):
                    annual = candidate

            # CK API'yi arka arkaya bombardımana tutmayalım.
            time.sleep(0.4)

    except Exception:
        ws.close()
        raise

    annual_by_year = {}

    if isinstance(annual, list):
        for item in annual:
            if not isinstance(item, dict):
                continue

            year = str(item.get("year", ""))
            consumption = to_float(item.get("consumption"))

            if year and consumption is not None:
                annual_by_year[year] = consumption

    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    conn = sqlite3.connect(DB_PATH)

    try:
        create_database(conn)
        create_notifications_table(conn)

        now = datetime.now(timezone.utc).isoformat(timespec="seconds")

        saved = 0

        for bill in valid_bills:
            bill_id = bill["billId"]

            # Detail API'den veri alınamayan eski faturayı
            # mevcut SQLite kaydının üzerine boş değerlerle yazma.
            # Mevcut DB kaydı ve PDF aynen korunur.
            if bill_id not in detail_by_id:
                print(
                    f"  {bill.get('billDate', '-')}: "
                    "detay alınamadığı için mevcut kayıt korundu."
                )
                continue

            detail_item = detail_by_id[bill_id]
            main_data = detail_item.get("mainData", {})

            cons = named_values(
                main_data.get("consInfoList", {}).get("consInfo", [])
            )

            bill_info = named_values(
                main_data.get("billInfoList", {}).get("billInfo", [])
            )

            customer = main_data.get("billCustomerInfo", {})

            first_read_date = parse_date(cons.get("cmlastread"))
            last_read_date = parse_date(cons.get("readdate"))

            period = customer.get("billTerm")

            invoice_date = (
                main_data.get("billDate")
                or bill.get("billDate")
            )

            due_date = (
                main_data.get("dueDate")
                or bill.get("dueDate")
            )

            amount = to_float(
                main_data.get("totalAmount")
                or bill.get("billAmount")
            )

            status_code = (
                main_data.get("billStatus")
                or bill.get("billStatus")
            )

            payment_state = bill_info.get("paymentinduedate")
            payment_date = parse_date(
                bill_info.get("paymentdate")
                or bill.get("paymentDate")
            )

            # CK'nin yıllık özetinden dönem yılını ve bir önceki yılı al.
            period_year = None

            if period and "-" in str(period):
                try:
                    period_year = int(str(period).split("-")[-1])
                except ValueError:
                    pass

            current_year_kwh = (
                to_float(customer.get("currYearCons"))
                if customer.get("currYearCons") is not None
                else None
            )

            previous_year_kwh = None

            if period_year:
                previous_year_kwh = annual_by_year.get(
                    str(period_year - 1)
                )

                if current_year_kwh is None:
                    current_year_kwh = annual_by_year.get(
                        str(period_year)
                    )

            values = {
                "provider": PROVIDER,
                "bill_id": bill_id,
                "bill_no": bill.get("billNo"),

                "period": period,
                "invoice_date": parse_date(invoice_date),
                "due_date": parse_date(due_date),

                "amount_tl": amount,

                "status_code": status_code,
                "payment_status": payment_state,
                "payment_date": payment_date,

                "reading_days": reading_days(
                    first_read_date,
                    last_read_date
                ),

                "consumption_kwh": to_float(
                    cons.get("cmactiveconsumption")
                ),

                "daily_kwh": to_float(
                    detail_item.get("dailyKwh")
                ),

                "day_kwh": to_float(
                    cons.get("cmshoulderpeakconsumption")
                ),

                "peak_kwh": to_float(
                    cons.get("cmpeakconsumption")
                ),

                "night_kwh": to_float(
                    cons.get("cmoffpeakconsumption")
                ),

                "first_index": to_float(
                    cons.get("cmactivefirstread")
                ),

                "last_index": to_float(
                    cons.get("cmactivelastread")
                ),

                "first_read_date": first_read_date,
                "last_read_date": last_read_date,

                "demand_kw": to_float(
                    cons.get("cmdemand")
                ),

                "installed_power_kw": to_float(
                    cons.get("cminstpower")
                ),

                "contract_power_kw": to_float(
                    cons.get("cmpower")
                ),

                "previous_year_kwh": previous_year_kwh,
                "current_year_kwh": current_year_kwh,

                "pdf_path": None,

                "collected_at": now,
                "updated_at": now
            }

            try:
                pdf_path, pdf_state = save_bill_pdf(
                    ws,
                    1000 + saved,
                    bill_id,
                    period,
                    token,
                    region
                )

                values["pdf_path"] = pdf_path

                print(
                    f"  PDF {period}: {pdf_state}"
                )

            except Exception as exc:
                print(
                    f"  PDF {period}: HATA - {exc}"
                )

            columns = list(values.keys())
            placeholders = ",".join("?" for _ in columns)

            update_columns = [
                c for c in columns
                if c not in ("provider", "bill_id", "collected_at")
            ]

            sql = f"""
                INSERT INTO invoices (
                    {",".join(columns)}
                )
                VALUES ({placeholders})

                ON CONFLICT(provider, bill_id)
                DO UPDATE SET
                    {",".join(f"{c}=excluded.{c}" for c in update_columns)}
            """

            conn.execute(
                sql,
                [values[c] for c in columns]
            )

            # Bu fatura için daha önce yeni-fatura bildirimi
            # gönderilmediyse Telegram'a bildir.
            if not notification_sent(
                conn,
                PROVIDER,
                bill_id,
                "new_invoice"
            ):
                previous = conn.execute("""
                    SELECT
                        consumption_kwh,
                        amount_tl
                    FROM invoices
                    WHERE provider = ?
                      AND bill_id != ?
                      AND invoice_date < ?
                    ORDER BY invoice_date DESC
                    LIMIT 1
                """, (
                    PROVIDER,
                    bill_id,
                    values["invoice_date"]
                )).fetchone()

                previous_kwh = (
                    previous[0]
                    if previous
                    else None
                )

                previous_amount = (
                    previous[1]
                    if previous
                    else None
                )

                kwh_change = percent_change(
                    values["consumption_kwh"],
                    previous_kwh
                )

                amount_change = percent_change(
                    values["amount_tl"],
                    previous_amount
                )

                period_text = (
                    values["period"]
                    or values["invoice_date"]
                    or "-"
                )

                message = (
                    "⚡ Yeni Elektrik Faturası\n\n"
                    f"📅 Dönem: {period_text}\n"
                    f"⚡ Tüketim: "
                    f"{values['consumption_kwh'] or 0:.3f} kWh\n"
                    f"💰 Tutar: "
                    f"{values['amount_tl'] or 0:.2f} TL\n"
                    f"⏰ Son ödeme: "
                    f"{format_tr_date(values['due_date'])}\n"
                    f"📊 Tüketim değişimi: "
                    f"{format_change(kwh_change)}\n"
                    f"📈 Fatura değişimi: "
                    f"{format_change(amount_change)}\n"
                    f"📄 PDF: "
                    f"{'Arşivlendi' if values['pdf_path'] else 'Yok'}"
                )

                try:
                    telegram_send(message)

                    mark_notification_sent(
                        conn,
                        PROVIDER,
                        bill_id,
                        "new_invoice"
                    )

                    # Telegram basariyla gonderildiyse bildirim
                    # kaydini hemen kalici hale getir.
                    # Collector daha sonra hata verse bile ayni
                    # fatura tekrar bildirilmez.
                    conn.commit()

                    print(
                        f"  Telegram {period_text}: gönderildi"
                    )

                except Exception as exc:
                    # Token, Chat ID veya mesaj içeriğini loglama.
                    print(
                        f"  Telegram {period_text}: "
                        f"HATA - {type(exc).__name__}"
                    )

            saved += 1

            print(
                f'{values["period"] or values["invoice_date"]} | '
                f'{values["consumption_kwh"]} kWh | '
                f'{values["amount_tl"]} TL | '
                f'{values["payment_status"] or values["status_code"]}'
            )

        conn.commit()

        print()
        print(f"SQLite kayıt işlemi tamamlandı: {saved} fatura")
        print("Veritabanı:", DB_PATH)

    finally:
        conn.close()
        ws.close()


if __name__ == "__main__":
    main()
