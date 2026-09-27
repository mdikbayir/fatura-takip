from flask import Flask, render_template_string, send_file, abort
import os
import sqlite3

app = Flask(__name__)

DB_PATH = "/data/faturalar.db"
PDF_ROOT = "/pdfs"


def get_db():
    conn = sqlite3.connect(
        f"file:{DB_PATH}?mode=ro",
        uri=True
    )
    conn.row_factory = sqlite3.Row
    return conn



def tr_date(value):
    if not value:
        return "-"

    try:
        year, month, day = value.split("-")
        return f"{day}.{month}.{year}"
    except Exception:
        return value


def payment_display(invoice):
    status = invoice.get("status_code")

    # CK'de mevcut/açık faturada P görüyoruz.
    if status == "P":
        return "Ödenecek"

    # Geçmiş kapanmış kayıtlarda X ve gerçek ödeme tarihi mevcut.
    if status == "X" and invoice.get("payment_date"):
        return "Ödendi"

    return "-"


def tr_period(period):
    if not period or "-" not in period:
        return period or "-"

    month, year = period.split("-", 1)

    months = {
        "01": "Ocak",
        "02": "Şubat",
        "03": "Mart",
        "04": "Nisan",
        "05": "Mayıs",
        "06": "Haziran",
        "07": "Temmuz",
        "08": "Ağustos",
        "09": "Eylül",
        "10": "Ekim",
        "11": "Kasım",
        "12": "Aralık",
    }

    return f"{months.get(month, month)} {year}"


@app.route("/")
def index():
    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM invoices
        WHERE provider = 'ck-bogazici'
        ORDER BY invoice_date DESC
        LIMIT 12
    """).fetchall()

    conn.close()

    invoices = [dict(r) for r in rows]

    for invoice in invoices:
        invoice["period_text"] = tr_period(
            invoice.get("period")
        )

        invoice["due_date_text"] = tr_date(
            invoice.get("due_date")
        )

        invoice["payment_date_text"] = tr_date(
            invoice.get("payment_date")
        )

        invoice["payment_display"] = payment_display(
            invoice
        )

    total_kwh = sum(
        x.get("consumption_kwh") or 0
        for x in invoices
    )

    total_tl = sum(
        x.get("amount_tl") or 0
        for x in invoices
    )

    avg_kwh = (
        total_kwh / len(invoices)
        if invoices else 0
    )

    avg_tl = (
        total_tl / len(invoices)
        if invoices else 0
    )

    latest = invoices[0] if invoices else None
    previous = invoices[1] if len(invoices) > 1 else None

    consumption_change = None
    amount_change = None
    cost_per_kwh = None

    if latest:
        consumption = latest.get("consumption_kwh") or 0
        amount = latest.get("amount_tl") or 0

        if consumption > 0:
            cost_per_kwh = amount / consumption

    if latest and previous:
        current_kwh = latest.get("consumption_kwh") or 0
        previous_kwh = previous.get("consumption_kwh") or 0

        current_amount = latest.get("amount_tl") or 0
        previous_amount = previous.get("amount_tl") or 0

        if previous_kwh > 0:
            consumption_change = (
                (current_kwh - previous_kwh)
                / previous_kwh * 100
            )

        if previous_amount > 0:
            amount_change = (
                (current_amount - previous_amount)
                / previous_amount * 100
            )

    # Grafik için eskiden yeniye.
    chart = list(reversed(invoices))

    return render_template_string(
        TEMPLATE,
        invoices=invoices,
        latest=latest,
        total_kwh=total_kwh,
        total_tl=total_tl,
        avg_kwh=avg_kwh,
        avg_tl=avg_tl,
        consumption_change=consumption_change,
        amount_change=amount_change,
        cost_per_kwh=cost_per_kwh,
        chart=chart
    )



@app.route("/su")
def water():
    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM invoices
        WHERE provider = 'iski'
        ORDER BY invoice_date DESC
        LIMIT 12
    """).fetchall()

    conn.close()

    invoices = [
        dict(r)
        for r in rows
    ]

    for invoice in invoices:
        period = (
            invoice.get("period")
            or ""
        )

        # ISKI donemi 202609 biciminde.
        if (
            len(period) == 6
            and period.isdigit()
        ):
            invoice["period_text"] = (
                tr_period(
                    period[4:6]
                    + "-"
                    + period[0:4]
                )
            )
        else:
            invoice["period_text"] = (
                period or "-"
            )

        invoice["due_date_text"] = tr_date(
            invoice.get("due_date")
        )

        invoice["first_read_date_text"] = (
            tr_date(
                invoice.get(
                    "first_read_date"
                )
            )
        )

        invoice["last_read_date_text"] = (
            tr_date(
                invoice.get(
                    "last_read_date"
                )
            )
        )

        payment_status = (
            invoice.get("payment_status")
            or ""
        )

        if payment_status == "paid_estimated":
            invoice["payment_status_text"] = (
                "🟢 Ödendi"
            )
            invoice["payment_status_note"] = (
                "tahmini"
            )

        elif payment_status == "unpaid_estimated":
            invoice["payment_status_text"] = (
                "🔴 Ödenmedi"
            )
            invoice["payment_status_note"] = (
                "tahmini"
            )

        elif payment_status == "pending":
            invoice["payment_status_text"] = (
                "🟡 Bekliyor"
            )
            invoice["payment_status_note"] = (
                ""
            )

        else:
            invoice["payment_status_text"] = (
                "⚪ Bilinmiyor"
            )
            invoice["payment_status_note"] = (
                ""
            )

    total_m3 = sum(
        x.get("consumption_m3") or 0
        for x in invoices
    )

    total_tl = sum(
        x.get("amount_tl") or 0
        for x in invoices
    )

    avg_m3 = (
        total_m3 / len(invoices)
        if invoices else 0
    )

    avg_tl = (
        total_tl / len(invoices)
        if invoices else 0
    )

    latest = (
        invoices[0]
        if invoices else None
    )

    previous = (
        invoices[1]
        if len(invoices) > 1
        else None
    )

    consumption_change = None
    amount_change = None
    cost_per_m3 = None

    if latest:
        consumption = (
            latest.get(
                "consumption_m3"
            )
            or 0
        )

        amount = (
            latest.get("amount_tl")
            or 0
        )

        if consumption > 0:
            cost_per_m3 = (
                amount / consumption
            )

    if latest and previous:
        current_m3 = (
            latest.get(
                "consumption_m3"
            )
            or 0
        )

        previous_m3 = (
            previous.get(
                "consumption_m3"
            )
            or 0
        )

        current_amount = (
            latest.get("amount_tl")
            or 0
        )

        previous_amount = (
            previous.get("amount_tl")
            or 0
        )

        if previous_m3 > 0:
            consumption_change = (
                (
                    current_m3
                    - previous_m3
                )
                / previous_m3
                * 100
            )

        if previous_amount > 0:
            amount_change = (
                (
                    current_amount
                    - previous_amount
                )
                / previous_amount
                * 100
            )

    chart = list(
        reversed(invoices)
    )

    return render_template_string(
        WATER_TEMPLATE,
        invoices=invoices,
        latest=latest,
        total_m3=total_m3,
        total_tl=total_tl,
        avg_m3=avg_m3,
        avg_tl=avg_tl,
        consumption_change=(
            consumption_change
        ),
        amount_change=amount_change,
        cost_per_m3=cost_per_m3,
        chart=chart
    )


