import base64
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import websocket


CDP = "http://127.0.0.1:9222/json"

PROVIDER = "igdas"

DB_PATH = "/data/faturalar.db"

PDF_ROOT = Path("/pdfs/igdas")

LIMIT = int(
    os.environ.get(
        "IGDAS_LIMIT",
        "1"
    )
)

START = int(
    os.environ.get(
        "IGDAS_START",
        "1"
    )
)


WRITE_DB = (
    os.environ.get(
        "IGDAS_WRITE_DB",
        "0"
    ).strip().lower()
    in (
        "1",
        "true",
        "yes",
        "on"
    )
)


# ============================================================
# GENEL YARDIMCI FONKSIYONLAR
# ============================================================

def tr_float(value):
    if value is None:
        return None

    value = str(value).strip()

    if not value:
        return None

    value = value.replace("₺", "")
    value = value.replace("TL", "")
    value = value.replace(" ", "")
    value = value.replace(".", "")
    value = value.replace(",", ".")

    try:
        return float(value)
    except ValueError:
        return None


def parse_tr_date(value):
    if not value:
        return None

    value = value.strip()

    if value == "-":
        return None

    try:
        return datetime.strptime(
            value,
            "%d.%m.%Y"
        ).strftime("%Y-%m-%d")

    except ValueError:
        return None


def first_match(pattern, text, flags=0):
    match = re.search(
        pattern,
        text,
        flags
    )

    if not match:
        return None

    return match.group(1).strip()


# ============================================================
# CDP
# ============================================================

def find_igdas_page():

    pages = json.load(
        urllib.request.urlopen(
            CDP,
            timeout=10
        )
    )

    candidates = [
        p
        for p in pages
        if p.get("type") == "page"
        and "oim.igdas.com.tr"
        in p.get("url", "")
    ]

    if not candidates:
        raise RuntimeError(
            "Acik IGDAS sekmesi bulunamadi."
        )

    # Mümkünse fatura listesi sekmesini kullan.
    for page in candidates:

        if "/all_invoices" in page.get(
            "url",
            ""
        ):
            return page

    return candidates[0]


class CDPClient:

    def __init__(self, ws_url):

        self.ws = websocket.create_connection(
            ws_url,
            timeout=30
        )

        self.counter = 1

    def close(self):
        self.ws.close()

    def command(
        self,
        method,
        params=None,
        timeout=30
    ):

        msg_id = self.counter
        self.counter += 1

        self.ws.send(
            json.dumps({
                "id": msg_id,
                "method": method,
                "params": params or {}
            })
        )

        self.ws.settimeout(1)

        deadline = time.time() + timeout

        while time.time() < deadline:

            try:
                msg = json.loads(
                    self.ws.recv()
                )

            except Exception:
                continue

            if msg.get("id") != msg_id:
                continue

            if "error" in msg:

                raise RuntimeError(
                    json.dumps(
                        msg["error"],
                        ensure_ascii=False
                    )
                )

            return msg.get(
                "result",
                {}
            )

        raise TimeoutError(
            f"CDP timeout: {method}"
        )

    def evaluate(
        self,
        expression,
        await_promise=False,
        timeout=30
    ):

        result = self.command(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True
            },
            timeout=timeout
        )

        result_obj = result.get(
            "result",
            {}
        )

        if result_obj.get(
            "subtype"
        ) == "error":

            raise RuntimeError(
                result_obj.get(
                    "description",
                    "Javascript hatasi"
                )
            )

        return result_obj.get(
            "value"
        )



# ============================================================
# IGDAS / E-DEVLET OTOMATIK LOGIN
# ============================================================

def get_cdp_pages():

    return json.load(
        urllib.request.urlopen(
            CDP,
            timeout=10
        )
    )


def wait_for_page_url(
    patterns,
    timeout=60
):

    deadline = time.time() + timeout

    while time.time() < deadline:

        try:
            pages = get_cdp_pages()
        except Exception:
            time.sleep(1)
            continue

        for page in pages:

            if page.get("type") != "page":
                continue

            url = page.get("url", "")

            if any(
                pattern in url
                for pattern in patterns
            ):
                return page

        time.sleep(1)

    raise RuntimeError(
        "Beklenen sayfaya yonlendirme olmadi: "
        + ", ".join(patterns)
    )


def open_cdp_page(page):

    cdp = CDPClient(
        page["webSocketDebuggerUrl"]
    )

    cdp.command(
        "Runtime.enable"
    )

    cdp.command(
        "Page.enable"
    )

    return cdp


def igdas_logged_in(cdp):

    try:
        url = cdp.evaluate(
            "location.href"
        ) or ""

        if (
            "/dashboard" in url
            or "/contract/" in url
            or "/all_invoices" in url
        ):
            return True

        return bool(
            cdp.evaluate(
                r"""
                (() => {
                    return !!document.querySelector(
                        '.oim-header__logout'
                    );
                })()
                """
            )
        )

    except Exception:
        return False


