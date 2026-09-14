from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.domain.classification import (
    ClassificationDecision,
    ClassificationReason,
    ClassificationRoute,
)
from app.domain.events import NormalizedInboundEvent, Platform
from app.domain.faq import (
    FAQEntryStatus,
    FAQResolutionReason,
    FAQResolutionStatus,
)
from app.persistence.classification_repository import ClassificationRepository
from app.persistence.faq_repository import FAQRepository
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.faq import FAQNotEligible, FAQService
from app.services.ingestion import IngestionService


def _build(
    tmp_path: Path,
) -> tuple[
    SQLiteDatabase,
    DurableRepository,
    ClassificationRepository,
    FAQRepository,
    FAQService,
]:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    events = DurableRepository(database)
    classifications = ClassificationRepository(database)
    faqs = FAQRepository(database)
    service = FAQService(classifications=classifications, faqs=faqs)
    return database, events, classifications, faqs, service


def _event(
    events: DurableRepository,
    *,
    key: str,
    platform: Platform = Platform.FACEBOOK,
) -> str:
    return IngestionService(events).ingest_event(
        NormalizedInboundEvent(
            platform=platform,
            external_event_key=key,
            text="سؤال تشغيلي تجريبي",
        )
    ).event.id


def _faq_classification(
    classifications: ClassificationRepository,
    *,
    event_id: str,
    faq_key: str,
) -> str:
    result = classifications.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.FAQ,
            reasons=(ClassificationReason.CONFIDENT_FAQ,),
            faq_key=faq_key,
        ),
        religious_possible=False,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    )
    return result.id


def _supervisor_classification(
    classifications: ClassificationRepository,
    *,
    event_id: str,
) -> str:
    result = classifications.create_for_event(
        event_id=event_id,
        decision=ClassificationDecision(
            route=ClassificationRoute.SUPERVISOR,
            reasons=(ClassificationReason.EXPLICIT_SUPERVISOR,),
        ),
        religious_possible=False,
        confidence=0.99,
        adapter_name="test-classifier",
        adapter_version="1",
    )
    return result.id


def _approved_entry(
    faqs: FAQRepository,
    *,
    key: str = "registration.status",
    answer: str = "Approved synthetic answer v1",
    source: str = "fixture://approved/registration/v1",
) -> str:
    return faqs.create_version(
        faq_key=key,
        answer_text=answer,
        source_ref=source,
        approved_by="test-approver",
        approved_at=datetime(2026, 9, 10, 7, 0, tzinfo=UTC),
    ).id


def test_fresh_database_has_no_seed_faq_entries(tmp_path: Path) -> None:
    _, _, _, faqs, _ = _build(tmp_path)
    assert faqs.count_entries() == 0


def test_exact_active_key_resolves_only_approved_answer(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="faq-success")
    classification_id = _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )
    entry_id = _approved_entry(faqs)

    result = service.resolve(event_id)

    assert result.resolution.status is FAQResolutionStatus.RESOLVED
    assert result.resolution.reason is FAQResolutionReason.APPROVED_ENTRY
    assert result.resolution.classification_result_id == classification_id
    assert result.resolution.faq_entry_id == entry_id
    assert result.entry is not None
    assert result.entry.version == 1
    assert result.entry.source_ref == "fixture://approved/registration/v1"
    assert result.answer_text == "Approved synthetic answer v1"


def test_missing_key_requires_supervisor_and_has_no_answer(tmp_path: Path) -> None:
    _, events, classifications, _, service = _build(tmp_path)
    event_id = _event(events, key="faq-missing")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="missing.key",
    )

    result = service.resolve(event_id)

    assert result.resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED
    assert result.resolution.reason is FAQResolutionReason.ENTRY_NOT_FOUND
    assert result.resolution.faq_entry_id is None
    assert result.answer_text is None


def test_disabled_key_requires_supervisor_and_has_no_answer(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="faq-disabled")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )
    _approved_entry(faqs)
    disabled = faqs.disable_active("registration.status")
    assert disabled is not None
    assert disabled.status is FAQEntryStatus.DISABLED

    result = service.resolve(event_id)

    assert result.resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED
    assert result.resolution.reason is FAQResolutionReason.ENTRY_DISABLED
    assert result.answer_text is None


def test_exact_lookup_never_fuzzy_matches_similar_key(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    _approved_entry(faqs, key="registration.status")
    event_id = _event(events, key="faq-exact-only")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration",
    )

    result = service.resolve(event_id)

    assert result.resolution.reason is FAQResolutionReason.ENTRY_NOT_FOUND
    assert result.answer_text is None


