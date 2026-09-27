import json
import os
import time
import urllib.parse
import urllib.request
import sqlite3
from datetime import datetime

import websocket


CDP_URL = "http://127.0.0.1:9222/json"

API_BASE = (
    "https://esubeapi.iski.gov.tr"
    "/EsubeAPI/fatura"
)


def find_iski_page():
    pages = json.load(
        urllib.request.urlopen(
            CDP_URL,
            timeout=5
        )
    )

    return next(
        (
            p for p in pages
            if p.get("type") == "page"
            and "esube.iski.gov.tr"
            in p.get("url", "")
        ),
        None
    )


def evaluate(ws, expression):
    ws.send(json.dumps({
        "id": 100,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True
        }
    }))

    while True:
        msg = json.loads(ws.recv())

        if msg.get("id") != 100:
            continue

        obj = (
            msg.get("result", {})
            .get("result", {})
        )

        return obj.get("value")



DB_PATH = "/data/faturalar.db"
PROVIDER = "iski"


def parse_number(value):
    """ISKI sayisal stringlerini REAL'e cevir."""
    if value is None:
        return None

    if isinstance(value, (int, float)):
        return float(value)

    value = str(value).strip()

    if not value:
        return None

    value = (
        value
        .replace("₺", "")
        .replace("TL", "")
        .replace("m³", "")
        .replace("m3", "")
        .replace(" ", "")
    )

    # 1.234,56 -> 1234.56
    if "," in value and "." in value:
        value = (
            value
            .replace(".", "")
            .replace(",", ".")
        )

    # 1234,56 -> 1234.56
    elif "," in value:
        value = value.replace(",", ".")

    try:
        return float(value)
    except ValueError:
        return None


def parse_integer(value):
    number = parse_number(value)

    if number is None:
        return None

    return int(number)


def normalize_date(value):
    if not value:
        return None

    value = str(value).strip()

    formats = (
        "%d.%m.%Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
        "%Y-%m-%dT%H:%M:%S",
    )

    for fmt in formats:
        try:
            return datetime.strptime(
                value, fmt
            ).strftime("%Y-%m-%d")
        except ValueError:
            pass

    # Bilinmeyen tarih formatini uydurmak
    # yerine mevcut haliyle sakla.
    return value


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
            "Telegram yapilandirmasi eksik."
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
            "Telegram API mesaji kabul etmedi."
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
    if (
        current is None
        or previous in (None, 0)
    ):
        return None

    return (
        (current - previous)
        / previous
        * 100
    )


def format_change(value):
    if value is None:
        return "-"

    if value > 0:
        return f"+%{value:.1f}"

    if value < 0:
        return f"-%{abs(value):.1f}"

    return "%0.0"


def send_pending_notifications():
    """
    JPG arsivleme tamamlandiktan sonra
    bildirilmemis ISKI faturalarini gonderir.
    """

    con = sqlite3.connect(DB_PATH)

    try:
        pending = con.execute(
            """
            SELECT
                i.bill_id,
                i.period,
                i.invoice_date,
                i.due_date,
                i.amount_tl,
                i.consumption_m3,
                i.pdf_path
            FROM invoices i
            WHERE i.provider = ?
              AND NOT EXISTS (
                  SELECT 1
                  FROM notifications n
                  WHERE n.provider =
                        i.provider
                    AND n.bill_id =
                        i.bill_id
                    AND n.notification_type =
                        'new_invoice'
              )
            ORDER BY
                i.invoice_date ASC
            """,
            (PROVIDER,)
        ).fetchall()

        sent = 0
        failed = 0
        waiting_jpg = 0

        for row in pending:
            (
                bill_id,
                period,
                invoice_date,
                due_date,
                amount_tl,
                consumption_m3,
                pdf_path,
            ) = row

            # Yeni fatura gorseli henuz
            # arsivlenmediyse bildirim gonderme.
            if not pdf_path:
                waiting_jpg += 1
                continue

            previous = con.execute(
                """
                SELECT
                    consumption_m3,
                    amount_tl
                FROM invoices
                WHERE provider = ?
                  AND bill_id != ?
                  AND invoice_date < ?
                ORDER BY
                    invoice_date DESC
                LIMIT 1
                """,
                (
                    PROVIDER,
                    bill_id,
                    invoice_date
                )
            ).fetchone()

            previous_m3 = (
                previous[0]
                if previous
                else None
            )

            previous_amount = (
                previous[1]
                if previous
                else None
            )

            m3_change = percent_change(
                consumption_m3,
                previous_m3
            )

            amount_change = percent_change(
                amount_tl,
                previous_amount
            )

            period_text = (
                period
                or invoice_date
                or "-"
            )

            message = (
                "💧 Yeni İSKİ Faturası\n\n"
                f"📅 Dönem: {period_text}\n"
                f"💧 Tüketim: "
                f"{consumption_m3 or 0:.2f} m³\n"
                f"💰 Tutar: "
                f"{amount_tl or 0:.2f} TL\n"
                f"⏰ Son ödeme: "
                f"{format_tr_date(due_date)}\n"
                f"📊 Tüketim değişimi: "
                f"{format_change(m3_change)}\n"
                f"📈 Fatura değişimi: "
                f"{format_change(amount_change)}\n"
                f"🖼️ JPG: Arşivlendi"
            )

            try:
                telegram_send(message)

                now = (
                    datetime.now()
                    .astimezone()
                    .isoformat(
                        timespec="seconds"
                    )
                )

                con.execute(
                    """
                    INSERT OR IGNORE INTO
                    notifications (
                        provider,
                        bill_id,
                        notification_type,
                        sent_at
                    )
                    VALUES (
                        ?,
                        ?,
                        'new_invoice',
                        ?
                    )
                    """,
                    (
                        PROVIDER,
                        bill_id,
                        now
                    )
                )

                # Telegram basariliysa
                # hemen kalici hale getir.
                con.commit()

                sent += 1

                print(
                    f"  Telegram "
                    f"{period_text}: gonderildi"
                )

            except Exception as exc:
                failed += 1

                # Secret veya fatura kimligi
                # loglanmaz.
                print(
                    f"  Telegram "
                    f"{period_text}: "
                    f"HATA - "
                    f"{type(exc).__name__}"
                )

        return {
            "pending": len(pending),
            "sent": sent,
            "failed": failed,
            "waiting_jpg": waiting_jpg,
        }

    finally:
        con.close()