def igdas_auto_login():

    print()
    print("=" * 70)
    print("IGDAS OTURUM KONTROLU")
    print("=" * 70)

    page = find_igdas_page()

    cdp = open_cdp_page(
        page
    )

    try:

        current = cdp.evaluate(
            "location.href"
        ) or ""

        print(
            "Mevcut URL:",
            current
        )

        if igdas_logged_in(cdp):

            print(
                "IGDAS oturumu zaten acik."
            )

            return page

        print(
            "IGDAS oturumu kapali."
        )

        # Login sayfasina git.
        if "/login" not in current:

            cdp.command(
                "Page.navigate",
                {
                    "url":
                    "https://oim.igdas.com.tr/login"
                }
            )

            time.sleep(2)

        # e-Devlet butonunu bul ve tikla.
        result = cdp.evaluate(
            r"""
            (() => {

                const buttons =
                    [...document.querySelectorAll(
                        'button'
                    )];

                const button =
                    buttons.find(b =>
                        /e-devlet/i.test(
                            (b.innerText || '').trim()
                        )
                    );

                if (!button) {
                    return {
                        ok: false,
                        reason:
                            'edevlet_button_not_found'
                    };
                }

                button.click();

                return {
                    ok: true,
                    text:
                        (button.innerText || '').trim()
                };

            })()
            """
        )

        if not result or not result.get("ok"):

            raise RuntimeError(
                "IGDAS e-Devlet giris "
                "butonu bulunamadi."
            )

        print(
            "e-Devlet girisi tiklandi."
        )

    finally:
        cdp.close()

    # --------------------------------------------------------
    # E-DEVLET LOGIN SAYFASI
    # --------------------------------------------------------

    edevlet_page = wait_for_page_url(
        [
            "giris.turkiye.gov.tr"
        ],
        timeout=30
    )

    cdp = open_cdp_page(
        edevlet_page
    )

    try:

        print(
            "e-Devlet sayfasi acildi."
        )

        tckn = os.environ.get(
            "EDEVLET_TCKN",
            ""
        ).strip()

        password = os.environ.get(
            "EDEVLET_PASSWORD",
            ""
        )

        if not tckn:
            raise RuntimeError(
                "EDEVLET_TCKN ortam degiskeni yok."
            )

        if not password:
            raise RuntimeError(
                "EDEVLET_PASSWORD ortam degiskeni yok."
            )

        # JSON ile JS stringlerine guvenli aktar.
        tckn_js = json.dumps(
            tckn
        )

        password_js = json.dumps(
            password
        )

        result = cdp.evaluate(
            f"""
            (() => {{

                const tckn =
                    document.querySelector(
                        '#tridField'
                    );

                const password =
                    document.querySelector(
                        '#egpField'
                    );

                if (!tckn || !password) {{
                    return {{
                        ok: false,
                        reason:
                            'login_fields_not_found'
                    }};
                }}

                const setValue =
                    (element, value) => {{

                    const setter =
                        Object.getOwnPropertyDescriptor(
                            HTMLInputElement.prototype,
                            'value'
                        ).set;

                    setter.call(
                        element,
                        value
                    );

                    element.dispatchEvent(
                        new Event(
                            'input',
                            {{
                                bubbles: true
                            }}
                        )
                    );

                    element.dispatchEvent(
                        new Event(
                            'change',
                            {{
                                bubbles: true
                            }}
                        )
                    );
                }};

                setValue(
                    tckn,
                    {tckn_js}
                );

                setValue(
                    password,
                    {password_js}
                );

                const buttons =
                    [...document.querySelectorAll(
                        'button,input[type="submit"]'
                    )];

                const submit =
                    buttons.find(x =>
                        /giriş yap|giris yap/i.test(
                            (
                                x.innerText
                                || x.value
                                || ''
                            ).trim()
                        )
                    );

                if (!submit) {{
                    return {{
                        ok: false,
                        reason:
                            'login_button_not_found'
                    }};
                }}

                submit.click();

                return {{
                    ok: true
                }};

            }})()
            """
        )

        if not result or not result.get("ok"):

            raise RuntimeError(
                "e-Devlet login formu "
                "otomatik gonderilemedi: "
                + str(result)
            )

        print(
            "e-Devlet kimlik bilgileri "
            "gonderildi."
        )

    finally:
        cdp.close()

    # --------------------------------------------------------
    # OAUTH ONAY EKRANI
    # --------------------------------------------------------

    oauth_page = wait_for_page_url(
        [
            "OAuth2AuthorizationServer/"
            "AuthorizationController"
        ],
        timeout=60
    )

    cdp = open_cdp_page(
        oauth_page
    )

    try:

        print(
            "e-Devlet IGDAS izin ekrani acildi."
        )

        result = cdp.evaluate(
            r"""
            (() => {

                const buttons =
                    [...document.querySelectorAll(
                        'button,input[type="submit"]'
                    )];

                const button =
                    buttons.find(x =>
                        /^onayla$/i.test(
                            (
                                x.innerText
                                || x.value
                                || ''
                            ).trim()
                        )
                    );

                if (!button) {
                    return {
                        ok: false,
                        reason:
                            'approve_button_not_found'
                    };
                }

                button.click();

                return {
                    ok: true
                };

            })()
            """
        )

        if not result or not result.get("ok"):

            raise RuntimeError(
                "e-Devlet Onayla butonu "
                "bulunamadi."
            )

        print(
            "e-Devlet Onayla tiklandi."
        )

    finally:
        cdp.close()

    # --------------------------------------------------------
    # IGDAS DONUSU
    # --------------------------------------------------------

    igdas_page = wait_for_page_url(
        [
            "oim.igdas.com.tr/dashboard",
            "oim.igdas.com.tr/contract/"
        ],
        timeout=60
    )

    print(
        "IGDAS login basarili."
    )

    print(
        "URL:",
        igdas_page.get(
            "url",
            ""
        )
    )

    return igdas_page


