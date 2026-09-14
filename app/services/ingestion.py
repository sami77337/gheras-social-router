"""Persist-first ingestion service."""

from __future__ import annotations

from app.domain.events import IngestionResult, NormalizedInboundEvent
from app.persistence.repositories import DurableRepository


class IngestionService:
    """Accept normalized events using persist-first, idempotent semantics."""

    def __init__(self, repository: DurableRepository) -> None:
        self.repository = repository

    def ingest_event(self, event: NormalizedInboundEvent) -> IngestionResult:
        """Persist a new event or return the already accepted event."""

        persisted, created = self.repository.ingest(event)
        return IngestionResult(event=persisted, created=created)