def test_non_faq_classification_is_ineligible(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="not-faq")
    _supervisor_classification(classifications, event_id=event_id)

    with pytest.raises(FAQNotEligible, match="durable FAQ classification"):
        service.resolve(event_id)

    assert faqs.count_resolutions() == 0


def test_invalid_faq_key_requires_supervisor_without_substitution(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    _approved_entry(faqs, key="registration.status")
    event_id = _event(events, key="invalid-faq-key")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration status",
    )

    result = service.resolve(event_id)

    assert result.resolution.status is FAQResolutionStatus.SUPERVISOR_REQUIRED
    assert result.resolution.reason is FAQResolutionReason.INVALID_FAQ_KEY
    assert result.answer_text is None


def test_new_version_preserves_historical_content_and_becomes_only_active(
    tmp_path: Path,
) -> None:
    _, _, _, faqs, _ = _build(tmp_path)
    first = faqs.create_version(
        faq_key="registration.status",
        answer_text="Synthetic answer v1",
        source_ref="fixture://v1",
        approved_by="approver-a",
        approved_at=datetime(2026, 9, 10, 7, 0, tzinfo=UTC),
    )
    second = faqs.create_version(
        faq_key="registration.status",
        answer_text="Synthetic answer v2",
        source_ref="fixture://v2",
        approved_by="approver-b",
        approved_at=datetime(2026, 9, 10, 8, 0, tzinfo=UTC),
    )

    versions = faqs.list_versions("registration.status")

    assert [entry.version for entry in versions] == [1, 2]
    assert versions[0].id == first.id
    assert versions[0].answer_text == "Synthetic answer v1"
    assert versions[0].source_ref == "fixture://v1"
    assert versions[0].status is FAQEntryStatus.DISABLED
    assert versions[1].id == second.id
    assert versions[1].answer_text == "Synthetic answer v2"
    assert versions[1].status is FAQEntryStatus.ACTIVE
    assert sum(entry.status is FAQEntryStatus.ACTIVE for entry in versions) == 1


def test_resolved_answer_becomes_unavailable_after_entry_revocation(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="faq-revoked-after-resolution")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )
    _approved_entry(faqs)

    first = service.resolve(event_id)
    assert first.answer_text == "Approved synthetic answer v1"

    faqs.disable_active("registration.status")
    second = service.resolve(event_id)

    assert second.resolution.id == first.resolution.id
    assert second.entry is not None
    assert second.entry.status is FAQEntryStatus.DISABLED
    assert second.answer_text is None


def test_duplicate_resolution_reuses_one_durable_row(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="faq-duplicate")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )
    _approved_entry(faqs)

    first = service.resolve(event_id)
    second = service.resolve(event_id)

    assert first.resolution.id == second.resolution.id
    assert faqs.count_resolutions() == 1


def test_concurrent_duplicate_resolution_creates_one_row(tmp_path: Path) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    event_id = _event(events, key="faq-race")
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )
    _approved_entry(faqs)

    with ThreadPoolExecutor(max_workers=8) as executor:
        ids = list(executor.map(lambda _: service.resolve(event_id).resolution.id, range(20)))

    assert len(set(ids)) == 1
    assert faqs.count_resolutions() == 1


@pytest.mark.parametrize("platform", list(Platform))
def test_all_v1_platforms_share_exact_faq_resolution_semantics(
    tmp_path: Path,
    platform: Platform,
) -> None:
    _, events, classifications, faqs, service = _build(tmp_path)
    _approved_entry(faqs)
    event_id = _event(events, key=f"faq-{platform.value}", platform=platform)
    _faq_classification(
        classifications,
        event_id=event_id,
        faq_key="registration.status",
    )

    result = service.resolve(event_id)

    assert result.resolution.status is FAQResolutionStatus.RESOLVED
    assert result.answer_text == "Approved synthetic answer v1"


def test_faq_resolution_foreign_keys_are_enforced(tmp_path: Path) -> None:
    database, _, _, _, _ = _build(tmp_path)

    with database.connect() as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(
            """
            INSERT INTO faq_resolutions (
                id, event_id, classification_result_id, faq_entry_id,
                status, reason_code, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bad-resolution",
                "missing-event",
                "missing-classification",
                None,
                "supervisor_required",
                "entry_not_found",
                "2026-09-10T07:00:00+00:00",
            ),
        )
