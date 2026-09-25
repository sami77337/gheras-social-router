# Phase 22 — Representative Shadow Execution Orchestration\n\n## Status\n\n**ENGINEERING PREPARATION: PASS. PRIVATE-CONTENT PROVIDER PROCESSING HAS NOT BEEN EXECUTED.**\n\nPhase 22 prepares the final local orchestration needed to execute HG-09 once a real representative corpus and approved local credentials are available.\n\n## Preconditions for a real run\n\nA real run requires all of the following:\n\n- a private replay JSONL corpus produced by Phase 20/21;\n- an explicit evaluator version for this evidence run;\n- an explicitly selected model ID;\n- a local GHERAS_OPENAI_API_KEY environment variable;\n- a fresh local SQLite evidence path;\n- an operator-selected --max-model-decisions ceiling;\n- explicit --confirm-private-content-provider-processing;\n- optionally, a private approved FAQ snapshot when FAQ behavior is part of the evaluated release.\n\nNo credential belongs in Git, command history, screenshots, evidence JSON, or chat.\n\n## Approved FAQ snapshot\n\nThe optional FAQ snapshot is UTF-8 JSONL with exactly: faq_key, answer_text, source_ref, approved_by, approved_at with timezone.\n\nThe complete file is validated before database seeding. Duplicate JSON keys, duplicate FAQ keys, unknown/missing fields, naive timestamps, excessive file size, and excessive entry count fail closed.\n\nEvidence records only the exact snapshot SHA-256, byte size, entry count, and digest of the FAQ key set. It does not emit approved answer text or approver names.\n\n## Execution boundary\n\nAt execution time, the local operator sets GHERAS_OPENAI_API_KEY and runs scripts/ops_run_representative_shadow.py with the private corpus, fresh database, evidence output, evaluator version, approved model, explicit model-decision ceiling, and --confirm-private-content-provider-processing.\n\nBefore the first model request, the command validates the complete replay corpus, calculates a conservative worst-case ceiling of two model decisions per presented record, refuses execution if that exceeds --max-model-decisions, requires a fresh database, requires explicit private-content processing acknowledgement, and obtains the API key only from the local environment.\n\nThe execution uses the existing strict OpenAIResponsesDecisionClient, which keeps store:false, disables tools, and accepts only the moderation/classification structured schemas.\n\n## Evidence\n\nThe content-free evidence binds the local Git release SHA, selected model ID, evaluator version, exact corpus SHA-256 and record count, optional approved FAQ snapshot digest/count, and Phase 20 aggregate Shadow evidence.\n\nNo publication client is installed and no publishing dispatcher is called.\n\n## Remaining Human Gate\n\nEngineering readiness does not authorize a real run. Sending private corpus text to an external model provider is an explicit Human Gate because it is an external data-processing action and can incur usage cost.\n\nAfter execution, aggregate results and anomaly cases must still be reviewed under STAGING_SHADOW_EVALUATION_PROTOCOL.md; only then may HG-09 receive PASS/HOLD/REJECT.\n
## Continuation hardening

After rebasing the Phase 22 stack onto the hardened Phase 21 head, a continuation review added three fail-closed improvements before renewing the engineering lock:

- private FAQ entry `repr` output is content-redacted;
- `evaluator_version` is validated as a bounded evidence namespace before runtime/database creation;
- the final content-free evidence file is written atomically through a temporary file.

Regression coverage verifies FAQ-entry redaction and rejects invalid evaluator namespaces before any database or model-client activity. The stack was then resynchronized onto the final hardened Phase 21 head, including no-loss Meta reply traversal and fail-closed conflicting provider-comment identity handling, and the complete combined stack was revalidated.

## Engineering lock evidence

- PR: #51 (stacked on hardened Phase 21; open/unmerged)
- synchronized Phase 21 base SHA: `f16c8e966a98f4eab850eb0293d720af08c83c6d`
- reviewed code head before this documentation lock: `03d85b88fb27082bdda1bd61f02179c37590f9dc`
- full CI run: `36174234191` — PASS
- production lock metadata: PASS
- dependency consistency: PASS
- production dependency audit: PASS
- build-tool audit: PASS
- CI/development audit: PASS
- production-environment reproduction: PASS
- Ruff: PASS
- Mypy: PASS
- Pytest: PASS
- submitted independent review: none at lock time
- real OpenAI/provider execution: not performed
- private representative corpus processing: not performed