def ensure_igdas_contract_page(cdp):

    current = cdp.evaluate(
        "location.href"
    ) or ""

    # Zaten contractId varsa hicbir sey yapma.
    contract_id = cdp.evaluate(
        r"""
        (() => {
            const u =
                new URL(location.href);

            return (
                u.searchParams.get(
                    'contractId'
                )
                || ''
            );
        })()
        """
    )

    if contract_id:
        return contract_id

    # Dashboard tam yuklensin.
    deadline = time.time() + 30

    while time.time() < deadline:

        contract_id = cdp.evaluate(
            r"""
            (() => {

                const links =
                    [...document.querySelectorAll(
                        'a[href]'
                    )];

                for (const a of links) {

                    const href =
                        a.href || '';

                    if (
                        !href.includes(
                            '/contract/detail'
                        )
                    ) {
                        continue;
                    }

                    try {

                        const u =
                            new URL(href);

                        const id =
                            u.searchParams.get(
                                'contractId'
                            );

                        if (id) {
                            return id;
                        }

                    } catch (_) {}
                }

                return '';

            })()
            """
        )

        if contract_id:
            break

        time.sleep(1)

    if not contract_id:

        raise RuntimeError(
            "IGDAS dashboard uzerinden "
            "contractId bulunamadi."
        )

    print(
        "Contract ID otomatik bulundu:",
        contract_id
    )

    target = (
        "https://oim.igdas.com.tr/"
        "all_invoices"
        f"?contractId={contract_id}"
        "&tab=detay"
    )

    print(
        "Fatura listesine gidiliyor:"
    )

    print(
        target
    )

    cdp.command(
        "Page.navigate",
        {
            "url": target
        }
    )

    return contract_id



# ============================================================
# FATURA LISTESI
# ============================================================

def ensure_invoice_page(cdp):

    current = cdp.evaluate(
        "location.href"
    )

    # --------------------------------------------------------
    # Contract ID
    # --------------------------------------------------------

    contract_id = cdp.evaluate(
        r"""
        (() => {
            const u =
                new URL(location.href);

            return (
                u.searchParams.get(
                    'contractId'
                )
                || ''
            );
        })()
        """
    )

    if not contract_id:

        raise RuntimeError(
            "contractId bulunamadi."
        )

    # --------------------------------------------------------
    # Gerekirse fatura listesine git
    # --------------------------------------------------------

    if "/all_invoices" not in current:

        target = (
            "https://oim.igdas.com.tr/"
            "all_invoices"
            f"?contractId={contract_id}"
            "&tab=detay"
        )

        print(
            "Fatura listesine gidiliyor:"
        )
        print(target)

        cdp.command(
            "Page.navigate",
            {
                "url": target
            }
        )

    # --------------------------------------------------------
    # React tablosunun GERCEK faturalarla dolmasini bekle
    #
    # Sadece <tr> bulunmasi yeterli degil.
    # IGDAS yukleme sirasinda gecici olarak:
    #
    # "Güncel ödenmemiş faturanız bulunmamaktadır"
    #
    # satirini gosterebiliyor.
    #
    # Bu nedenle gercek a.link + fatura numarasi bekleniyor.
    # --------------------------------------------------------

    deadline = time.time() + 45

    while time.time() < deadline:

        ready = cdp.evaluate(
            r"""
            (() => {

                if (
                    document.readyState
                    !== 'complete'
                ) {
                    return false;
                }

                const tables =
                    [...document.querySelectorAll(
                        'table'
                    )];

                const table =
                    tables.find(t => {

                        const headers =
                            [...t.querySelectorAll(
                                'th'
                            )]
                            .map(x =>
                                (x.innerText || '')
                                .trim()
                            );

                        return (
                            headers.includes(
                                'Fatura / No'
                            )
                            &&
                            headers.includes(
                                'Tüketim'
                            )
                            &&
                            headers.includes(
                                'Fatura Tutarı'
                            )
                        );
                    });

                if (!table) {
                    return false;
                }

                const links =
                    [...table.querySelectorAll(
                        'tbody tr td a.link'
                    )];

                return links.some(a => {

                    const text =
                        (a.innerText || '')
                        .trim();

                    return (
                        /^\d+F$/.test(text)
                    );
                });

            })()
            """
        )

        if ready:
            return

        time.sleep(1)

    raise RuntimeError(
        "IGDAS fatura listesi "
        "gercek faturalarla "
        "hazir hale gelmedi."
    )


