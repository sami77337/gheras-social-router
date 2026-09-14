"""Read-only, content-free evidence reporting for one Shadow evaluator version."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from app.persistence.sqlite import SQLiteDatabase


@dataclass(frozen=True, slots=True)
class ShadowEvidenceReport:
    """Aggregate evidence for exactly one immutable Shadow evaluator version."""

    evaluator_version: str
    total_evaluated: int
    first_created_at: datetime
    last_created_at: datetime
    by_platform: dict[str, int]
    by_route: dict[str, int]
    by_outcome: dict[str, int]
    evidence_sha256: str


class ShadowEvidenceService:
    """Generate deterministic counts-only Shadow evidence without reading content columns."""

    def __init__(self, database: SQLiteDatabase) -> None:
        self.database = database

    @staticmethod
    def _version(value: str) -> str:
        version = value.strip()
        if not version or len(version) > 80 or any(char.isspace() for char in version):
            raise ValueError("evaluator_version must be a compact identifier up to 80 characters")
        return version

    @staticmethod
    def _digest_payload(
        *,
        evaluator_version: str,
        total_evaluated: int,
        first_created_at: str,
        last_created_at: str,
        by_platform: dict[str, int],
        by_route: dict[str, int],
        by_outcome: dict[str, int],
    ) -> str:
        payload = {
            "by_outcome": by_outcome,
            "by_platform": by_platform,
            "by_route": by_route,
            "evaluator_version": evaluator_version,
            "first_created_at": first_created_at,
            "last_created_at": last_created_at,
            "total_evaluated": total_evaluated,
        }
        encoded = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def report(self, evaluator_version: str) -> ShadowEvidenceReport:
        """Return reconciled aggregates for one evaluator version.

        Missing evidence fails closed rather than producing a zero-count pseudo-result.
        """

        version = self._version(evaluator_version)
        with self.database.connect_readonly() as connection:
            total_row = connection.execute(
                """
                SELECT COUNT(*) AS count, MIN(created_at) AS first_created_at,
                       MAX(created_at) AS last_created_at
                FROM shadow_evaluations
                WHERE evaluator_version = ?
                """,
                (version,),
            ).fetchone()
            platform_rows = connection.execute(
                """
                SELECT platform, COUNT(*) AS count
                FROM shadow_evaluations
                WHERE evaluator_version = ?
                GROUP BY platform ORDER BY platform
                """,
                (version,),
            ).fetchall()
            route_rows = connection.execute(
                """
                SELECT observed_route, COUNT(*) AS count
                FROM shadow_evaluations
                WHERE evaluator_version = ?
                GROUP BY observed_route ORDER BY observed_route
                """,
                (version,),
            ).fetchall()
            outcome_rows = connection.execute(
                """
                SELECT outcome, COUNT(*) AS count
                FROM shadow_evaluations
                WHERE evaluator_version = ?
                GROUP BY outcome ORDER BY outcome
                """,
                (version,),
            ).fetchall()

        total = int(total_row["count"]) if total_row is not None else 0
        if total == 0 or total_row is None:
            raise LookupError(f"no Shadow evidence for evaluator version {version}")
        first_raw = total_row["first_created_at"]
        last_raw = total_row["last_created_at"]
        if first_raw is None or last_raw is None:
            raise RuntimeError("non-empty Shadow evidence is missing timestamps")

        by_platform = {str(row["platform"]): int(row["count"]) for row in platform_rows}
        by_route = {
            (str(row["observed_route"]) if row["observed_route"] is not None else "none"):
            int(row["count"])
            for row in route_rows
        }
        by_outcome = {str(row["outcome"]): int(row["count"]) for row in outcome_rows}
        if not (
            sum(by_platform.values())
            == sum(by_route.values())
            == sum(by_outcome.values())
            == total
        ):
            raise RuntimeError("Shadow aggregate counts do not reconcile")

        first_text = str(first_raw)
        last_text = str(last_raw)
        return ShadowEvidenceReport(
            evaluator_version=version,
            total_evaluated=total,
            first_created_at=datetime.fromisoformat(first_text),
            last_created_at=datetime.fromisoformat(last_text),
            by_platform=by_platform,
            by_route=by_route,
            by_outcome=by_outcome,
            evidence_sha256=self._digest_payload(
                evaluator_version=version,
                total_evaluated=total,
                first_created_at=first_text,
                last_created_at=last_text,
                by_platform=by_platform,
                by_route=by_route,
                by_outcome=by_outcome,
            ),
        )