def save_to_database(bills):
    now = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    con = sqlite3.connect(DB_PATH)

    try:
        con.execute("BEGIN")

        existing_ids = {
            row[0]
            for row in con.execute(
                """
                SELECT bill_id
                FROM invoices
                WHERE provider = ?
                """,
                (PROVIDER,)
            )
        }

        # Baseline yalnizca ISKI ilk kez
        # veritabanina aktarilirken olusturulur.
        # Sonraki calismalarda bulunan yeni
        # faturalar bildirim adayi olarak kalir.
        initial_import = (
            len(existing_ids) == 0
        )

        inserted = 0
        updated = 0
        baseline = 0

        for bill in bills:
            if not bill.get("ok"):
                continue

            bill_id = str(
                bill.get("faturaNo") or ""
            ).strip()

            if not bill_id:
                continue

            was_existing = (
                bill_id in existing_ids
            )

            con.execute(
                """
                INSERT INTO invoices (
                    provider,
                    bill_id,
                    bill_no,
                    period,
                    invoice_date,
                    due_date,
                    amount_tl,
                    reading_days,
                    first_read_date,
                    last_read_date,
                    consumption_m3,
                    daily_m3,
                    water_charge_tl,
                    wastewater_charge_tl,
                    ctv_tl,
                    vat_tl,
                    collected_at,
                    updated_at
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(provider, bill_id)
                DO UPDATE SET
                    bill_no = excluded.bill_no,
                    period = excluded.period,
                    invoice_date =
                        excluded.invoice_date,
                    due_date =
                        excluded.due_date,
                    amount_tl =
                        excluded.amount_tl,
                    reading_days =
                        excluded.reading_days,
                    first_read_date =
                        excluded.first_read_date,
                    last_read_date =
                        excluded.last_read_date,
                    consumption_m3 =
                        excluded.consumption_m3,
                    daily_m3 =
                        excluded.daily_m3,
                    water_charge_tl =
                        excluded.water_charge_tl,
                    wastewater_charge_tl =
                        excluded.wastewater_charge_tl,
                    ctv_tl =
                        excluded.ctv_tl,
                    vat_tl =
                        excluded.vat_tl,
                    updated_at =
                        excluded.updated_at
                """,
                (
                    PROVIDER,
                    bill_id,
                    bill_id,
                    bill.get("donem"),
                    normalize_date(
                        bill.get("faturaTarihi")
                    ),
                    normalize_date(
                        bill.get("sonOdemeTarihi")
                    ),
                    parse_number(
                        bill.get("odenecekTutar")
                    ),
                    parse_integer(
                        bill.get("gunSayisi")
                    ),
                    normalize_date(
                        bill.get("ilkOkumaTarihi")
                    ),
                    normalize_date(
                        bill.get("sonOkumaTarihi")
                    ),
                    parse_number(
                        bill.get("toplamM3")
                    ),
                    parse_number(
                        bill.get("gunlukM3")
                    ),
                    parse_number(
                        bill.get("suBedeli")
                    ),
                    parse_number(
                        bill.get("atiksuBedeli")
                    ),
                    parse_number(
                        bill.get("ctv")
                    ),
                    parse_number(
                        bill.get("kdv")
                    ),
                    now,
                    now,
                )
            )

            if was_existing:
                updated += 1
            else:
                inserted += 1

                # Yalnizca ilk toplu aktarimda
                # mevcut faturalar baseline olur.
                if initial_import:
                    con.execute(
                        """
                        INSERT OR IGNORE INTO
                        notifications (
                            provider,
                            bill_id,
                            notification_type,
                            sent_at
                        )
                        VALUES (
                            ?,
                            ?,
                            'new_invoice',
                            ?
                        )
                        """,
                        (
                            PROVIDER,
                            bill_id,
                            now
                        )
                    )

                    baseline += 1

        # -------------------------------------------------
        # ISKI tahmini odeme durumu
        #
        # Bir sonraki faturada gecmisDonemBorcu = 0 ise
        # onceki faturanin odendigi varsayilir.
        #
        # Gercek odeme tarihi bilinmedigi icin
        # payment_date doldurulmaz.
        # -------------------------------------------------

        payment_bills = []

        for bill in bills:
            if not bill.get("ok"):
                continue

            bill_id = str(
                bill.get("faturaNo") or ""
            ).strip()

            invoice_date = normalize_date(
                bill.get("faturaTarihi")
            )

            if not bill_id or not invoice_date:
                continue

            debt_raw = bill.get(
                "gecmisDonemBorcu"
            )

            debt = None

            if debt_raw not in (None, ""):
                debt = parse_number(
                    debt_raw
                )

            payment_bills.append({
                "bill_id": bill_id,
                "invoice_date": invoice_date,
                "previous_debt": debt,
            })

        payment_bills.sort(
            key=lambda x: x["invoice_date"]
        )

        payment_updated = 0

        # Once tum ISKI kayitlarinin tahmini
        # durumunu temizle. payment_date'e
        # dokunmuyoruz.
        con.execute(
            """
            UPDATE invoices
            SET
                payment_status = NULL,
                status_code = NULL
            WHERE provider = ?
            """,
            (PROVIDER,)
        )

        # Bir faturanin odeme durumunu,
        # kendisinden sonraki faturadaki
        # gecmisDonemBorcu belirler.
        for index in range(
            len(payment_bills) - 1
        ):
            current = payment_bills[index]
            next_bill = payment_bills[
                index + 1
            ]

            debt = next_bill[
                "previous_debt"
            ]

            # API degeri yoksa tahmin yapma.
            if debt is None:
                continue

            if abs(debt) < 0.005:
                payment_status = (
                    "paid_estimated"
                )
            else:
                payment_status = (
                    "unpaid_estimated"
                )

            con.execute(
                """
                UPDATE invoices
                SET
                    payment_status = ?,
                    status_code = ?
                WHERE provider = ?
                  AND bill_id = ?
                """,
                (
                    payment_status,
                    "estimated",
                    PROVIDER,
                    current["bill_id"],
                )
            )

            payment_updated += 1

        # En yeni faturanin sonraki faturasi
        # olmadigi icin odeme durumu kesin
        # olarak cikartilamaz.
        if payment_bills:
            newest = payment_bills[-1]

            con.execute(
                """
                UPDATE invoices
                SET
                    payment_status = 'pending',
                    status_code = 'estimated'
                WHERE provider = ?
                  AND bill_id = ?
                """,
                (
                    PROVIDER,
                    newest["bill_id"],
                )
            )

            payment_updated += 1

        con.commit()

        return {
            "inserted": inserted,
            "updated": updated,
            "baseline": baseline,
            "payment_updated":
                payment_updated,
        }

    except Exception:
        con.rollback()
        raise

    finally:
        con.close()