def read_invoice_rows(cdp):

    expression = r"""
    (() => {

        const tables =
            [...document.querySelectorAll(
                'table'
            )];

        const table = tables.find(t => {

            const h =
                [...t.querySelectorAll(
                    'th'
                )]
                .map(x =>
                    (x.innerText || '')
                    .trim()
                );

            return (
                h.includes('Fatura / No')
                &&
                h.includes('Tüketim')
                &&
                h.includes(
                    'Fatura Tutarı'
                )
            );
        });

        if (!table) {
            return [];
        }

        return [
            ...table.querySelectorAll(
                'tbody tr'
            )
        ].map(tr => {

            const cells =
                [...tr.querySelectorAll(
                    'td'
                )]
                .map(td =>
                    (td.innerText || '')
                    .trim()
                );

            const link =
                tr.querySelector(
                    'td a.link'
                );

            return {
                bill_no:
                    cells[0] || null,

                payment_channel:
                    cells[1] || null,

                consumption_m3:
                    cells[2] || null,

                amount_tl:
                    cells[3] || null,

                payment_date:
                    cells[4] || null,

                due_date:
                    cells[5] || null,

                action:
                    cells[6] || null,

                has_link:
                    !!link
            };
        });

    })()
    """

    rows = cdp.evaluate(
        expression
    )

    if not rows:
        raise RuntimeError(
            "Fatura satiri bulunamadi."
        )

    # React sayfasi yuklenirken gecici olarak
    # 'Guncel odenmemis faturanız bulunmamaktadir'
    # benzeri bir satir gosterebiliyor.
    # Sadece gercek IGDAS fatura numaralarini kabul et.
    rows = [
        row
        for row in rows
        if (
            row.get("has_link")
            and re.fullmatch(
                r"[0-9]+F",
                str(
                    row.get("bill_no")
                    or ""
                ).strip()
            )
        )
    ]

    if not rows:
        raise RuntimeError(
            "Gercek fatura satiri bulunamadi."
        )

    return rows


# ============================================================
# IGDAS API / PDF
# ============================================================

def get_session_info(cdp):

    info = cdp.evaluate(
        r"""
        (() => ({
            token:
                sessionStorage.getItem(
                    'token'
                ),

            customerNo:
                sessionStorage.getItem(
                    'customerNo'
                ),

            contractId:
                new URL(location.href)
                .searchParams.get(
                    'contractId'
                )
        }))()
        """
    )

    if not info:
        raise RuntimeError(
            "IGDAS session bilgisi "
            "okunamadi."
        )

    if not info.get("token"):
        raise RuntimeError(
            "IGDAS session token yok."
        )

    if not info.get("customerNo"):
        raise RuntimeError(
            "IGDAS customerNo yok."
        )

    if not info.get("contractId"):
        raise RuntimeError(
            "IGDAS contractId yok."
        )

    return info


