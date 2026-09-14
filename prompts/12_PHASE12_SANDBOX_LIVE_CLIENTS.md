# Phase 12 — Sandbox-Capable Live Clients, Disabled by Default

## Objective

Implement provider HTTP clients behind a dedicated live-integration boundary while making accidental external execution impossible from ordinary application configuration.

## Non-negotiable constraints

- `app/integrations/live/` is the only application package allowed to import the HTTP client.
- Domain, services, persistence, and pure platform adapters remain network-free.
- Every live client requires both an explicitly injected `SandboxExecutionPermit` and an explicitly injected `httpx.AsyncClient`.
- Phase 12 exposes no production execution permit.
- No client creates its own default HTTP transport.
- Provider hosts are fixed allowlisted HTTPS hosts; IDs/API versions are validated before URL construction.
- Access tokens/secrets are never placed in exception messages.
- Response bodies are never included in provider exceptions.
- Tests use `httpx.MockTransport` only.
- No real credential, webhook registration, OAuth grant, provider request, or production reply is performed.
- Existing publication uncertainty semantics remain authoritative: a provider-call exception after dispatch begins is not blindly retried.

## Verified provider operations (snapshot 2026-09-10)

- Facebook Page comment reply: `POST /{comment-id}/comments` on Graph API with message text.
- Instagram comment reply: `POST /{IG_COMMENT_ID}/replies` using the Instagram/Meta Graph surface.
- Telegram message/reply: Bot API `sendMessage`, using `chat_id`, `text`, and `reply_parameters.message_id` when replying.
- YouTube comment ingestion: `commentThreads.list`.
- YouTube reply: `comments.insert` with `part=snippet`, `snippet.parentId`, and `snippet.textOriginal`.

Meta Graph API version remains configuration and is not silently guessed by a client.

## Exit criteria

- Ruff, Mypy, and Pytest PASS on final head.
- MockTransport tests prove exact method/path/body/header semantics without external network.
- Missing execution permit fails before an HTTP request.
- Provider errors are bounded and redaction-safe.
- Security regression permits hardcoded provider URLs only under `app/integrations/live/` and only for approved hosts.
- No production activation capability is added.
- PR targets Phase 11, not `main`.