@app.route("/dogalgaz")
def gas():

    conn = get_db()

    rows = conn.execute("""
        SELECT *
        FROM invoices
        WHERE provider = 'igdas'
        ORDER BY invoice_date DESC
        LIMIT 12
    """).fetchall()

    conn.close()

    invoices = [
        dict(r)
        for r in rows
    ]

    for invoice in invoices:

        period = (
            invoice.get("period")
            or ""
        )

        # IGDAS collector period'i 09-2026
        # veya 202609 biciminde gelebilir.
        if (
            len(period) == 6
            and period.isdigit()
        ):
            invoice["period_text"] = tr_period(
                period[4:6] + "-" + period[:4]
            )
        else:
            invoice["period_text"] = tr_period(
                period
            )

        invoice["due_date_text"] = tr_date(
            invoice.get("due_date")
        )

        invoice["invoice_date_text"] = tr_date(
            invoice.get("invoice_date")
        )

        invoice["first_read_date_text"] = tr_date(
            invoice.get("first_read_date")
        )

        invoice["last_read_date_text"] = tr_date(
            invoice.get("last_read_date")
        )

        invoice["payment_date_text"] = tr_date(
            invoice.get("payment_date")
        )

        status = (
            invoice.get("payment_status")
            or ""
        ).lower()

        if status == "paid":
            invoice["payment_status_text"] = (
                "🟢 Ödendi"
            )
        elif status == "unpaid":
            invoice["payment_status_text"] = (
                "🟡 Ödenecek"
            )
        else:
            invoice["payment_status_text"] = (
                "⚪ Bilinmiyor"
            )

        consumption = (
            invoice.get("consumption_m3")
            or 0
        )

        days = (
            invoice.get("reading_days")
            or 0
        )

        invoice["daily_m3"] = (
            consumption / days
            if days else 0
        )

    total_m3 = sum(
        x.get("consumption_m3") or 0
        for x in invoices
    )

    total_tl = sum(
        x.get("amount_tl") or 0
        for x in invoices
    )

    avg_m3 = (
        total_m3 / len(invoices)
        if invoices else 0
    )

    avg_tl = (
        total_tl / len(invoices)
        if invoices else 0
    )

    latest = (
        invoices[0]
        if invoices else None
    )

    previous = (
        invoices[1]
        if len(invoices) > 1
        else None
    )

    consumption_change = None
    amount_change = None
    cost_per_m3 = None

    if latest:

        consumption = (
            latest.get("consumption_m3")
            or 0
        )

        amount = (
            latest.get("amount_tl")
            or 0
        )

        if consumption > 0:
            cost_per_m3 = (
                amount / consumption
            )

    if latest and previous:

        current_m3 = (
            latest.get("consumption_m3")
            or 0
        )

        previous_m3 = (
            previous.get("consumption_m3")
            or 0
        )

        current_amount = (
            latest.get("amount_tl")
            or 0
        )

        previous_amount = (
            previous.get("amount_tl")
            or 0
        )

        if previous_m3 > 0:
            consumption_change = (
                (current_m3 - previous_m3)
                / previous_m3 * 100
            )

        if previous_amount > 0:
            amount_change = (
                (current_amount - previous_amount)
                / previous_amount * 100
            )

    chart = list(
        reversed(invoices)
    )

    return render_template_string(
        GAS_TEMPLATE,
        invoices=invoices,
        latest=latest,
        total_m3=total_m3,
        total_tl=total_tl,
        avg_m3=avg_m3,
        avg_tl=avg_tl,
        consumption_change=consumption_change,
        amount_change=amount_change,
        cost_per_m3=cost_per_m3,
        chart=chart
    )



@app.route(
    "/fatura-dosya/<int:invoice_id>"
)
def invoice_file(invoice_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT provider, pdf_path
        FROM invoices
        WHERE id = ?
        """,
        (invoice_id,)
    ).fetchone()

    conn.close()

    if not row or not row["pdf_path"]:
        abort(404)

    relative = row["pdf_path"]

    # Hem goreli hem /pdfs ile baslayan
    # mutlak DB yollarini destekle.
    if os.path.isabs(relative):
        path = os.path.realpath(relative)
    else:
        path = os.path.realpath(
            os.path.join(
                PDF_ROOT,
                relative
            )
        )

    root = os.path.realpath(
        PDF_ROOT
    )

    if not path.startswith(
        root + os.sep
    ):
        abort(403)

    if not os.path.isfile(path):
        abort(404)

    ext = os.path.splitext(
        path
    )[1].lower()

    mimetypes = {
        ".pdf": "application/pdf",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
    }

    mimetype = mimetypes.get(
        ext,
        "application/octet-stream"
    )

    return send_file(
        path,
        mimetype=mimetype,
        as_attachment=False
    )


@app.route("/pdf/<int:invoice_id>")
def pdf(invoice_id):
    conn = get_db()

    row = conn.execute(
        """
        SELECT pdf_path
        FROM invoices
        WHERE id = ?
        """,
        (invoice_id,)
    ).fetchone()

    conn.close()

    if not row or not row["pdf_path"]:
        abort(404)

    path = os.path.realpath(row["pdf_path"])
    root = os.path.realpath(PDF_ROOT)

    if not path.startswith(root + os.sep):
        abort(403)

    if not os.path.isfile(path):
        abort(404)

    return send_file(
        path,
        mimetype="application/pdf",
        as_attachment=False
    )


@app.route("/health")
def health():
    return {"status": "ok"}


WATER_TEMPLATE = r"""
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>Su Fatura Takibi</title>

<style>
:root {
    color-scheme: dark;
    --bg: #0b1220;
    --card: #121c2e;
    --card2: #17243a;
    --text: #eef4ff;
    --muted: #91a4bf;
    --line: #263752;
    --accent: #58a6ff;
    --good: #4ade80;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: #07111f;
    color: #e8eef8;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 28px 20px 50px;
}

.topbar {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 20px;
    margin-bottom: 24px;
}

.provider-nav {
    display: flex;
    gap: 10px;
    margin-bottom: 22px;
    flex-wrap: wrap;
}

.provider-nav a {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 9px 15px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--card);
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
    transition:
        background 0.15s ease,
        border-color 0.15s ease,
        color 0.15s ease;
}

.provider-nav a:hover {
    background: var(--card2);
    color: var(--text);
}

.provider-nav a.active {
    background: var(--card2);
    border-color: var(--accent);
    color: var(--text);
}

