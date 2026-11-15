CREATE TABLE IF NOT EXISTS raw_vault.audit_batch (
    batch_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    batch_id CHAR(64) NOT NULL,
    pipeline_name VARCHAR(150) NOT NULL,
    source_name VARCHAR(150) NOT NULL,

    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',

    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMPTZ,

    files_count INTEGER NOT NULL DEFAULT 0,
    records_read BIGINT NOT NULL DEFAULT 0,

    inserted_records JSONB NOT NULL DEFAULT '{}'::JSONB,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,

    error_message TEXT,

    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT chk_audit_batch_status
        CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED')),

    CONSTRAINT chk_audit_batch_files
        CHECK (files_count >= 0),

    CONSTRAINT chk_audit_batch_records
        CHECK (records_read >= 0),

    CONSTRAINT chk_audit_batch_dates
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);

CREATE INDEX IF NOT EXISTS idx_audit_batch_id
    ON raw_vault.audit_batch (batch_id);

CREATE INDEX IF NOT EXISTS idx_audit_batch_status
    ON raw_vault.audit_batch (status);

CREATE INDEX IF NOT EXISTS idx_audit_batch_started_at
    ON raw_vault.audit_batch (started_at DESC);
