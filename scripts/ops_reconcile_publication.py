"""Record one provider-verified publication reconciliation decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.persistence.reconciliation_repository import PublicationReconciliationRepository
from app.persistence.sqlite import SQLiteDatabase
from app.services.reconciliation import PublicationReconciliationService


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--action-id", required=True)
    parser.add_argument("--operator-ref", required=True)
    parser.add_argument("--evidence-ref", required=True)
    parser.add_argument("--reconciliation-key", required=True)
    parser.add_argument(
        "--provider-outcome-verified",
        action="store_true",
        required=True,
        help="Required acknowledgment that provider-side outcome was independently verified",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database",
        required=True,
        type=Path,
        help="Existing Gheras SQLite database file",
    )
    subparsers = parser.add_subparsers(dest="decision", required=True)

    succeeded = subparsers.add_parser("confirmed-succeeded")
    _add_common_arguments(succeeded)
    succeeded.add_argument("--external-result-id", required=True)

    not_sent = subparsers.add_parser("confirmed-not-sent")
    _add_common_arguments(not_sent)

    args = parser.parse_args()
    if not args.provider_outcome_verified:
        parser.error("provider-side outcome verification is required")

    service = PublicationReconciliationService(
        PublicationReconciliationRepository(SQLiteDatabase(args.database))
    )
    if args.decision == "confirmed-succeeded":
        record, action = service.confirm_succeeded(
            action_id=args.action_id,
            operator_ref=args.operator_ref,
            evidence_ref=args.evidence_ref,
            external_reconciliation_key=args.reconciliation_key,
            external_result_id=args.external_result_id,
        )
    else:
        record, action = service.confirm_not_sent(
            action_id=args.action_id,
            operator_ref=args.operator_ref,
            evidence_ref=args.evidence_ref,
            external_reconciliation_key=args.reconciliation_key,
        )

    payload = {
        "action_id": action.id,
        "decision": record.decision.value,
        "new_status": action.status,
        "prior_status": record.prior_status.value,
        "reconciliation_id": record.id,
    }
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