h1 {
    margin: 0 0 5px;
    font-size: 30px;
}

.subtitle {
    color: #91a4bf;
    margin-bottom: 25px;
}

h2 {
    margin-top: 0;
    font-size: 20px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(5, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}

@media (max-width: 1100px) {
    .grid {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 700px) {
    .grid {
        grid-template-columns:
            1fr;
    }
}

.card {
    background: #0e1a2a;
    border: 1px solid #1e3048;
    border-radius: 14px;
    padding: 18px;
}

.label {
    color: #91a4bf;
    font-size: 13px;
    margin-bottom: 8px;
}

.value {
    font-size: 26px;
    font-weight: 700;
}

.sub {
    margin-top: 6px;
    color: #91a4bf;
    font-size: 13px;
}

.up {
    color: #fb7185;
}

.down {
    color: #4ade80;
}

.charts {
    display: grid;
    grid-template-columns:
        1fr;
    gap: 18px;
    margin-bottom: 18px;
}

.charts .card h2 {
    margin-top: 0;
    font-size: 19px;
}

canvas {
    width: 100%;
    height: 280px;
    display: block;
}

.breakdown {
    display: grid;
    grid-template-columns:
        repeat(4, minmax(0, 1fr));
    gap: 12px;
}

.breakdown-item {
    background: #111f32;
    border-radius: 10px;
    padding: 14px;
}

.breakdown-item strong {
    display: block;
    font-size: 20px;
    margin-top: 5px;
}

.table-card {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 1000px;
}

th,
td {
    text-align: right;
    padding: 12px 10px;
    border-bottom: 1px solid #1d3048;
    white-space: nowrap;
}

th {
    color: #91a4bf;
    font-size: 12px;
}

td {
    font-size: 14px;
}

th:first-child,
td:first-child {
    text-align: left;
}

.file-button {
    display: inline-block;
    text-decoration: none;
    color: #fff;
    background: #1769aa;
    padding: 7px 11px;
    border-radius: 8px;
    font-weight: 600;
}

.empty {
    color: #91a4bf;
}

@media (max-width: 900px) {
    .grid,
    .breakdown {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }

    .charts {
        grid-template-columns: 1fr;
    }
}

@media (max-width: 600px) {
    .container {
        padding: 16px;
    }

    .topbar {
        align-items: flex-start;
        flex-direction: column;
    }

    .grid,
    .breakdown {
        grid-template-columns: 1fr;
    }
}
</style>
</head>

<body>

<div class="container">

<nav class="provider-nav">
    <a href="/">
        ⚡ Elektrik
    </a>

    <a href="/su" class="active">
        💧 Su
    </a>

    <a href="/dogalgaz">
        🔥 Doğalgaz
    </a>
</nav>

<h1>💧 Su Fatura Takibi</h1>
<div class="subtitle">
İSKİ
</div>

{% if latest %}

<div class="grid">

    <div class="card">
        <div class="label">
            Son Fatura
        </div>

        <div class="value">
            {{ "%.2f"|format(latest.amount_tl or 0) }}
            TL
        </div>

        <div class="sub">
            {{ latest.period_text }}

            {% if amount_change is not none %}
                ·
                <span class="
                    {{ 'up' if amount_change > 0 else 'down' }}
                ">
                    {{ "%+.1f"|format(amount_change) }}%
                </span>
            {% endif %}
        </div>
    </div>

    <div class="card">
        <div class="label">
            Son Tüketim
        </div>

        <div class="value">
            {{ "%.1f"|format(latest.consumption_m3 or 0) }}
            m³
        </div>

        <div class="sub">
            {% if consumption_change is not none %}
                Önceki aya göre
                <span class="
                    {{ 'up' if consumption_change > 0 else 'down' }}
                ">
                    {{ "%+.1f"|format(consumption_change) }}%
                </span>
            {% else %}
                Aylık tüketim
            {% endif %}
        </div>
    </div>

    <div class="card">
        <div class="label">
            Günlük Ortalama
        </div>

        <div class="value">
            {{ "%.2f"|format(latest.daily_m3 or 0) }}
            m³
        </div>

        <div class="sub">
            {{ latest.reading_days or 0 }}
            günlük okuma dönemi
        </div>
    </div>

    <div class="card">
        <div class="label">
            12 Aylık Tüketim
        </div>

        <div class="value">
            {{ "%.1f"|format(total_m3) }}
            m³
        </div>

        <div class="sub">
            Aylık ortalama
            {{ "%.1f"|format(avg_m3) }} m³
        </div>
    </div>

    <div class="card">
        <div class="label">
            12 Aylık Tutar
        </div>

        <div class="value">
            {{ "%.2f"|format(total_tl) }}
            TL
        </div>

        <div class="sub">
            Aylık ortalama
            {{ "%.2f"|format(avg_tl) }} TL
        </div>
    </div>

</div>


<div class="charts">

    <div class="card">
        <h2>
            12 Aylık Tüketim
        </h2>

        <canvas id="consumptionChart"></canvas>
    </div>

    <div class="card">
        <h2>
            Aylık Fatura Tutarı
        </h2>

        <canvas id="amountChart"></canvas>
    </div>

</div>


<div class="card"
     style="margin-bottom:18px">

    <h2>
        Son Fatura Dağılımı
    </h2>

    <div class="breakdown">

        <div class="breakdown-item">
            <div class="label">
                Su Bedeli
            </div>
            <strong>
                {{ "%.2f"|format(
                    latest.water_charge_tl or 0
                ) }} TL
            </strong>
        </div>

        <div class="breakdown-item">
            <div class="label">
                Atıksu Bedeli
            </div>
            <strong>
                {{ "%.2f"|format(
                    latest.wastewater_charge_tl or 0
                ) }} TL
            </strong>
        </div>

        <div class="breakdown-item">
            <div class="label">
                ÇTV
            </div>
            <strong>
                {{ "%.2f"|format(
                    latest.ctv_tl or 0
                ) }} TL
            </strong>
        </div>

        <div class="breakdown-item">
            <div class="label">
                KDV
            </div>
            <strong>
                {{ "%.2f"|format(
                    latest.vat_tl or 0
                ) }} TL
            </strong>
        </div>

    </div>

    <div class="sub"
         style="margin-top:14px">

        Ortalama fatura:
        {{ "%.2f"|format(avg_tl) }} TL

        {% if cost_per_m3 is not none %}
            · Son faturada efektif maliyet:
            {{ "%.2f"|format(cost_per_m3) }}
            TL/m³
        {% endif %}

    </div>

</div>


<div class="card table-card">

<h2>Son 12 Fatura</h2>

<table>

<thead>
<tr>
    <th>Dönem</th>
    <th>Tüketim</th>
    <th>Günlük</th>
    <th>Okuma Aralığı</th>
    <th>Fatura</th>
    <th>Son Ödeme</th>
    <th>Ödeme Durumu</th>
    <th>Belge</th>
</tr>
</thead>

<tbody>

{% for invoice in invoices %}

<tr>
    <td>
        {{ invoice.period_text }}
    </td>

    <td>
        {{ "%.1f"|format(
            invoice.consumption_m3 or 0
        ) }} m³
    </td>

    <td>
        {{ "%.2f"|format(
            invoice.daily_m3 or 0
        ) }} m³
    </td>

    <td>
        {{ invoice.first_read_date_text }}
        –
        {{ invoice.last_read_date_text }}
    </td>

    <td>
        {{ "%.2f"|format(
            invoice.amount_tl or 0
        ) }} TL
    </td>

    <td>
        {{ invoice.due_date_text }}
    </td>

    <td>
        <strong>
            {{ invoice.payment_status_text }}
        </strong>

        {% if invoice.payment_status_note %}
        <div class="sub">
            {{ invoice.payment_status_note }}
        </div>
        {% endif %}
    </td>

    <td>
        {% if invoice.pdf_path %}
        <a
            class="file-button"
            href="/fatura-dosya/{{ invoice.id }}"
            target="_blank"
        >
            Görüntüle
        </a>
        {% else %}
            -
        {% endif %}
    </td>
</tr>

{% endfor %}

</tbody>
</table>

</div>

{% else %}

<div class="card empty">
    İSKİ faturası bulunamadı.
</div>

{% endif %}

</div>


<script>

const chartData = {{ chart | tojson }};

function prepareCanvas(id) {
    const canvas =
        document.getElementById(id);

    if (!canvas) {
        return null;
    }

    const ratio =
        window.devicePixelRatio || 1;

    const width =
        canvas.clientWidth;

    const height = 280;

    canvas.width =
        width * ratio;

    canvas.height =
        height * ratio;

    canvas.style.height =
        height + "px";

    const ctx =
        canvas.getContext("2d");

    ctx.scale(ratio, ratio);

    return {
        canvas,
        ctx,
        width,
        height
    };
}


function drawBars(
    id,
    field,
    suffix,
    color
) {
    const setup =
        prepareCanvas(id);

    if (!setup || !chartData.length) {
        return;
    }

    const {
        ctx,
        width,
        height
    } = setup;

    ctx.clearRect(
        0,
        0,
        width,
        height
    );

    const data =
        chartData.map(item => ({
            label:
                item.period_text || "",
            value:
                Number(item[field] || 0)
        }));

    const max =
        Math.max(
            ...data.map(x => x.value),
            1
        );

    const pad = {
        left: 55,
        right: 15,
        top: 15,
        bottom: 45
    };

    const w =
        width -
        pad.left -
        pad.right;

    const h =
        height -
        pad.top -
        pad.bottom;

    ctx.font =
        "11px sans-serif";

    ctx.strokeStyle =
        "#20334d";

    ctx.lineWidth = 1;

    for (
        let i = 0;
        i <= 4;
        i++
    ) {
        const y =
            pad.top +
            h -
            h * i / 4;

        const value =
            max * i / 4;

        ctx.beginPath();

        ctx.moveTo(
            pad.left,
            y
        );

        ctx.lineTo(
            width - pad.right,
            y
        );

        ctx.stroke();

        ctx.fillStyle =
            "#91a4bf";

        ctx.textAlign =
            "left";

        ctx.fillText(
            value.toFixed(
                suffix === "m³"
                    ? 1
                    : 0
            ) + " " + suffix,
            2,
            y + 4
        );
    }

    const slot =
        w / data.length;

    const barWidth =
        Math.min(
            42,
            slot * 0.62
        );

    data.forEach(
        (item, i) => {

            const barHeight =
                item.value /
                max *
                h;

            const x =
                pad.left +
                i * slot +
                (
                    slot -
                    barWidth
                ) / 2;

            const y =
                pad.top +
                h -
                barHeight;

            ctx.fillStyle =
                color;

            ctx.fillRect(
                x,
                y,
                barWidth,
                barHeight
            );

            ctx.fillStyle =
                "#91a4bf";

            ctx.textAlign =
                "center";

            ctx.fillText(
                item.label
                    .replace(
                        " 20",
                        " "
                    ),
                x + barWidth / 2,
                height - 18
            );
        }
    );

    ctx.textAlign = "left";
}


function drawCharts() {
    drawBars(
        "consumptionChart",
        "consumption_m3",
        "m³",
        "#38bdf8"
    );

    drawBars(
        "amountChart",
        "amount_tl",
        "TL",
        "#4ade80"
    );
}

drawCharts();

window.addEventListener(
    "resize",
    drawCharts
);

</script>

</body>
</html>
"""



GAS_TEMPLATE = r"""
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>Doğalgaz Fatura Takibi</title>

<style>
:root {
    color-scheme: dark;
    --bg: #0b1220;
    --card: #121c2e;
    --card2: #17243a;
    --text: #eef4ff;
    --muted: #91a4bf;
    --line: #263752;
    --accent: #58a6ff;
    --good: #4ade80;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    background: var(--bg);
    color: var(--text);
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}

.container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 28px 20px 50px;
}

.provider-nav {
    display: flex;
    gap: 10px;
    margin-bottom: 22px;
    flex-wrap: wrap;
}

.provider-nav a {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 9px 15px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--card);
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
}

