"""Additive operational schema for durable publication reconciliation."""

OPERATIONS_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS publication_reconciliations (
    id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    prior_status TEXT NOT NULL CHECK (
        prior_status IN ('dispatching', 'uncertain')
    ),
    decision TEXT NOT NULL CHECK (
        decision IN ('confirmed_succeeded', 'confirmed_not_sent')
    ),
    operator_ref TEXT NOT NULL CHECK (length(trim(operator_ref)) > 0),
    evidence_ref TEXT NOT NULL CHECK (length(trim(evidence_ref)) > 0),
    external_reconciliation_key TEXT NOT NULL UNIQUE CHECK (
        length(trim(external_reconciliation_key)) > 0
    ),
    external_result_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (action_id) REFERENCES outbound_actions(id) ON DELETE CASCADE,
    CHECK (
        (
            decision = 'confirmed_succeeded'
            AND external_result_id IS NOT NULL
            AND length(trim(external_result_id)) > 0
        )
        OR
        (
            decision = 'confirmed_not_sent'
            AND external_result_id IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_publication_reconciliations_action
ON publication_reconciliations (action_id, created_at);
"""
