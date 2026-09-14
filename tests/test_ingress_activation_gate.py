from __future__ import annotations

from pathlib import Path

import pytest

from app.api.integrations import IngressRuntime, build_ingress_router
from app.ingress.common import ExactIngestionCollector
from app.ingress.meta import MetaWebhookIngress
from app.ingress.telegram import TelegramWebhookIngress
from app.integrations.live.activation import ExternalIntegrationDisabled
from app.persistence.repositories import DurableRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.ingestion import IngestionService


def test_ingress_router_construction_requires_explicit_sandbox_capability(
    tmp_path: Path,
) -> None:
    database = SQLiteDatabase(tmp_path / "router.db")
    database.initialize()
    collector = ExactIngestionCollector(IngestionService(DurableRepository(database)))
    runtime = IngressRuntime(
        meta=MetaWebhookIngress(collector=collector, app_secret="meta-secret"),
        telegram=TelegramWebhookIngress(
            collector=collector,
            webhook_secret="Telegram_Secret-123",
        ),
        meta_verify_token="meta-verify-token",
    )

    with pytest.raises(ExternalIntegrationDisabled, match="permit is required"):
        build_ingress_router(runtime)