.provider-nav a:hover {
    background: var(--card2);
    color: var(--text);
}

.provider-nav a.active {
    background: var(--card2);
    border-color: var(--accent);
    color: var(--text);
}

h1 {
    margin: 0 0 5px;
    font-size: 30px;
}

.subtitle {
    color: var(--muted);
    margin-bottom: 25px;
}

.grid {
    display: grid;
    grid-template-columns:
        repeat(5, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}

.card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px;
}

.label {
    color: var(--muted);
    font-size: 13px;
    margin-bottom: 8px;
}

.value {
    font-size: 26px;
    font-weight: 700;
}

.sub {
    margin-top: 6px;
    color: var(--muted);
    font-size: 13px;
}

.up {
    color: #f87171;
}

.down {
    color: #4ade80;
}

.section {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px;
    margin-top: 18px;
}

.section h2 {
    margin-top: 0;
    font-size: 19px;
}

canvas {
    width: 100%;
    height: 280px;
    display: block;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 1000px;
}

th, td {
    padding: 12px 10px;
    border-bottom: 1px solid var(--line);
    text-align: right;
    white-space: nowrap;
}

th {
    color: var(--muted);
    font-size: 12px;
}

th:first-child,
td:first-child {
    text-align: left;
}

.file-button {
    display: inline-block;
    text-decoration: none;
    color: #fff;
    background: #1769aa;
    padding: 7px 11px;
    border-radius: 8px;
    font-weight: 600;
}

