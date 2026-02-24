-- Reconciliation Exception Investigation Agent
-- Database Schema (SQLite)

-- ============================================================
-- REFERENCE TABLES (exception sources — truth for discrepancies)
-- ============================================================

CREATE TABLE IF NOT EXISTS restructured_payments (
    restructure_id      TEXT PRIMARY KEY,
    loan_id             TEXT NOT NULL,
    original_due_date   DATE NOT NULL,
    restructured_due_date DATE NOT NULL,
    period              DATE NOT NULL,  -- reconciliation period (first of month)
    original_amount     DECIMAL(15,2) NOT NULL,
    restructured_amount DECIMAL(15,2) NOT NULL,
    status              TEXT NOT NULL   -- PENDING | COMPLETED | CANCELLED
);

CREATE TABLE IF NOT EXISTS delinquency_fees (
    fee_id          TEXT PRIMARY KEY,
    loan_id         TEXT NOT NULL,
    fee_date        DATE NOT NULL,
    period          DATE NOT NULL,
    fee_amount      DECIMAL(15,2) NOT NULL,
    fee_type        TEXT NOT NULL,      -- LATE_FEE | PENALTY_FEE | ADMIN_FEE
    days_past_due   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS refunds (
    refund_id       TEXT PRIMARY KEY,
    loan_id         TEXT NOT NULL,
    refund_date     DATE NOT NULL,
    period          DATE NOT NULL,
    refund_amount   DECIMAL(15,2) NOT NULL,
    refund_reason   TEXT NOT NULL       -- OVERPAYMENT | CANCELLED_LOAN | DISPUTE
);

CREATE TABLE IF NOT EXISTS charge_offs (
    charge_off_id   TEXT PRIMARY KEY,
    loan_id         TEXT NOT NULL,
    charge_off_date DATE NOT NULL,
    period          DATE NOT NULL,
    days_past_due   INTEGER NOT NULL,
    charge_off_amount DECIMAL(15,2) NOT NULL,
    status          TEXT NOT NULL       -- PENDING | CONFIRMED | REVERSED
);

-- ============================================================
-- LEDGER TABLES
-- ============================================================

CREATE TABLE IF NOT EXISTS gl_journal_entries (
    entry_id        TEXT PRIMARY KEY,
    transaction_date DATE NOT NULL,
    period          DATE NOT NULL,
    account_code    TEXT NOT NULL,
    debit_amount    DECIMAL(15,2) NOT NULL DEFAULT 0,
    credit_amount   DECIMAL(15,2) NOT NULL DEFAULT 0,
    reference_id    TEXT NOT NULL,      -- FK to exception table PK
    reference_type  TEXT NOT NULL,      -- RESTRUCTURE | FEE | REFUND | CHARGE_OFF
    entry_type      TEXT NOT NULL
    -- entry_type values:
    --   RESTRUCTURE_REVERSAL | RESTRUCTURE_ADDITION
    --   FEE_POSTING
    --   REFUND_CREDIT
    --   CHARGE_OFF_WRITE_OFF
);

CREATE TABLE IF NOT EXISTS ar_subledger (
    record_id           TEXT PRIMARY KEY,
    loan_id             TEXT NOT NULL,
    transaction_date    DATE NOT NULL,
    period              DATE NOT NULL,
    transaction_type    TEXT NOT NULL,
    -- transaction_type values:
    --   RESTRUCTURE_REVERSAL | RESTRUCTURE_ADDITION
    --   FEE_CHARGE
    --   REFUND_APPLIED
    --   CHARGE_OFF_CLEARANCE
    amount              DECIMAL(15,2) NOT NULL,
    reference_id        TEXT NOT NULL,  -- FK to exception table PK
    reference_type      TEXT NOT NULL   -- RESTRUCTURE | FEE | REFUND | CHARGE_OFF
);

-- ============================================================
-- INDEXES for query performance
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_gl_period ON gl_journal_entries (period);
CREATE INDEX IF NOT EXISTS idx_gl_reference ON gl_journal_entries (reference_id, reference_type);
CREATE INDEX IF NOT EXISTS idx_ar_period ON ar_subledger (period);
CREATE INDEX IF NOT EXISTS idx_ar_reference ON ar_subledger (reference_id, reference_type);
CREATE INDEX IF NOT EXISTS idx_restructured_period ON restructured_payments (period);
CREATE INDEX IF NOT EXISTS idx_fees_period ON delinquency_fees (period);
CREATE INDEX IF NOT EXISTS idx_refunds_period ON refunds (period);
CREATE INDEX IF NOT EXISTS idx_chargeoffs_period ON charge_offs (period);