ISKI_SESSION_ALERT = "iski_session_expired"


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


def iski_session_alert_active():
    con = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(con)

        row = con.execute(
            """
            SELECT active
            FROM system_alerts
            WHERE alert_type = ?
            """,
            (ISKI_SESSION_ALERT,)
        ).fetchone()

        return bool(row and row[0])

    finally:
        con.close()


def mark_iski_session_alert():
    now = (
        datetime.now()
        .astimezone()
        .isoformat(timespec="seconds")
    )

    con = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(con)

        con.execute(
            """
            INSERT INTO system_alerts (
                alert_type,
                active,
                first_seen,
                last_seen,
                notified_at
            )
            VALUES (?, 1, ?, ?, ?)

            ON CONFLICT(alert_type)
            DO UPDATE SET
                active = 1,
                last_seen = excluded.last_seen,
                notified_at = excluded.notified_at
            """,
            (
                ISKI_SESSION_ALERT,
                now,
                now,
                now
            )
        )

        con.commit()

    finally:
        con.close()


def clear_iski_session_alert():
    con = sqlite3.connect(DB_PATH)

    try:
        create_system_alerts_table(con)

        con.execute(
            """
            UPDATE system_alerts
            SET active = 0
            WHERE alert_type = ?
            """,
            (ISKI_SESSION_ALERT,)
        )

        con.commit()

    finally:
        con.close()


