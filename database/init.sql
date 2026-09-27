PRAGMA foreign_keys = ON;

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

    -- Elektrik
    consumption_kwh REAL,
    daily_kwh REAL,
    day_kwh REAL,
    peak_kwh REAL,
    night_kwh REAL,

    -- Ortak sayaç alanları
    first_index REAL,
    last_index REAL,
    first_read_date TEXT,
    last_read_date TEXT,

    -- Elektrik güç alanları
    demand_kw REAL,
    installed_power_kw REAL,
    contract_power_kw REAL,

    previous_year_kwh REAL,
    current_year_kwh REAL,

    pdf_path TEXT,

    collected_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    -- Su / Doğalgaz
    consumption_m3 REAL,
    daily_m3 REAL,

    -- İSKİ
    water_charge_tl REAL,
    wastewater_charge_tl REAL,
    ctv_tl REAL,

    -- Ortak / İGDAŞ
    vat_tl REAL,

    -- İGDAŞ
    correction_factor REAL,
    calorific_value REAL,
    unit_price REAL,
    consumption_charge_tl REAL,
    other_charge_tl REAL,
    state_support_tl REAL,

    UNIQUE(provider, bill_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    bill_id TEXT NOT NULL,
    notification_type TEXT NOT NULL,
    sent_at TEXT NOT NULL,

    UNIQUE(provider, bill_id, notification_type)
);

CREATE TABLE IF NOT EXISTS system_alerts (
    alert_type TEXT PRIMARY KEY,
    active INTEGER NOT NULL DEFAULT 0,
    first_seen TEXT,
    last_seen TEXT,
    notified_at TEXT
);
