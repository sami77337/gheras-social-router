# Phase 6 — Mock-First Platform Adapters

## Objective

Create provider-specific adapter modules for Facebook, Instagram, Telegram, and YouTube without using real credentials or network endpoints.

## Boundary rule

This phase implements typed provider DTO normalization and injectable outbound client protocols. It does not implement live webhook authentication, polling, OAuth, token refresh, or production HTTP clients.

## Inbound requirements

Each platform adapter must:

- validate required stable identifiers;
- normalize into the shared `NormalizedInboundEvent`;
- choose a deterministic event key that collapses redelivery of the same logical comment/message;
- preserve Arabic/Unicode text without semantic rewriting;
- never invent missing IDs or content;
- raise a normalized `AdapterPayloadError` for malformed inputs.

## Outbound requirements

Provider-specific reply publishers may delegate only to an injected client protocol. Production network clients are forbidden in this phase. The common router treats `external_comment_id` as an opaque platform-owned reply target.

Telegram additionally implements the `SupervisorTransportAdapter` boundary using an injected client protocol and a deterministic minimal human-review message.

## Safety

- no tokens, secrets, OAuth, webhooks, polling, or production URLs;
- no raw provider payload persistence;
- no domain-layer vendor imports;
- no user-facing reply generation;
- no fatwa generation;
- malformed provider data fails closed.

## Tests

Cover all four platforms, Arabic/Unicode preservation, malformed IDs, duplicate normalization/ingestion, reply delegation with fake clients, Telegram supervisor dispatch with a fake client, and absence of real network libraries from provider modules.

## Gates

- `ruff check app tests`
- `mypy app`
- `pytest`
- independent review before promotion
