"""SQLite schema for Gheras Social Router durable processing."""

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS inbound_events (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL CHECK (
        platform IN ('facebook', 'instagram', 'telegram', 'youtube')
    ),
    external_event_key TEXT NOT NULL,
    external_event_id TEXT,
    external_comment_id TEXT,
    external_post_id TEXT,
    author_id TEXT,
    text TEXT,
    media_json TEXT,
    correlation_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN (
            'received',
            'processing',
            'waiting_human',
            'completed',
            'failed_retryable',
            'failed_terminal'
        )
    ),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    next_retry_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, external_event_key)
);

CREATE INDEX IF NOT EXISTS idx_inbound_events_status_retry
ON inbound_events (status, next_retry_at);

CREATE TABLE IF NOT EXISTS processing_attempts (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    started_at TEXT NOT NULL,
    finished_at TEXT,
    outcome TEXT,
    error_code TEXT,
    error_message TEXT,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    UNIQUE (event_id, attempt_number)
);

CREATE INDEX IF NOT EXISTS idx_processing_attempts_event
ON processing_attempts (event_id, attempt_number);

CREATE TABLE IF NOT EXISTS outbound_actions (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (
        platform IN ('facebook', 'instagram', 'telegram', 'youtube')
    ),
    action_type TEXT NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    external_result_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_outbound_actions_event
ON outbound_actions (event_id, created_at);

CREATE TABLE IF NOT EXISTS moderation_results (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    disposition TEXT NOT NULL CHECK (
        disposition IN ('allow_routing', 'human_review', 'block_routing')
    ),
    reason_codes_json TEXT NOT NULL,
    categories_json TEXT NOT NULL,
    adapter_name TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_moderation_results_disposition
ON moderation_results (disposition, created_at);

CREATE TABLE IF NOT EXISTS moderation_human_reviews (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    moderation_result_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'resolved')),
    decision TEXT CHECK (
        decision IS NULL OR decision IN ('allow_routing', 'block_routing')
    ),
    reviewer_ref TEXT,
    external_review_key TEXT UNIQUE,
    created_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    FOREIGN KEY (moderation_result_id)
        REFERENCES moderation_results(id) ON DELETE CASCADE,
    CHECK (
        (
            status = 'pending'
            AND decision IS NULL
            AND reviewer_ref IS NULL
            AND external_review_key IS NULL
            AND resolved_at IS NULL
        )
        OR
        (
            status = 'resolved'
            AND decision IS NOT NULL
            AND reviewer_ref IS NOT NULL
            AND length(trim(reviewer_ref)) > 0
            AND external_review_key IS NOT NULL
            AND length(trim(external_review_key)) > 0
            AND resolved_at IS NOT NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_moderation_human_reviews_status
ON moderation_human_reviews (status, created_at);

CREATE TABLE IF NOT EXISTS classification_results (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    route TEXT NOT NULL CHECK (route IN ('FAQ', 'SUPERVISOR', 'FATWA')),
    reason_codes_json TEXT NOT NULL,
    faq_key TEXT,
    religious_possible INTEGER CHECK (
        religious_possible IS NULL OR religious_possible IN (0, 1)
    ),
    confidence REAL CHECK (
        confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)
    ),
    adapter_name TEXT NOT NULL,
    adapter_version TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    CHECK (
        (route = 'FAQ' AND faq_key IS NOT NULL)
        OR (route != 'FAQ' AND faq_key IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_classification_results_route
ON classification_results (route, created_at);

CREATE TABLE IF NOT EXISTS faq_entries (
    id TEXT PRIMARY KEY,
    faq_key TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    answer_text TEXT NOT NULL CHECK (length(trim(answer_text)) > 0),
    source_ref TEXT NOT NULL CHECK (length(trim(source_ref)) > 0),
    status TEXT NOT NULL CHECK (status IN ('active', 'disabled')),
    approved_by TEXT NOT NULL CHECK (length(trim(approved_by)) > 0),
    approved_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (faq_key, version)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_faq_entries_one_active_key
ON faq_entries (faq_key) WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_faq_entries_key_version
ON faq_entries (faq_key, version DESC);

CREATE TABLE IF NOT EXISTS faq_resolutions (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    classification_result_id TEXT NOT NULL UNIQUE,
    faq_entry_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN ('resolved', 'supervisor_required')
    ),
    reason_code TEXT NOT NULL CHECK (
        reason_code IN (
            'approved_entry',
            'entry_not_found',
            'entry_disabled',
            'invalid_faq_key'
        )
    ),
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    FOREIGN KEY (classification_result_id)
        REFERENCES classification_results(id) ON DELETE CASCADE,
    FOREIGN KEY (faq_entry_id) REFERENCES faq_entries(id),
    CHECK (
        (
            status = 'resolved'
            AND reason_code = 'approved_entry'
            AND faq_entry_id IS NOT NULL
        )
        OR
        (
            status = 'supervisor_required'
            AND reason_code != 'approved_entry'
            AND faq_entry_id IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_faq_resolutions_status
ON faq_resolutions (status, created_at);

CREATE TABLE IF NOT EXISTS supervisor_escalations (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL CHECK (
        source IN ('classification', 'faq_resolution')
    ),
    classification_result_id TEXT,
    faq_resolution_id TEXT,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending_dispatch',
            'awaiting_response',
            'responded',
            'cancelled'
        )
    ),
    dispatch_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
        dispatch_attempt_count >= 0
    ),
    transport_name TEXT,
    external_thread_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    FOREIGN KEY (classification_result_id)
        REFERENCES classification_results(id) ON DELETE CASCADE,
    FOREIGN KEY (faq_resolution_id)
        REFERENCES faq_resolutions(id) ON DELETE CASCADE,
    CHECK (
        (
            source = 'classification'
            AND classification_result_id IS NOT NULL
            AND faq_resolution_id IS NULL
        )
        OR
        (
            source = 'faq_resolution'
            AND classification_result_id IS NULL
            AND faq_resolution_id IS NOT NULL
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_supervisor_external_thread
ON supervisor_escalations (external_thread_id)
WHERE external_thread_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_supervisor_escalations_status
ON supervisor_escalations (status, created_at);

CREATE TABLE IF NOT EXISTS supervisor_responses (
    id TEXT PRIMARY KEY,
    escalation_id TEXT NOT NULL UNIQUE,
    external_response_key TEXT NOT NULL UNIQUE,
    supervisor_ref TEXT NOT NULL CHECK (length(trim(supervisor_ref)) > 0),
    response_text TEXT NOT NULL CHECK (length(trim(response_text)) > 0),
    received_at TEXT NOT NULL,
    FOREIGN KEY (escalation_id)
        REFERENCES supervisor_escalations(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_supervisor_responses_received
ON supervisor_responses (received_at);

CREATE TABLE IF NOT EXISTS fatwa_bridge_requests (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    classification_result_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK (
        status IN (
            'pending_dispatch',
            'awaiting_result',
            'approved_result',
            'rejected',
            'cancelled'
        )
    ),
    dispatch_attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (
        dispatch_attempt_count >= 0
    ),
    bridge_name TEXT,
    external_case_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    FOREIGN KEY (classification_result_id)
        REFERENCES classification_results(id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_fatwa_bridge_external_case
ON fatwa_bridge_requests (external_case_id)
WHERE external_case_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_fatwa_bridge_requests_status
ON fatwa_bridge_requests (status, created_at);

CREATE TABLE IF NOT EXISTS fatwa_bridge_results (
    id TEXT PRIMARY KEY,
    request_id TEXT NOT NULL UNIQUE,
    external_result_key TEXT NOT NULL UNIQUE,
    outcome TEXT NOT NULL CHECK (outcome IN ('approved', 'rejected')),
    answer_text TEXT,
    approved_by TEXT,
    source_ref TEXT NOT NULL CHECK (length(trim(source_ref)) > 0),
    received_at TEXT NOT NULL,
    FOREIGN KEY (request_id)
        REFERENCES fatwa_bridge_requests(id) ON DELETE CASCADE,
    CHECK (
        (
            outcome = 'approved'
            AND answer_text IS NOT NULL
            AND length(trim(answer_text)) > 0
            AND approved_by IS NOT NULL
            AND length(trim(approved_by)) > 0
        )
        OR
        (
            outcome = 'rejected'
            AND answer_text IS NULL
            AND approved_by IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_fatwa_bridge_results_received
ON fatwa_bridge_results (received_at);

CREATE TABLE IF NOT EXISTS shadow_evaluations (
    id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL CHECK (length(trim(correlation_id)) > 0),
    platform TEXT NOT NULL CHECK (
        platform IN ('facebook', 'instagram', 'telegram', 'youtube')
    ),
    evaluator_version TEXT NOT NULL CHECK (
        length(trim(evaluator_version)) > 0
        AND length(evaluator_version) <= 80
    ),
    observed_route TEXT CHECK (
        observed_route IS NULL OR observed_route IN ('FAQ', 'SUPERVISOR', 'FATWA')
    ),
    outcome TEXT NOT NULL CHECK (
        outcome IN (
            'would_publish',
            'would_wait_human',
            'would_route_fatwa',
            'not_ready',
            'blocked'
        )
    ),
    source_kind TEXT CHECK (
        source_kind IS NULL OR source_kind IN ('faq', 'supervisor', 'fatwa')
    ),
    evidence_id TEXT,
    proposed_text TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (event_id) REFERENCES inbound_events(id) ON DELETE CASCADE,
    UNIQUE (event_id, evaluator_version),
    CHECK (
        (
            outcome = 'would_publish'
            AND source_kind IS NOT NULL
            AND evidence_id IS NOT NULL
            AND length(trim(evidence_id)) > 0
            AND proposed_text IS NOT NULL
            AND length(trim(proposed_text)) > 0
        )
        OR
        (
            outcome != 'would_publish'
            AND source_kind IS NULL
            AND evidence_id IS NULL
            AND proposed_text IS NULL
        )
    )
);

CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_outcome
ON shadow_evaluations (outcome, created_at);

CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_platform
ON shadow_evaluations (platform, created_at);

CREATE INDEX IF NOT EXISTS idx_shadow_evaluations_route
ON shadow_evaluations (observed_route, created_at);
"""