def fetch_invoice_pdf(
    cdp,
    customer_no,
    contract_no,
    document_no
):

    # --------------------------------------------------------
    # IGDAS PDF alma yöntemi
    #
    # API çağrısını kendimiz üretmiyoruz.
    # IGDAS React uygulamasındaki gerçek fatura linkine
    # tıklıyoruz.
    #
    # Böylece IGDAS kendi güncel Authorization bilgisini
    # kullanıyor.
    #
    # Oluşan GetContractDocument POST isteğinin response'u
    # Chrome DevTools Protocol üzerinden yakalanıyor.
    # --------------------------------------------------------

    target_api = (
        "GetContractDocument"
    )

    # Network eventlerini aç.
    cdp.command(
        "Network.enable"
    )

    # --------------------------------------------------------
    # Fatura linkini bul ve React click oluştur.
    # --------------------------------------------------------

    expression = f"""
    (() => {{

        const links =
            [...document.querySelectorAll(
                'table a.link'
            )];

        const link =
            links.find(a =>
                (a.innerText || '').trim()
                === {json.dumps(document_no)}
            );

        if (!link) {{

            return {{
                ok: false,
                error:
                    'Fatura linki bulunamadi: '
                    + {json.dumps(document_no)}
            }};
        }}

        link.scrollIntoView({{
            block: 'center'
        }});

        link.click();

        return {{
            ok: true
        }};

    }})()
    """

    click_result = cdp.evaluate(
        expression
    )

    if not click_result:
        raise RuntimeError(
            "IGDAS click sonucu bos."
        )

    if not click_result.get("ok"):
        raise RuntimeError(
            click_result.get(
                "error",
                "IGDAS fatura linki "
                "tiklanamadi."
            )
        )

    # --------------------------------------------------------
    # React'in oluşturduğu gerçek POST request'ini yakala.
    # --------------------------------------------------------

    request_id = None
    response_status = None

    deadline = time.time() + 30

    while time.time() < deadline:

        cdp.ws.settimeout(1)

        try:
            message = json.loads(
                cdp.ws.recv()
            )

        except Exception:
            continue

        method = message.get(
            "method"
        )

        params = message.get(
            "params",
            {}
        )

        # ----------------------------------------------------
        # Request
        # ----------------------------------------------------

        if (
            method
            == "Network.requestWillBeSent"
        ):

            request = params.get(
                "request",
                {}
            )

            url = request.get(
                "url",
                ""
            )

            http_method = request.get(
                "method",
                ""
            )

            if target_api not in url:
                continue

            # CORS preflight
            if http_method == "OPTIONS":
                continue

            if http_method != "POST":
                continue

            post_data = request.get(
                "postData",
                ""
            )

            # Aynı anda başka bir fatura request'i
            # oluşursa yanlış response'u alma.
            if document_no not in post_data:
                continue

            request_id = params.get(
                "requestId"
            )

            continue

        # ----------------------------------------------------
        # Response
        # ----------------------------------------------------

        if (
            method
            == "Network.responseReceived"
            and request_id
            and params.get("requestId")
            == request_id
        ):

            response = params.get(
                "response",
                {}
            )

            response_status = response.get(
                "status"
            )

            continue

        # ----------------------------------------------------
        # Response tamamen geldi.
        # ----------------------------------------------------

        if (
            method
            == "Network.loadingFinished"
            and request_id
            and params.get("requestId")
            == request_id
        ):

            body_result = cdp.command(
                "Network.getResponseBody",
                {
                    "requestId":
                        request_id
                },
                timeout=15
            )

            body = body_result.get(
                "body",
                ""
            )

            if body_result.get(
                "base64Encoded"
            ):

                body = base64.b64decode(
                    body
                ).decode(
                    "utf-8",
                    errors="replace"
                )

            if response_status != 200:

                raise RuntimeError(
                    "IGDAS PDF HTTP hatasi: "
                    + str(response_status)
                )

            try:

                data = json.loads(
                    body
                )

            except Exception as exc:

                raise RuntimeError(
                    "IGDAS PDF JSON parse "
                    "hatasi: "
                    + str(exc)
                )

            encoded = data.get(
                "outContractDocument"
            )

            if not encoded:

                raise RuntimeError(
                    "outContractDocument bos."
                )

            try:

                pdf = base64.b64decode(
                    encoded
                )

            except Exception as exc:

                raise RuntimeError(
                    "IGDAS PDF base64 "
                    "decode hatasi: "
                    + str(exc)
                )

            if not pdf.startswith(
                b"%PDF"
            ):

                raise RuntimeError(
                    "Gelen belge PDF degil."
                )

            return pdf

    if not request_id:

        raise RuntimeError(
            "IGDAS React click sonrasi "
            "GetContractDocument POST "
            "yakalanamadi."
        )

    raise RuntimeError(
        "IGDAS GetContractDocument "
        "response tamamlanamadi."
    )


# ============================================================
# PDF TEXT
# ============================================================

def pdf_to_text(pdf_path):

    try:
        result = subprocess.run(
            [
                "pdftotext",
                "-layout",
                str(pdf_path),
                "-"
            ],
            check=True,
            capture_output=True,
            text=True,
            errors="replace"
        )

    except FileNotFoundError:

        raise RuntimeError(
            "pdftotext collector "
            "containerinda kurulu degil."
        )

    return result.stdout


# ============================================================
# PDF PARSER
# ============================================================