def notify_iski_session_expired():
    # Ayni oturum problemi devam ederken
    # Telegram mesaji yalnizca bir kez gider.
    if iski_session_alert_active():
        print(
            "ISKI oturum uyarisi "
            "daha once gonderilmis."
        )
        return

    message = (
        "🔐 İSKİ Oturum Uyarısı\n\n"
        "İSKİ e-Devlet oturumu artık geçerli değil.\n"
        "Fatura takibinin devam edebilmesi için "
        "e-Devlet oturumunun yenilenmesi gerekiyor."
    )

    try:
        telegram_send(message)

        mark_iski_session_alert()

        print(
            "ISKI oturum uyarisi "
            "Telegram'a gonderildi."
        )

    except Exception as exc:
        # Telegram basarisizsa alarm aktif
        # isaretlenmez; sonraki calismada
        # tekrar denenebilir.
        print(
            "ISKI oturum uyarisi "
            "gonderilemedi: "
            f"{type(exc).__name__}"
        )



def cdp_pages():
    return json.load(
        urllib.request.urlopen(
            CDP_URL,
            timeout=5
        )
    )


def find_page_by_url(fragment):
    return next(
        (
            p for p in cdp_pages()
            if p.get("type") == "page"
            and fragment in p.get("url", "")
        ),
        None
    )


def open_cdp_page(url):
    endpoint = (
        "http://127.0.0.1:9222/json/new?"
        + urllib.parse.quote(
            url,
            safe=":/?=&"
        )
    )

    request = urllib.request.Request(
        endpoint,
        method="PUT"
    )

    return json.load(
        urllib.request.urlopen(
            request,
            timeout=10
        )
    )


def cdp_evaluate(
    ws,
    expression,
    ident=900
):
    ws.send(json.dumps({
        "id": ident,
        "method": "Runtime.evaluate",
        "params": {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True
        }
    }))

    while True:
        message = json.loads(
            ws.recv()
        )

        if message.get("id") != ident:
            continue

        return (
            message.get("result", {})
            .get("result", {})
            .get("value")
        )


def wait_for_page_url(
    ws,
    fragment,
    timeout=60
):
    deadline = time.time() + timeout
    ident = 1000

    while time.time() < deadline:
        try:
            raw = cdp_evaluate(
                ws,
                """
                JSON.stringify({
                    url: location.href,
                    title: document.title
                })
                """,
                ident
            )

            ident += 1

            if raw:
                state = json.loads(raw)

                if fragment in state.get(
                    "url", ""
                ):
                    return state

        except Exception:
            pass

        time.sleep(1)

    return None


def wait_for_edevlet_mobile_approval(
    ws,
    timeout=180
):
    """
    Mobil onaydan sonraki e-Devlet
    uygulama izin ekranini bekler.

    Telefon onayini kullanici yapar.
    """
    deadline = time.time() + timeout
    ident = 2000

    while time.time() < deadline:
        try:
            raw = cdp_evaluate(
                ws,
                r"""
                (() => {
                    const approve = [
                        ...document.querySelectorAll(
                            'button[name="btn"]'
                        )
                    ].find(b =>
                        (b.value || '').trim()
                            === 'Onayla'
                        ||
                        (b.innerText || '').trim()
                            === 'Onayla'
                    );

                    return JSON.stringify({
                        url: location.href,
                        approve:
                            !!approve,
                        text:
                            document.body
                            ? document.body.innerText
                            : ''
                    });
                })()
                """,
                ident
            )

            ident += 1

            if not raw:
                time.sleep(1)
                continue

            state = json.loads(raw)

            if state.get("approve"):
                return True

            text = state.get(
                "text", ""
            )

            # e-Devlet acik bir hata
            # bildiriyorsa gereksiz yere
            # timeout sonuna kadar bekleme.
            if (
                "Giriş işleminiz tamamlanamadı"
                in text
            ):
                return False

        except Exception:
            # Navigasyon aninda Runtime.evaluate
            # gecici olarak hata verebilir.
            pass

        time.sleep(1)

    return False


