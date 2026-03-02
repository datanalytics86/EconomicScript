PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    keywords TEXT NOT NULL DEFAULT '[]', -- JSON array
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS category_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    category_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bank TEXT NOT NULL CHECK (bank IN ('BCI', 'BANCO_ESTADO', 'SECURITY')),
    date TEXT NOT NULL,
    amount INTEGER NOT NULL,
    type TEXT,
    merchant TEXT,
    category_id INTEGER,
    source TEXT NOT NULL CHECK (source IN ('gmail', 'cartola')),
    verified INTEGER NOT NULL DEFAULT 0,
    raw_text TEXT,
    gmail_message_id TEXT UNIQUE,
    statement_ref TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (category_id) REFERENCES categories(id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_bank_date_amount
    ON transactions(bank, date, amount);

CREATE INDEX IF NOT EXISTS idx_transactions_source
    ON transactions(source);

CREATE TABLE IF NOT EXISTS reconciliation_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id INTEGER NOT NULL,
    match_status TEXT NOT NULL CHECK (match_status IN ('verified', 'gmail_only', 'cartola_only')),
    matched_with_id INTEGER,
    reconciled_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (transaction_id) REFERENCES transactions(id),
    FOREIGN KEY (matched_with_id) REFERENCES transactions(id)
);

CREATE TABLE IF NOT EXISTS unprocessed_emails (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL UNIQUE,
    sender TEXT,
    subject TEXT,
    raw_text TEXT NOT NULL,
    error_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