def parse_invoice_pdf(text):

    data = {}

    data["invoice_date"] = (
        parse_tr_date(
            first_match(
                r"Fatura Tarihi\s+"
                r"(\d{2}\.\d{2}\.\d{4})",
                text
            )
        )
    )

    data["bill_no"] = first_match(
        r"Fatura Numarası\s+"
        r"([A-Z0-9]+)",
        text
    )

    reading_days = first_match(
        r"Fatura Gün Sayısı\s+"
        r"(\d+)",
        text
    )

    data["reading_days"] = (
        int(reading_days)
        if reading_days
        else None
    )

    data["consumption_m3"] = (
        tr_float(
            first_match(
                r"Sayaçtan Ölçülen "
                r"Hacim\(m³\)\s+"
                r"([\d.,]+)",
                text
            )
        )
    )

    data["consumption_kwh"] = (
        tr_float(
            first_match(
                r"Tüketilen Enerji "
                r"Miktari \(kwh\)\s+"
                r"([\d.,]+)",
                text,
                re.I
            )
        )
    )

    data["correction_factor"] = (
        tr_float(
            first_match(
                r"Düzeltme Katsayısı\s+"
                r"([\d.,]+)",
                text
            )
        )
    )

    data["calorific_value"] = (
        tr_float(
            first_match(
                r"Ort\.\s*Fiili\s+"
                r"Üst\s+Isil\s+Deger"
                r"\(kwh/m³\)\s+"
                r"([\d.,]+)",
                text,
                re.I
            )
        )
    )

    data["unit_price"] = (
        tr_float(
            first_match(
                r"Tük\.Dön\.Per\.Sts\.Fiy\."
                r"\(TL/kwh\)\s+"
                r"([\d.,]+)",
                text,
                re.I
            )
        )
    )

    data["consumption_charge_tl"] = (
        tr_float(
            first_match(
                r"Toplam Tüketim Bedeli\s+"
                r"([\d.,]+)",
                text
            )
        )
    )

    data["other_charge_tl"] = (
        tr_float(
            first_match(
                r"Diger Bedeller\s+"
                r"([\d.,]+)",
                text,
                re.I
            )
        )
    )

    data["vat_tl"] = (
        tr_float(
            first_match(
                r"KDV\s*%20\s+"
                r"([\d.,]+)",
                text,
                re.I
            )
        )
    )

    data["invoice_amount_exact"] = (
        tr_float(
            first_match(
                r"Fatura Tutarı\s+"
                r"([\d.,]+)",
                text
            )
        )
    )

    data["state_support_tl"] = (
        tr_float(
            first_match(
                r"([\d.,]+)\s*TL'lik "
                r"devlet desteği",
                text,
                re.I
            )
        )
    )

    # Okuma tarihleri / endeksler.
    #
    # Örnek sayaç satırı biçimi:
    # GG.AA.YYYY   ENDEKS   SAYAC_NO
    # GG.AA.YYYY   ENDEKS   SAYAC_NO

    meter_rows = re.findall(
        r"^\s*"
        r"(\d{2}\.\d{2}\.\d{4})"
        r"\s+"
        r"([\d.,]+)"
        r"\s+"
        r"\d+"
        r"\s*$",
        text,
        re.M
    )

    if len(meter_rows) >= 2:

        data["first_read_date"] = (
            parse_tr_date(
                meter_rows[0][0]
            )
        )

        data["first_index"] = (
            tr_float(
                meter_rows[0][1]
            )
        )

        data["last_read_date"] = (
            parse_tr_date(
                meter_rows[1][0]
            )
        )

        data["last_index"] = (
            tr_float(
                meter_rows[1][1]
            )
        )

    else:

        data["first_read_date"] = None
        data["first_index"] = None
        data["last_read_date"] = None
        data["last_index"] = None

    if data["invoice_date"]:

        dt = datetime.strptime(
            data["invoice_date"],
            "%Y-%m-%d"
        )

        data["period"] = (
            f"{dt.year:04d}"
            f"{dt.month:02d}"
        )

    else:
        data["period"] = None

    return data


# ============================================================
# DATABASE
# ============================================================