def click_edevlet_approve(ws):
    raw = cdp_evaluate(
        ws,
        r"""
        (() => {
            const approve = [
                ...document.querySelectorAll(
                    'button[name="btn"]'
                )
            ].find(b =>
                (b.value || '').trim()
                    === 'Onayla'
                ||
                (b.innerText || '').trim()
                    === 'Onayla'
            );

            if (!approve) {
                return JSON.stringify({
                    ok: false,
                    error:
                        'APPROVE_BUTTON_NOT_FOUND'
                });
            }

            approve.click();

            return JSON.stringify({
                ok: true
            });
        })()
        """,
        3000
    )

    if not raw:
        return False

    result = json.loads(raw)

    return bool(
        result.get("ok")
    )


def wait_for_iski_session(
    ws,
    timeout=60
):
    deadline = time.time() + timeout
    ident = 4000

    while time.time() < deadline:
        try:
            raw = cdp_evaluate(
                ws,
                r"""
                JSON.stringify({
                    url: location.href,

                    token:
                        !!localStorage.getItem(
                            'esube_token'
                        ),

                    contracts:
                        !!localStorage.getItem(
                            'esube_sozlesmeListesi'
                        )
                })
                """,
                ident
            )

            ident += 1

            if raw:
                state = json.loads(raw)

                if (
                    "esube.iski.gov.tr"
                    in state.get("url", "")
                    and state.get("token")
                    and state.get("contracts")
                ):
                    return True

        except Exception:
            pass

        time.sleep(1)

    return False