@media (max-width: 1100px) {
    .grid {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 700px) {
    .grid {
        grid-template-columns: 1fr;
    }

    .container {
        padding: 18px 12px 40px;
    }
}

/* =========================================================
   IGDAS FATURA DETAY PANELI
   ========================================================= */

.detail-button {
    display: inline-block;
    border: 1px solid var(--line);
    color: var(--text);
    background: var(--card2);
    padding: 7px 11px;
    border-radius: 8px;
    font-weight: 600;
    cursor: pointer;
    font-family: inherit;
    font-size: 14px;
    white-space: nowrap;
}

.detail-button:hover {
    border-color: var(--accent);
}

.detail-button.active {
    border-color: var(--accent);
    color: var(--accent);
}

.detail-row {
    display: none;
}

.detail-row.open {
    display: table-row;
}

.detail-cell {
    padding: 0 !important;
    text-align: left !important;
    white-space: normal !important;
    background: #0d1727;
}

.invoice-detail {
    padding: 18px;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
}

.detail-title {
    font-size: 17px;
    font-weight: 700;
    margin-bottom: 15px;
}

.detail-grid {
    display: grid;
    grid-template-columns:
        repeat(4, minmax(0, 1fr));
    gap: 14px;
}

.detail-group {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 12px;
    padding: 14px;
}

.detail-group h3 {
    margin: 0 0 12px;
    font-size: 14px;
    color: var(--accent);
}

.detail-item {
    display: flex;
    justify-content: space-between;
    gap: 15px;
    padding: 7px 0;
    border-bottom:
        1px solid rgba(38, 55, 82, .65);
    font-size: 13px;
}

.detail-item:last-child {
    border-bottom: 0;
}

.detail-key {
    color: var(--muted);
}

.detail-value {
    color: var(--text);
    font-weight: 600;
    text-align: right;
}

.detail-total {
    margin-top: 5px;
    padding-top: 10px;
    font-size: 15px;
    font-weight: 700;
}

.detail-support {
    color: var(--good);
}

@media (max-width: 1100px) {
    .detail-grid {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 700px) {
    .detail-grid {
        grid-template-columns: 1fr;
    }
}

</style>
</head>

<body>

<div class="container">

<nav class="provider-nav">

    <a href="/">
        ⚡ Elektrik
    </a>

    <a href="/su">
        💧 Su
    </a>

    <a href="/dogalgaz" class="active">
        🔥 Doğalgaz
    </a>

</nav>

<h1>🔥 Doğalgaz Fatura Takibi</h1>

<div class="subtitle">
    İGDAŞ
</div>

{% if latest %}

<div class="grid">

<div class="card">
    <div class="label">Son Fatura</div>
    <div class="value">
        {{ "%.2f"|format(latest.amount_tl or 0) }} TL
    </div>
    <div class="sub">
        {{ latest.period_text }}
        • Son ödeme:
        {{ latest.due_date_text }}
    </div>
</div>

<div class="card">
    <div class="label">Son Tüketim</div>
    <div class="value">
        {{ "%.1f"|format(latest.consumption_m3 or 0) }} m³
    </div>
    <div class="sub">
        {% if consumption_change is not none %}
        Önceki aya göre
        <span class="{{ 'up' if consumption_change > 0 else 'down' }}">
            {{ "%+.1f"|format(consumption_change) }}%
        </span>
        {% endif %}
    </div>
</div>

<div class="card">
    <div class="label">Günlük Ortalama</div>
    <div class="value">
        {{ "%.2f"|format(latest.daily_m3 or 0) }} m³
    </div>
    <div class="sub">
        {{ latest.reading_days or 0 }}
        günlük okuma dönemi
    </div>
</div>

<div class="card">
    <div class="label">12 Aylık Tüketim</div>
    <div class="value">
        {{ "%.1f"|format(total_m3) }} m³
    </div>
    <div class="sub">
        Aylık ortalama:
        {{ "%.1f"|format(avg_m3) }} m³
        {% if cost_per_m3 is not none %}
        • Son ay
        {{ "%.2f"|format(cost_per_m3) }} TL/m³
        {% endif %}
    </div>
</div>

<div class="card">
    <div class="label">12 Aylık Tutar</div>
    <div class="value">
        {{ "%.2f"|format(total_tl) }} TL
    </div>
    <div class="sub">
        Aylık ortalama:
        {{ "%.2f"|format(avg_tl) }} TL

        {% if amount_change is not none %}
        •
        <span class="{{ 'up' if amount_change > 0 else 'down' }}">
            {{ "%+.1f"|format(amount_change) }}%
        </span>
        {% endif %}
    </div>
</div>

</div>

<div class="section">
<h2>12 Aylık Tüketim</h2>
<canvas id="consumptionChart"></canvas>
</div>

<div class="section">
<h2>Aylık Fatura Tutarı</h2>
<canvas id="amountChart"></canvas>
</div>

<div class="section">

<h2>Son 12 Fatura</h2>

<div class="table-wrap">

<table>

<thead>
<tr>
<th>Dönem</th>
<th>Tüketim</th>
<th>Günlük</th>
<th>Okuma Aralığı</th>
<th>Gün</th>
<th>Tutar</th>
<th>Son Ödeme</th>
<th>Durum</th>
<th>Belge</th>
<th>Detay</th>
</tr>
</thead>

<tbody>

{% for x in invoices %}

<tr>

<td>{{ x.period_text }}</td>

<td>
{{ "%.1f"|format(x.consumption_m3 or 0) }} m³
</td>

<td>
{{ "%.2f"|format(x.daily_m3 or 0) }} m³
</td>

<td>
{{ x.first_read_date_text }}
–
{{ x.last_read_date_text }}
</td>

<td>
{{ x.reading_days or "-" }}
</td>

<td>
<strong>
{{ "%.2f"|format(x.amount_tl or 0) }} TL
</strong>
</td>

<td>
{{ x.due_date_text }}
</td>

<td>
<strong>
{{ x.payment_status_text }}
</strong>
</td>

<td>
{% if x.pdf_path %}
<a class="file-button"
   href="/fatura-dosya/{{ x.id }}"
   target="_blank">
Görüntüle
</a>
{% else %}
-
{% endif %}
</td>

<td>
<button
    type="button"
    class="detail-button"
    onclick="toggleInvoiceDetail({{ x.id }}, this)">
Detay
</button>
</td>

</tr>

<tr
    id="detail-{{ x.id }}"
    class="detail-row">

<td
    colspan="10"
    class="detail-cell">

<div class="invoice-detail">

<div class="detail-title">
{{ x.period_text }} • Fatura Detayı
</div>

<div class="detail-grid">

<!-- TUKETIM ============================================== -->

<div class="detail-group">

<h3>🔥 Tüketim</h3>

<div class="detail-item">
<span class="detail-key">Tüketim</span>
<span class="detail-value">
{% if x.consumption_m3 is not none %}
{{ "%.2f"|format(x.consumption_m3) }} m³
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">Enerji karşılığı</span>
<span class="detail-value">
{% if x.consumption_kwh is not none %}
{{ "%.2f"|format(x.consumption_kwh) }} kWh
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">Okuma süresi</span>
<span class="detail-value">
{% if x.reading_days %}
{{ x.reading_days }} gün
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">Günlük ortalama</span>
<span class="detail-value">
{% if x.daily_m3 is not none %}
{{ "%.3f"|format(x.daily_m3) }} m³/gün
{% else %}
—
{% endif %}
</span>
</div>

</div>


<!-- SAYAC ================================================ -->

<div class="detail-group">

<h3>🔢 Sayaç Bilgileri</h3>

<div class="detail-item">
<span class="detail-key">İlk okuma tarihi</span>
<span class="detail-value">
{{ x.first_read_date_text }}
</span>
</div>

<div class="detail-item">
<span class="detail-key">İlk endeks</span>
<span class="detail-value">
{% if x.first_index is not none %}
{{ "%.2f"|format(x.first_index) }}
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">Son okuma tarihi</span>
<span class="detail-value">
{{ x.last_read_date_text }}
</span>
</div>

<div class="detail-item">
<span class="detail-key">Son endeks</span>
<span class="detail-value">
{% if x.last_index is not none %}
{{ "%.2f"|format(x.last_index) }}
{% else %}
—
{% endif %}
</span>
</div>

</div>


<!-- HESAPLAMA ============================================ -->

<div class="detail-group">

<h3>⚙️ Hesaplama Bilgileri</h3>

<div class="detail-item">
<span class="detail-key">
Düzeltme katsayısı
</span>
<span class="detail-value">
{% if x.correction_factor is not none %}
{{ "%.6f"|format(x.correction_factor) }}
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">
Üst ısıl değer
</span>
<span class="detail-value">
{% if x.calorific_value is not none %}
{{ "%.6f"|format(x.calorific_value) }}
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">
Birim fiyat
</span>
<span class="detail-value">
{% if x.unit_price is not none %}
{{ "%.8f"|format(x.unit_price) }} TL
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">
Fatura tarihi
</span>
<span class="detail-value">
{{ x.invoice_date_text }}
</span>
</div>

</div>


<!-- BEDELLER ============================================= -->

<div class="detail-group">

<h3>💳 Fatura Bedelleri</h3>

<div class="detail-item">
<span class="detail-key">
Tüketim bedeli
</span>
<span class="detail-value">
{% if x.consumption_charge_tl is not none %}
{{ "%.2f"|format(x.consumption_charge_tl) }} TL
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">
Diğer bedeller
</span>
<span class="detail-value">
{% if x.other_charge_tl is not none %}
{{ "%.2f"|format(x.other_charge_tl) }} TL
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">KDV</span>
<span class="detail-value">
{% if x.vat_tl is not none %}
{{ "%.2f"|format(x.vat_tl) }} TL
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item">
<span class="detail-key">
Devlet desteği
</span>
<span class="detail-value detail-support">
{% if x.state_support_tl is not none %}
{{ "%.2f"|format(x.state_support_tl) }} TL
{% else %}
—
{% endif %}
</span>
</div>

<div class="detail-item detail-total">
<span class="detail-key">
Fatura toplamı
</span>
<span class="detail-value">
{{ "%.2f"|format(x.amount_tl or 0) }} TL
</span>
</div>

</div>

</div>

</div>

</td>
</tr>

{% endfor %}

</tbody>

</table>

</div>
</div>

{% else %}

<div class="card">
İGDAŞ faturası bulunamadı.
</div>

{% endif %}

</div>

<script>

function toggleInvoiceDetail(id, button) {

    const row =
        document.getElementById(
            "detail-" + id
        );

    if (!row) {
        return;
    }

    const opening =
        !row.classList.contains("open");

    document.querySelectorAll(
        ".detail-row.open"
    ).forEach(function(otherRow) {

        otherRow.classList.remove(
            "open"
        );

    });

    document.querySelectorAll(
        ".detail-button"
    ).forEach(function(otherButton) {

        otherButton.classList.remove(
            "active"
        );

        otherButton.textContent =
            "Detay";

    });

    if (opening) {

        row.classList.add(
            "open"
        );

        button.classList.add(
            "active"
        );

        button.textContent =
            "Kapat";
    }
}

const chartData = {{ chart | tojson }};

function drawBars(id, field, suffix, color) {

    const canvas =
        document.getElementById(id);

    if (!canvas || !chartData.length) {
        return;
    }

    const ratio =
        window.devicePixelRatio || 1;

    const width =
        canvas.clientWidth;

    const height = 280;

    canvas.width =
        width * ratio;

    canvas.height =
        height * ratio;

    canvas.style.height =
        height + "px";

    const ctx =
        canvas.getContext("2d");

    ctx.scale(ratio, ratio);

    const data =
        chartData.map(item => ({
            label:
                item.period_text || "",
            value:
                Number(item[field] || 0)
        }));

    const max =
        Math.max(
            ...data.map(x => x.value),
            1
        ) * 1.15;

    const pad = {
        left: 65,
        right: 20,
        top: 20,
        bottom: 50
    };

    const w =
        width -
        pad.left -
        pad.right;

    const h =
        height -
        pad.top -
        pad.bottom;

    ctx.font =
        "11px sans-serif";

    ctx.strokeStyle =
        "#263752";

    ctx.lineWidth = 1;

    for (let i = 0; i <= 4; i++) {

        const y =
            pad.top +
            h -
            h * i / 4;

        const value =
            max * i / 4;

        ctx.beginPath();

        ctx.moveTo(
            pad.left,
            y
        );

        ctx.lineTo(
            width - pad.right,
            y
        );

        ctx.stroke();

        ctx.fillStyle =
            "#91a4bf";

        ctx.textAlign =
            "left";

        ctx.fillText(
            value.toFixed(
                suffix === "m³" ? 1 : 0
            ) + " " + suffix,
            2,
            y + 4
        );
    }

    const slot =
        w / data.length;

    const barWidth =
        Math.min(
            42,
            slot * 0.62
        );

    data.forEach((item, i) => {

        const barHeight =
            item.value /
            max *
            h;

        const x =
            pad.left +
            i * slot +
            (
                slot -
                barWidth
            ) / 2;

        const y =
            pad.top +
            h -
            barHeight;

        ctx.fillStyle =
            color;

        ctx.fillRect(
            x,
            y,
            barWidth,
            barHeight
        );

        ctx.fillStyle =
            "#91a4bf";

        ctx.textAlign =
            "center";

        ctx.fillText(
            item.label.replace(
                " 20",
                " "
            ),
            x + barWidth / 2,
            height - 18
        );
    });

    ctx.textAlign = "left";
}

function drawCharts() {

    drawBars(
        "consumptionChart",
        "consumption_m3",
        "m³",
        "#f59e0b"
    );

    drawBars(
        "amountChart",
        "amount_tl",
        "TL",
        "#4ade80"
    );
}

drawCharts();

window.addEventListener(
    "resize",
    drawCharts
);

</script>

</body>
</html>
"""


TEMPLATE = r'''
<!doctype html>
<html lang="tr">
<head>
<meta charset="utf-8">
<meta name="viewport"
      content="width=device-width, initial-scale=1">

<title>Fatura Takip</title>

<style>
:root {
    color-scheme: dark;
    --bg: #0b1220;
    --card: #121c2e;
    --card2: #17243a;
    --text: #eef4ff;
    --muted: #91a4bf;
    --line: #263752;
    --accent: #58a6ff;
    --good: #4ade80;
}

* {
    box-sizing: border-box;
}

body {
    margin: 0;
    font-family:
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
    background: var(--bg);
    color: var(--text);
}

.container {
    max-width: 1400px;
    margin: 0 auto;
    padding: 28px 20px 50px;
}

.provider-nav {
    display: flex;
    gap: 10px;
    margin-bottom: 22px;
    flex-wrap: wrap;
}

.provider-nav a {
    display: inline-flex;
    align-items: center;
    gap: 7px;
    padding: 9px 15px;
    border-radius: 10px;
    border: 1px solid var(--line);
    background: var(--card);
    color: var(--muted);
    text-decoration: none;
    font-size: 14px;
    font-weight: 600;
    transition:
        background 0.15s ease,
        border-color 0.15s ease,
        color 0.15s ease;
}

.provider-nav a:hover {
    background: var(--card2);
    color: var(--text);
}

.provider-nav a.active {
    background: var(--card2);
    border-color: var(--accent);
    color: var(--text);
}

h1 {
    margin: 0 0 5px;
    font-size: 30px;
}

.subtitle {
    color: var(--muted);
    margin-bottom: 25px;
}

.cards {
    display: grid;
    grid-template-columns:
        repeat(3, minmax(0, 1fr));
    gap: 14px;
    margin-bottom: 22px;
}

.summary-cards {
    grid-template-columns:
        repeat(5, minmax(0, 1fr));
}

@media (max-width: 1100px) {
    .summary-cards {
        grid-template-columns:
            repeat(2, minmax(0, 1fr));
    }
}

@media (max-width: 700px) {
    .cards,
    .summary-cards {
        grid-template-columns:
            1fr;
    }
}

.card {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px;
}

.label {
    color: var(--muted);
    font-size: 13px;
    margin-bottom: 8px;
}

.value {
    font-size: 26px;
    font-weight: 700;
}

.small {
    color: var(--muted);
    font-size: 13px;
    margin-top: 6px;
}

.up {
    color: #f87171;
}

.down {
    color: #4ade80;
}

.neutral {
    color: var(--muted);
}

.section {
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px;
    margin-top: 18px;
}

.section h2 {
    margin-top: 0;
    font-size: 19px;
}

canvas {
    width: 100%;
    height: 280px;
    display: block;
}

.table-wrap {
    overflow-x: auto;
}

table {
    width: 100%;
    border-collapse: collapse;
    min-width: 1000px;
}

th, td {
    padding: 12px 10px;
    border-bottom: 1px solid var(--line);
    text-align: right;
    white-space: nowrap;
}

th {
    color: var(--muted);
    font-size: 12px;
}

th:first-child,
td:first-child {
    text-align: left;
}

a.file-button {
    display: inline-block;
    text-decoration: none;
    color: #fff;
    background: #1769aa;
    padding: 7px 11px;
    border-radius: 8px;
    font-weight: 600;
}

.status {
    color: var(--good);
}

.footer {
    color: var(--muted);
    text-align: center;
    font-size: 12px;
    margin-top: 25px;
}

@media (max-width: 600px) {
    .container {
        padding: 18px 12px 40px;
    }

    h1 {
        font-size: 25px;
    }

    .value {
        font-size: 22px;
    }
}
</style>
</head>

<body>

<div class="container">

<nav class="provider-nav">
    <a href="/" class="active">
        ⚡ Elektrik
    </a>

    <a href="/su">
        💧 Su
    </a>

    <a href="/dogalgaz">
        🔥 Doğalgaz
    </a>
</nav>

<h1>⚡ Elektrik Fatura Takibi</h1>
<div class="subtitle">
CK Enerji Boğaziçi Elektrik
</div>

{% if latest %}

<div class="cards summary-cards">

<div class="card">
<div class="label">Son Fatura</div>
<div class="value">
{{ "%.2f"|format(latest.amount_tl or 0) }} TL
</div>
<div class="small">
{{ latest.period_text }} • Son ödeme:
{{ latest.due_date_text }}
</div>
</div>

<div class="card">
<div class="label">Son Tüketim</div>
<div class="value">
{{ "%.3f"|format(latest.consumption_kwh or 0) }} kWh
</div>
<div class="small">
Günlük:
{{ "%.3f"|format(latest.daily_kwh or 0) }} kWh
{% if consumption_change is not none %}
•
<span class="{{ 'up' if consumption_change > 0 else 'down' }}">
{{ "%+.1f"|format(consumption_change) }}%
</span>
{% endif %}
</div>
</div>

<div class="card">
<div class="label">Günlük Ortalama</div>
<div class="value">
{{ "%.3f"|format(latest.daily_kwh or 0) }} kWh
</div>
<div class="small">
{{ latest.reading_days or 0 }} günlük okuma dönemi
</div>
</div>

<div class="card">
<div class="label">12 Aylık Tüketim</div>
<div class="value">
{{ "%.1f"|format(total_kwh) }} kWh
</div>
<div class="small">
Aylık ortalama:
{{ "%.1f"|format(avg_kwh) }} kWh
{% if cost_per_kwh is not none %}
• Son ay {{ "%.2f"|format(cost_per_kwh) }} TL/kWh
{% endif %}
</div>
</div>

<div class="card">
<div class="label">12 Aylık Tutar</div>
<div class="value">
{{ "%.2f"|format(total_tl) }} TL
</div>
<div class="small">
Aylık ortalama:
{{ "%.2f"|format(avg_tl) }} TL
{% if amount_change is not none %}
•
<span class="{{ 'up' if amount_change > 0 else 'down' }}">
{{ "%+.1f"|format(amount_change) }}%
</span>
{% endif %}
</div>
</div>

</div>


<div class="section">
<h2>12 Aylık Tüketim</h2>
<canvas id="chart"></canvas>
</div>


<div class="section">
<h2>Aylık Fatura Tutarı</h2>
<canvas id="amountChart"></canvas>
</div>

<div class="section">
<h2>Son Fatura Dağılımı</h2>

<div class="cards">

<div class="card">
<div class="label">Gündüz</div>
<div class="value">
{{ "%.3f"|format(latest.day_kwh or 0) }} kWh
</div>
<div class="small">
{% if latest.consumption_kwh %}
{{ "%.1f"|format((latest.day_kwh or 0) / latest.consumption_kwh * 100) }}%
{% endif %}
</div>
</div>

<div class="card">
<div class="label">Puant</div>
<div class="value">
{{ "%.3f"|format(latest.peak_kwh or 0) }} kWh
</div>
<div class="small">
{% if latest.consumption_kwh %}
{{ "%.1f"|format((latest.peak_kwh or 0) / latest.consumption_kwh * 100) }}%
{% endif %}
</div>
</div>

<div class="card">
<div class="label">Gece</div>
<div class="value">
{{ "%.3f"|format(latest.night_kwh or 0) }} kWh
</div>
<div class="small">
{% if latest.consumption_kwh %}
{{ "%.1f"|format((latest.night_kwh or 0) / latest.consumption_kwh * 100) }}%
{% endif %}
</div>
</div>

</div>
</div>

<div class="section">
<h2>Son 12 Fatura</h2>

<div class="table-wrap">
<table>

<thead>
<tr>
<th>Dönem</th>
<th>Tüketim</th>
<th>Günlük</th>
<th>Gündüz</th>
<th>Puant</th>
<th>Gece</th>
<th>Gün</th>
<th>Tutar</th>
<th>Durum</th>
<th>Ödeme Tarihi</th>
<th>Belge</th>
</tr>
</thead>

<tbody>

{% for x in invoices %}
<tr>

<td>{{ x.period_text }}</td>

<td>
{{ "%.3f"|format(x.consumption_kwh or 0) }} kWh
</td>

<td>
{{ "%.3f"|format(x.daily_kwh or 0) }}
</td>

<td>
{{ "%.3f"|format(x.day_kwh or 0) }}
</td>

<td>
{{ "%.3f"|format(x.peak_kwh or 0) }}
</td>

<td>
{{ "%.3f"|format(x.night_kwh or 0) }}
</td>

<td>
{{ x.reading_days or "-" }}
</td>

<td>
<strong>
{{ "%.2f"|format(x.amount_tl or 0) }} TL
</strong>
</td>

<td class="status">
{% if x.payment_display == "Ödendi" %}
🟢 Ödendi
{% elif x.payment_display == "Ödenecek" %}
🟡 Ödenecek
{% else %}
{{ x.payment_display }}
{% endif %}
</td>

<td>
{% if x.payment_display == "Ödendi" %}
{{ x.payment_date_text }}
{% else %}
-
{% endif %}
</td>

<td>
{% if x.pdf_path %}
<a class="file-button"
   href="/pdf/{{ x.id }}"
   target="_blank">
Görüntüle
</a>
{% else %}
-
{% endif %}
</td>

</tr>
{% endfor %}

</tbody>
</table>
</div>
</div>

{% else %}

<div class="section">
Henüz fatura kaydı bulunmuyor.
</div>

{% endif %}

<div class="footer">
Fatura Takip
</div>

</div>


<script>
const data = [
{% for x in chart %}
{
    label: {{ x.period_text|tojson }},
    value: {{ x.consumption_kwh or 0 }},
    amount: {{ x.amount_tl or 0 }}
},
{% endfor %}
];

const canvas = document.getElementById("chart");

if (canvas && data.length) {

    function drawChart() {

        const ratio = window.devicePixelRatio || 1;
        const width = canvas.clientWidth;
        const height = canvas.clientHeight;

        canvas.width = width * ratio;
        canvas.height = height * ratio;

        const ctx = canvas.getContext("2d");
        ctx.scale(ratio, ratio);

        const pad = {
            left: 55,
            right: 20,
            top: 20,
            bottom: 50
        };

        const w = width - pad.left - pad.right;
        const h = height - pad.top - pad.bottom;

        const max =
            Math.max(...data.map(x => x.value)) * 1.15;

        ctx.font = "12px sans-serif";
        ctx.fillStyle = "#91a4bf";
        ctx.strokeStyle = "#263752";
        ctx.lineWidth = 1;

        for (let i = 0; i <= 4; i++) {

            const y =
                pad.top + h - (h * i / 4);

            const val =
                Math.round(max * i / 4);

            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(width - pad.right, y);
            ctx.stroke();

            ctx.fillText(
                val + " kWh",
                2,
                y + 4
            );
        }

        const slot = w / data.length;
        const barWidth =
            Math.min(42, slot * 0.62);

        data.forEach((item, i) => {

            const barHeight =
                (item.value / max) * h;

            const x =
                pad.left +
                i * slot +
                (slot - barWidth) / 2;

            const y =
                pad.top + h - barHeight;

            ctx.fillStyle = "#58a6ff";

            ctx.fillRect(
                x,
                y,
                barWidth,
                barHeight
            );

            ctx.fillStyle = "#91a4bf";
            ctx.textAlign = "center";

            ctx.fillText(
                item.label
                    .replace(" 20", " "),
                x + barWidth / 2,
                height - 18
            );
        });

        ctx.textAlign = "left";
    }

    drawChart();

    window.addEventListener(
        "resize",
        drawChart
    );
}

const amountCanvas = document.getElementById("amountChart");

if (amountCanvas && data.length) {

    function drawAmountChart() {

        const ratio = window.devicePixelRatio || 1;
        const width = amountCanvas.clientWidth;
        const height = amountCanvas.clientHeight;

        amountCanvas.width = width * ratio;
        amountCanvas.height = height * ratio;

        const ctx = amountCanvas.getContext("2d");
        ctx.scale(ratio, ratio);

        const pad = {
            left: 65,
            right: 20,
            top: 20,
            bottom: 50
        };

        const w = width - pad.left - pad.right;
        const h = height - pad.top - pad.bottom;

        const max =
            Math.max(...data.map(x => x.amount)) * 1.15;

        ctx.font = "12px sans-serif";
        ctx.strokeStyle = "#263752";
        ctx.lineWidth = 1;

        for (let i = 0; i <= 4; i++) {

            const y =
                pad.top + h - (h * i / 4);

            const val =
                Math.round(max * i / 4);

            ctx.beginPath();
            ctx.moveTo(pad.left, y);
            ctx.lineTo(width - pad.right, y);
            ctx.stroke();

            ctx.fillStyle = "#91a4bf";
            ctx.textAlign = "left";

            ctx.fillText(
                val + " TL",
                2,
                y + 4
            );
        }

        const slot = w / data.length;
        const barWidth =
            Math.min(42, slot * 0.62);

        data.forEach((item, i) => {

            const barHeight =
                (item.amount / max) * h;

            const x =
                pad.left +
                i * slot +
                (slot - barWidth) / 2;

            const y =
                pad.top + h - barHeight;

            ctx.fillStyle = "#4ade80";

            ctx.fillRect(
                x,
                y,
                barWidth,
                barHeight
            );

            ctx.fillStyle = "#91a4bf";
            ctx.textAlign = "center";

            ctx.fillText(
                item.label.replace(" 20", " "),
                x + barWidth / 2,
                height - 18
            );
        });

        ctx.textAlign = "left";
    }

    drawAmountChart();

    window.addEventListener(
        "resize",
        drawAmountChart
    );
}

</script>

</body>
</html>
'''

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=8080
    )