def save_invoice_to_db(
    parsed,
    row,
    pdf_path
):

    now = datetime.now().astimezone().isoformat(
        timespec="seconds"
    )

    bill_no = (
        parsed.get("bill_no")
        or row.get("bill_no")
    )

    if not bill_no:
        raise RuntimeError(
            "DB kaydi icin bill_no yok."
        )

    # IGDAS icin fatura numarasi kalici ve benzersiz
    # bill_id olarak kullaniliyor.
    bill_id = bill_no

    invoice_date = parsed.get(
        "invoice_date"
    )

    due_date = parse_tr_date(
        row.get("due_date")
    )

    payment_date = parse_tr_date(
        row.get("payment_date")
    )

    paid = (
        row.get("payment_date")
        not in (
            None,
            "",
            "-"
        )
    )

    payment_status = (
        "paid"
        if paid
        else "unpaid"
    )

    amount_tl = parsed.get(
        "invoice_amount_exact"
    )

    if amount_tl is None:
        amount_tl = tr_float(
            row.get("amount_tl")
        )

    consumption_m3 = parsed.get(
        "consumption_m3"
    )

    if consumption_m3 is None:
        consumption_m3 = tr_float(
            row.get("consumption_m3")
        )

    reading_days = parsed.get(
        "reading_days"
    )

    daily_m3 = None

    if (
        consumption_m3 is not None
        and reading_days
        and reading_days > 0
    ):
        daily_m3 = (
            consumption_m3
            / reading_days
        )

    period = parsed.get(
        "period"
    )

    if period:
        period = str(period)

        if (
            len(period) == 6
            and period.isdigit()
        ):
            period = (
                period[4:6]
                + "-"
                + period[0:4]
            )

    con = sqlite3.connect(
        DB_PATH
    )

    try:

        existing = con.execute(
            """
            SELECT id
            FROM invoices
            WHERE provider = ?
              AND bill_id = ?
            """,
            (
                PROVIDER,
                bill_id
            )
        ).fetchone()

        is_new = existing is None

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
                payment_status,
                payment_date,
                reading_days,
                consumption_kwh,
                daily_kwh,
                first_index,
                last_index,
                first_read_date,
                last_read_date,
                pdf_path,
                collected_at,
                updated_at,
                consumption_m3,
                daily_m3,
                vat_tl,
                correction_factor,
                calorific_value,
                unit_price,
                consumption_charge_tl,
                other_charge_tl,
                state_support_tl
            )
            VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?, ?, ?, ?, ?
            )

            ON CONFLICT(provider, bill_id)
            DO UPDATE SET
                bill_no = excluded.bill_no,
                period = excluded.period,
                invoice_date = excluded.invoice_date,
                due_date = excluded.due_date,
                amount_tl = excluded.amount_tl,
                payment_status = excluded.payment_status,
                payment_date = excluded.payment_date,
                reading_days = excluded.reading_days,
                consumption_kwh = excluded.consumption_kwh,
                daily_kwh = excluded.daily_kwh,
                first_index = excluded.first_index,
                last_index = excluded.last_index,
                first_read_date = excluded.first_read_date,
                last_read_date = excluded.last_read_date,
                pdf_path = excluded.pdf_path,
                updated_at = excluded.updated_at,
                consumption_m3 = excluded.consumption_m3,
                daily_m3 = excluded.daily_m3,
                vat_tl = excluded.vat_tl,
                correction_factor = excluded.correction_factor,
                calorific_value = excluded.calorific_value,
                unit_price = excluded.unit_price,
                consumption_charge_tl = excluded.consumption_charge_tl,
                other_charge_tl = excluded.other_charge_tl,
                state_support_tl = excluded.state_support_tl
            """,
            (
                PROVIDER,
                bill_id,
                bill_no,
                period,
                invoice_date,
                due_date,
                amount_tl,
                payment_status,
                payment_date,
                reading_days,
                parsed.get("consumption_kwh"),
                (
                    parsed.get("consumption_kwh")
                    / reading_days
                    if (
                        parsed.get("consumption_kwh")
                        is not None
                        and reading_days
                        and reading_days > 0
                    )
                    else None
                ),
                parsed.get("first_index"),
                parsed.get("last_index"),
                parsed.get("first_read_date"),
                parsed.get("last_read_date"),
                str(pdf_path),
                now,
                now,
                consumption_m3,
                daily_m3,
                parsed.get("vat_tl"),
                parsed.get("correction_factor"),
                parsed.get("calorific_value"),
                parsed.get("unit_price"),
                parsed.get("consumption_charge_tl"),
                parsed.get("other_charge_tl"),
                parsed.get("state_support_tl")
            )
        )

        con.commit()

        db_row = con.execute(
            """
            SELECT
                id,
                provider,
                bill_id,
                bill_no,
                period,
                invoice_date,
                due_date,
                amount_tl,
                payment_status,
                payment_date,
                reading_days,
                consumption_kwh,
                consumption_m3,
                daily_m3,
                vat_tl,
                pdf_path
            FROM invoices
            WHERE provider = ?
              AND bill_id = ?
            """,
            (
                PROVIDER,
                bill_id
            )
        ).fetchone()

        return {
            "is_new": is_new,
            "row": db_row
        }

    finally:
        con.close()



# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 70)
    print("IGDAS COLLECTOR - TEST MODU")
    print("=" * 70)
    print(
        "Limit:",
        LIMIT
    )

    page = igdas_auto_login()

    print(
        "Sekme:",
        page.get("title")
    )

    print(
        "URL  :",
        page.get("url")
    )

    cdp = CDPClient(
        page[
            "webSocketDebuggerUrl"
        ]
    )

    try:

        cdp.command(
            "Runtime.enable"
        )

        cdp.command(
            "Page.enable"
        )

        ensure_igdas_contract_page(
            cdp
        )

        ensure_invoice_page(
            cdp
        )

        rows = read_invoice_rows(
            cdp
        )

        session = get_session_info(
            cdp
        )

        print()
        print(
            "Toplam fatura:",
            len(rows)
        )

        print(
            "CustomerNo   :",
            session["customerNo"]
        )

        print(
            "ContractNo   :",
            session["contractId"]
        )

        start_index = max(
            START - 1,
            0
        )

        end_index = min(
            start_index + LIMIT,
            len(rows)
        )

        selected = rows[
            start_index:end_index
        ]

        for index, row in enumerate(
            selected,
            start_index + 1
        ):

            bill_no = row.get(
                "bill_no"
            )

            if not bill_no:
                continue

            print()
            print("=" * 70)
            print(
                f"FATURA {index}/{len(rows)}"
            )
            print("=" * 70)

            print(
                "Fatura No    :",
                bill_no
            )

            print(
                "Liste m3     :",
                row.get(
                    "consumption_m3"
                )
            )

            print(
                "Liste tutar  :",
                row.get(
                    "amount_tl"
                )
            )

            print(
                "Odeme tarihi :",
                row.get(
                    "payment_date"
                )
            )

            print(
                "Son odeme    :",
                row.get(
                    "due_date"
                )
            )

            # Her PDF tiklamasi IGDAS'i belge sayfasina
            # goturebildigi icin sonraki faturadan once
            # fatura listesinin tekrar hazir oldugundan
            # emin ol.
            page_ready = False
            page_error = None

            for page_attempt in range(1, 4):

                try:

                    ensure_invoice_page(
                        cdp
                    )

                    page_ready = True
                    page_error = None
                    break

                except Exception as exc:

                    page_error = exc

                    print(
                        f"Sayfa deneme "
                        f"{page_attempt}/3 "
                        f"basarisiz: "
                        f"{exc}"
                    )

                    if page_attempt < 3:

                        # React sayfasina biraz zaman ver.
                        time.sleep(3)

            if not page_ready:

                print(
                    "FATURA ATLANDI      :",
                    bill_no
                )

                print(
                    "Son sayfa hatasi    :",
                    str(page_error)
                )

                continue

            pdf = None
            pdf_error = None

            for attempt in range(1, 4):

                try:

                    if attempt > 1:

                        print(
                            f"PDF tekrar deneme : "
                            f"{attempt}/3"
                        )

                        # Onceki click belge sayfasina
                        # goturmus olabilir.
                        ensure_invoice_page(
                            cdp
                        )

                        # React / Network tarafinin
                        # sakinlesmesi icin kisa bekleme.
                        time.sleep(2)

                    pdf = fetch_invoice_pdf(
                        cdp,
                        session[
                            "customerNo"
                        ],
                        session[
                            "contractId"
                        ],
                        bill_no
                    )

                    pdf_error = None
                    break

                except Exception as exc:

                    pdf_error = exc

                    print(
                        f"PDF deneme "
                        f"{attempt}/3 "
                        f"basarisiz: "
                        f"{exc}"
                    )

                    if attempt < 3:
                        time.sleep(2)

            if pdf is None:

                print(
                    "FATURA ATLANDI      :",
                    bill_no
                )

                print(
                    "Son PDF hatasi      :",
                    str(pdf_error)
                )

                continue

            print(
                "PDF          :",
                len(pdf),
                "byte"
            )

            # PDF once gecici olarak yazilir.
            # Fatura tarihi PDF icinden parse edildikten
            # sonra yil bazli kalici arsive tasinir.

            temp_dir = (
                PDF_ROOT
                / ".tmp"
            )

            temp_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            temp_pdf = (
                temp_dir
                / f"{bill_no}.pdf"
            )

            temp_pdf.write_bytes(
                pdf
            )

            text = pdf_to_text(
                temp_pdf
            )

            parsed = parse_invoice_pdf(
                text
            )

            invoice_date = parsed.get(
                "invoice_date"
            )

            if not invoice_date:
                raise RuntimeError(
                    "Kalici PDF arsivi icin "
                    "invoice_date bulunamadi: "
                    f"{bill_no}"
                )

            try:
                invoice_year = datetime.strptime(
                    invoice_date,
                    "%Y-%m-%d"
                ).year
            except ValueError as exc:
                raise RuntimeError(
                    "Gecersiz invoice_date: "
                    f"{invoice_date}"
                ) from exc

            archive_dir = (
                PDF_ROOT
                / str(invoice_year)
            )

            archive_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            archive_pdf = (
                archive_dir
                / f"{bill_no}.pdf"
            )

            temp_pdf.replace(
                archive_pdf
            )

            print(
                "PDF yolu     :",
                archive_pdf
            )

            print()
            print(
                "PARSE EDILEN VERILER"
            )
            print("-" * 70)

            for key, value in (
                parsed.items()
            ):
                print(
                    f"{key:24}: "
                    f"{value}"
                )

            print()
            print(
                "LISTE VERILERI"
            )
            print("-" * 70)

            print(
                "due_date                :",
                parse_tr_date(
                    row.get(
                        "due_date"
                    )
                )
            )

            print(
                "payment_date            :",
                parse_tr_date(
                    row.get(
                        "payment_date"
                    )
                )
            )

            print(
                "amount_tl_list          :",
                tr_float(
                    row.get(
                        "amount_tl"
                    )
                )
            )

            print(
                "consumption_m3_list     :",
                tr_float(
                    row.get(
                        "consumption_m3"
                    )
                )
            )

            paid = (
                row.get(
                    "payment_date"
                )
                not in (
                    None,
                    "",
                    "-"
                )
            )

            print(
                "payment_status          :",
                "paid"
                if paid
                else "unpaid"
            )


            if WRITE_DB:

                db_result = save_invoice_to_db(
                    parsed,
                    row,
                    archive_pdf
                )

                print()
                print(
                    "DB KAYDI"
                )
                print("-" * 70)

                print(
                    "Durum                  :",
                    "YENI"
                    if db_result["is_new"]
                    else "GUNCELLENDI"
                )

                db_row = db_result["row"]

                if db_row:
                    print(
                        "DB ID                  :",
                        db_row[0]
                    )
                    print(
                        "Provider               :",
                        db_row[1]
                    )
                    print(
                        "Bill ID                :",
                        db_row[2]
                    )
                    print(
                        "Fatura No              :",
                        db_row[3]
                    )
                    print(
                        "Donem                  :",
                        db_row[4]
                    )
                    print(
                        "Tutar                  :",
                        db_row[7]
                    )
                    print(
                        "Durum                  :",
                        db_row[8]
                    )
                    print(
                        "Tuketim m3             :",
                        db_row[12]
                    )

            else:

                print()
                print(
                    "DB yazma                : KAPALI"
                )

        print()
        print("=" * 70)
        print("TEST TAMAMLANDI")
        print("=" * 70)
        if WRITE_DB:
            print(
                "DB yazma modu: AKTIF"
            )
        else:
            print(
                "DB'ye herhangi bir "
                "kayit yazilmadi."
            )

    finally:
        cdp.close()


if __name__ == "__main__":

    try:
        main()

    except Exception as exc:

        print(
            "HATA:",
            str(exc),
            file=sys.stderr
        )

        sys.exit(1)