def iski_edevlet_auto_login():
    """
    ISKI e-Devlet oturumunu yeniler.

    TCKN ve sifre .env'den gelir.
    Mobil Onay kullanici tarafindan
    yapilir. Son e-Devlet Onayla
    butonu otomatik tiklanir.
    """

    tc = os.environ.get(
        "EDEVLET_TCKN", ""
    ).strip()

    password = os.environ.get(
        "EDEVLET_PASSWORD", ""
    ).strip()

    if not tc or not password:
        print(
            "ISKI otomatik giris: "
            "EDEVLET bilgileri eksik."
        )
        return False

    print(
        "ISKI e-Devlet otomatik "
        "giris baslatiliyor..."
    )

    login_url = (
        "https://esube.iski.gov.tr"
        "/Home/Login"
    )

    page = find_page_by_url(
        "/Home/Login"
    )

    if not page:
        page = open_cdp_page(
            login_url
        )

    ws = websocket.create_connection(
        page["webSocketDebuggerUrl"],
        timeout=30
    )

    try:
        # Yeni acilan ISKI Login sayfasinin
        # DOM ve JavaScript tarafinin tamamen
        # hazir olmasini bekle.
        login_page_ready = False

        for attempt in range(30):
            try:
                ready_raw = cdp_evaluate(
                    ws,
                    r"""
                    (() => {
                        return JSON.stringify({
                            ready:
                                document.readyState,
                            kvkk:
                                !!document.querySelector(
                                    '#chkKvkk'
                                ),
                            edevlet:
                                typeof getEDevletLink
                                === 'function',
                            url:
                                location.href
                        });
                    })()
                    """,
                    5000
                )

                ready = json.loads(
                    ready_raw or "{}"
                )

                if (
                    ready.get("ready")
                    == "complete"
                    and ready.get("kvkk")
                    and ready.get("edevlet")
                ):
                    login_page_ready = True
                    break

            except Exception:
                # Yeni sekme yuklenirken CDP
                # gecici olarak cevap vermeyebilir.
                pass

            time.sleep(1)

        if not login_page_ready:
            print(
                "ISKI otomatik giris: "
                "LOGIN_PAGE_NOT_READY"
            )
            return False

        print(
            "ISKI login sayfasi hazir."
        )

        # ISKI aydinlatma metnini onayla
        # ve e-Devlet yonlendirmesini baslat.
        raw = cdp_evaluate(
            ws,
            r"""
            (() => {
                const box =
                    document.querySelector(
                        '#chkKvkk'
                    );

                if (!box) {
                    return JSON.stringify({
                        ok: false,
                        error:
                            'KVKK_NOT_FOUND'
                    });
                }

                if (!box.checked) {
                    box.click();
                }

                if (!box.checked) {
                    return JSON.stringify({
                        ok: false,
                        error:
                            'KVKK_NOT_CHECKED'
                    });
                }

                if (
                    typeof getEDevletLink
                    !== 'function'
                ) {
                    return JSON.stringify({
                        ok: false,
                        error:
                            'EDEVLET_LINK_NOT_FOUND'
                    });
                }

                getEDevletLink();

                return JSON.stringify({
                    ok: true
                });
            })()
            """,
            5000
        )

        if not raw:
            return False

        start = json.loads(raw)

        if not start.get("ok"):
            print(
                "ISKI otomatik giris: "
                + str(
                    start.get("error")
                )
            )
            return False

        state = wait_for_page_url(
            ws,
            "giris.turkiye.gov.tr",
            timeout=60
        )

        if not state:
            print(
                "e-Devlet giris sayfasi "
                "acilamadi."
            )
            return False

        print(
            "e-Devlet giris sayfasi acildi."
        )

        # Hassas degerleri loglamadan
        # JavaScript literal haline getir.
        tc_js = json.dumps(tc)
        password_js = json.dumps(
            password
        )

        raw = cdp_evaluate(
            ws,
            f"""
            (() => {{
                const tc =
                    document.querySelector(
                        '#tridField'
                    );

                const pw =
                    document.querySelector(
                        '#egpField'
                    );

                const submit =
                    document.querySelector(
                        'button[name="submitButton"]'
                    );

                if (!tc || !pw || !submit) {{
                    return JSON.stringify({{
                        ok: false,
                        error:
                            'LOGIN_FORM_NOT_FOUND'
                    }});
                }}

                tc.focus();
                tc.value = {tc_js};
                tc.dispatchEvent(
                    new Event(
                        'input',
                        {{bubbles:true}}
                    )
                );
                tc.dispatchEvent(
                    new Event(
                        'change',
                        {{bubbles:true}}
                    )
                );

                pw.focus();
                pw.value = {password_js};
                pw.dispatchEvent(
                    new Event(
                        'input',
                        {{bubbles:true}}
                    )
                );
                pw.dispatchEvent(
                    new Event(
                        'change',
                        {{bubbles:true}}
                    )
                );

                submit.click();

                return JSON.stringify({{
                    ok: true
                }});
            }})()
            """,
            6000
        )

        if not raw:
            return False

        login_result = json.loads(
            raw
        )

        if not login_result.get("ok"):
            print(
                "e-Devlet formu: "
                + str(
                    login_result.get(
                        "error"
                    )
                )
            )
            return False

        print(
            "e-Devlet sifresi gonderildi."
        )

        print(
            "Telefon Mobil Onayi "
            "bekleniyor..."
        )

        if not wait_for_edevlet_mobile_approval(
            ws,
            timeout=180
        ):
            print(
                "e-Devlet Mobil Onay "
                "tamamlanamadi."
            )
            return False

        print(
            "Mobil Onay tamamlandi."
        )

        if not click_edevlet_approve(
            ws
        ):
            print(
                "e-Devlet son Onayla "
                "butonu tiklanamadi."
            )
            return False

        print(
            "e-Devlet son Onayla: OK"
        )

        if not wait_for_iski_session(
            ws,
            timeout=60
        ):
            print(
                "ISKI oturumu "
                "olusturulamadi."
            )
            return False

        print(
            "ISKI e-Devlet girisi: "
            "BASARILI"
        )

        return True

    finally:
        try:
            ws.close()
        except Exception:
            pass

def main():
    print("ISKI collector baslatiliyor...")

    page = find_iski_page()

    if not page:
        print(
            "ISKI Chromium sekmesi bulunamadi."
        )

        print(
            "ISKI otomatik e-Devlet "
            "girisi deneniyor..."
        )

        try:
            login_ok = (
                iski_edevlet_auto_login()
            )
        except Exception as exc:
            print(
                "ISKI otomatik giris "
                "hatasi: "
                f"{type(exc).__name__}"
            )
            login_ok = False

        if login_ok:
            print(
                "ISKI otomatik giris "
                "basarili."
            )

            # e-Devlet -> ISKI donusunden sonra
            # yeni ISKI execution context'inin
            # tamamen hazir olmasini bekle.
            page = None

            for attempt in range(30):
                candidate = find_iski_page()

                if candidate:
                    test_ws = None

                    try:
                        test_ws = (
                            websocket.create_connection(
                                candidate[
                                    "webSocketDebuggerUrl"
                                ],
                                timeout=10
                            )
                        )

                        ready_raw = cdp_evaluate(
                            test_ws,
                            r"""
                            (() => {
                                return JSON.stringify({
                                    ready:
                                        document.readyState,
                                    url:
                                        location.href,
                                    token:
                                        !!localStorage.getItem(
                                            'esube_token'
                                        ),
                                    contracts:
                                        !!localStorage.getItem(
                                            'esube_sozlesmeListesi'
                                        )
                                });
                            })()
                            """,
                            5000
                        )

                        ready = json.loads(
                            ready_raw or "{}"
                        )

                        if (
                            ready.get("ready")
                            == "complete"
                            and ready.get("token")
                            and ready.get("contracts")
                            and "esube.iski.gov.tr"
                            in ready.get("url", "")
                        ):
                            page = candidate

                            print(
                                "ISKI login sonrasi "
                                "sayfa hazir."
                            )

                            break

                    except Exception:
                        pass

                    finally:
                        if test_ws:
                            try:
                                test_ws.close()
                            except Exception:
                                pass

                time.sleep(1)

        if not page:
            print(
                "ISKI Chromium sekmesi "
                "olusturulamadi."
            )

            notify_iski_session_expired()

            raise SystemExit(2)

    ws = websocket.create_connection(
        page["webSocketDebuggerUrl"],
        timeout=60
    )

    expression = r"""
    (async () => {
        const token =
            localStorage.getItem(
                'esube_token'
            );

        const raw =
            localStorage.getItem(
                'esube_sozlesmeListesi'
            );

        if (!token || !raw) {
            return JSON.stringify({
                ok: false,
                error: 'SESSION_DATA_MISSING'
            });
        }

        let contracts;

        try {
            contracts = JSON.parse(raw);
        } catch (e) {
            return JSON.stringify({
                ok: false,
                error: 'CONTRACT_PARSE_ERROR'
            });
        }

        if (
            !Array.isArray(contracts) ||
            !contracts.length
        ) {
            return JSON.stringify({
                ok: false,
                error: 'CONTRACT_NOT_FOUND'
            });
        }

        const contract =
            contracts[0];

        if (!contract.sozlesmeNo) {
            return JSON.stringify({
                ok: false,
                error: 'CONTRACT_NUMBER_MISSING'
            });
        }

        const headers = {
            'Authorization':
                'Bearer ' + token,

            'Content-Type':
                'application/json'
        };

        const summaryResponse =
            await fetch(
                '""" + API_BASE + r"""/ozetListe',
                {
                    method: 'POST',
                    headers: headers,
                    body: JSON.stringify({
                        sozlesmeNo:
                            contract.sozlesmeNo
                    })
                }
            );

        if (!summaryResponse.ok) {
            return JSON.stringify({
                ok: false,
                error: 'SUMMARY_HTTP_ERROR',
                status:
                    summaryResponse.status
            });
        }

        const summary =
            await summaryResponse.json();

        const bills =
            Array.isArray(summary.data)
            ? summary.data
            : [];

        const output = [];

        for (const bill of bills) {
            if (!bill.numarasi) {
                continue;
            }

            const detailResponse =
                await fetch(
                    '""" + API_BASE + r"""/bilgileri',
                    {
                        method: 'POST',
                        headers: headers,
                        body: JSON.stringify({
                            faturaNo:
                                Number(
                                    bill.numarasi
                                )
                        })
                    }
                );

            if (!detailResponse.ok) {
                output.push({
                    ok: false,
                    faturaNoPresent: true,
                    status:
                        detailResponse.status
                });

                continue;
            }

            const detail =
                await detailResponse.json();

            const d =
                detail.data || {};

            /*
             * Bilerek sadece fatura/analiz
             * alanlarini aliyoruz.
             *
             * adiSoyadi, faturaAdresi,
             * sayac seri no vb. alinmiyor.
             */

            output.push({
                ok: true,

                faturaNo:
                    d.faturaNo ||
                    bill.numarasi,

                donem:
                    d.donemi ||
                    bill.faturaAy,

                faturaTarihi:
                    d.faturaTarihi ||
                    bill.tarihi,

                sonOdemeTarihi:
                    d.sonOdemeTarihi ||
                    bill.sonOdemeTarihi,

                donemTutari:
                    d.donemTutari ||
                    bill.donemTutari,

                odenecekTutar:
                    d.odenecekTutar ??
                    bill.genelToplami,

                toplamM3:
                    d.toplamM3 ||
                    bill.tuketimM3,

                gunlukM3:
                    d.gunlukM3,

                gunSayisi:
                    d.gunSayisi,

                ilkOkumaTarihi:
                    d.ilkOkumaTarihi ||
                    bill.ilkOkumaTarihi,

                sonOkumaTarihi:
                    d.sonOkumaTarihi ||
                    bill.sonOkumaTarihi,

                suBedeli:
                    d.suBedeli,

                atiksuBedeli:
                    d.atiksuBedeli,

                ctv:
                    d.ctv,

                kdv:
                    d.kdv,

                gecmisDonemBorcu:
                    d.gecmisDonemBorcu
            });

            await new Promise(
                resolve =>
                    setTimeout(resolve, 150)
            );
        }

        return JSON.stringify({
            ok: true,
            summaryCount:
                bills.length,
            detailCount:
                output.filter(
                    x => x.ok
                ).length,
            failedCount:
                output.filter(
                    x => !x.ok
                ).length,
            bills: output
        });
    })()
    """

    value = evaluate(
        ws,
        expression
    )

    ws.close()

    if not value:
        raise SystemExit(
            "ISKI sonucu alinamadi."
        )

    result = json.loads(value)

    if not result.get("ok"):
        print(
            "ISKI API: BASARISIZ"
        )

        error = result.get("error")
        status = result.get("status")

        print(
            "Hata:",
            error
        )

        if status:
            print(
                "HTTP:",
                status
            )

        session_expired = (
            error == "SESSION_DATA_MISSING"
            or (
                error == "SUMMARY_HTTP_ERROR"
                and status in (401, 403)
            )
        )

        if session_expired:
            print(
                "ISKI e-Devlet oturumu "
                "gecersiz."
            )

            # Ayni collector calismasinda yalnizca
            # bir kez otomatik e-Devlet girisi dene.
            already_retried = (
                os.environ.get(
                    "ISKI_LOGIN_RETRIED",
                    ""
                ) == "1"
            )

            if not already_retried:
                print(
                    "ISKI otomatik e-Devlet "
                    "girisi deneniyor..."
                )

                try:
                    login_ok = (
                        iski_edevlet_auto_login()
                    )
                except Exception as exc:
                    print(
                        "ISKI otomatik giris "
                        "hatasi: "
                        f"{type(exc).__name__}"
                    )
                    login_ok = False

                if login_ok:
                    print(
                        "ISKI otomatik giris "
                        "basarili."
                    )

                    # Sonsuz yeniden giris dongusunu
                    # engelle.
                    os.environ[
                        "ISKI_LOGIN_RETRIED"
                    ] = "1"

                    print(
                        "ISKI API yeni oturumla "
                        "yeniden deneniyor..."
                    )

                    return main()

            print(
                "ISKI otomatik giris "
                "tamamlanamadi."
            )

            notify_iski_session_expired()

            raise SystemExit(2)

        raise SystemExit(1)

    # API basariliysa onceki oturum
    # alarmini temizle.
    clear_iski_session_alert()

    bills = result.get(
        "bills", []
    )

    print("ISKI API: BASARILI")
    print(
        "Ozet fatura:",
        result.get("summaryCount")
    )
    print(
        "Detay alinan:",
        result.get("detailCount")
    )
    print(
        "Detay hatasi:",
        result.get("failedCount")
    )

    print("\nVeri kalite kontrolu:")

    fields = [
        "faturaNo",
        "donem",
        "faturaTarihi",
        "sonOdemeTarihi",
        "donemTutari",
        "odenecekTutar",
        "toplamM3",
        "gunlukM3",
        "gunSayisi",
        "ilkOkumaTarihi",
        "sonOkumaTarihi",
        "suBedeli",
        "atiksuBedeli",
        "ctv",
        "kdv",
    ]

    valid = [
        b for b in bills
        if b.get("ok")
    ]

    for field in fields:
        count = sum(
            1
            for bill in valid
            if bill.get(field)
            not in (None, "")
        )

        print(
            f"  {field}: "
            f"{count}/{len(valid)}"
        )

    db_result = save_to_database(valid)

    print("\nSQLite:")
    print(
        "  Yeni kayit:",
        db_result["inserted"]
    )
    print(
        "  Guncellenen:",
        db_result["updated"]
    )
    print(
        "  Baseline bildirim:",
        db_result["baseline"]
    )

    print(
        "\nKisisel bilgiler "
        "kaydedilmedi."
    )

    # ISKI fatura gorsellerini arsivle.
    # Bu kod ayri tutuluyor; API/SQLite
    # collector mantigini etkilemez.
    print(
        "\nISKI JPG arsivi baslatiliyor..."
    )

    import runpy

    runpy.run_path(
        "/app/iski-jpg-download.py",
        run_name="__main__"
    )

    print(
        "\nISKI Telegram kontrolu..."
    )

    telegram_result = (
        send_pending_notifications()
    )

    print(
        "  Bildirim bekleyen:",
        telegram_result["pending"]
    )
    print(
        "  Gonderilen:",
        telegram_result["sent"]
    )
    print(
        "  Hata:",
        telegram_result["failed"]
    )
    print(
        "  JPG bekleyen:",
        telegram_result["waiting_jpg"]
    )


if __name__ == "__main__":
    main()
