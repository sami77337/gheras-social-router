from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
from dataclasses import asdict
from pathlib import Path

import httpx

from app.integrations.live.activation import issue_sandbox_execution_permit
from app.integrations.live.openai import OpenAIResponsesDecisionClient
from app.operations.replay import load_replay_corpus
from app.operations.representative_shadow import execute_representative_shadow


def _git_head() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def _run(args: argparse.Namespace, api_key: str) -> dict[str, object]:
    corpus = load_replay_corpus(args.corpus)
    maximum_decisions = corpus.manifest.record_count * 2
    if maximum_decisions > args.max_model_decisions:
        raise SystemExit(
            "corpus worst-case model-decision count exceeds --max-model-decisions"
        )

    permit = issue_sandbox_execution_permit(purpose="sandbox_validation")
    async with httpx.AsyncClient(timeout=60.0) as http:
        client = OpenAIResponsesDecisionClient(
            http=http,
            permit=permit,
            api_key=api_key,
            model=args.model,
        )
        evidence = await execute_representative_shadow(
            corpus_path=args.corpus,
            database_path=args.database,
            permit=permit,
            moderation_client=client,
            classification_client=client,
            evaluator_version=args.evaluator_version,
            release_sha=_git_head(),
            model_id=args.model,
            faq_snapshot_path=args.faq_snapshot,
        )
    return asdict(evidence)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run a private representative corpus through non-publishing OpenAI Shadow "
            "evaluation and write content-free evidence."
        )
    )
    parser.add_argument("corpus", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--evidence-output", type=Path, required=True)
    parser.add_argument("--evaluator-version", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--faq-snapshot", type=Path)
    parser.add_argument("--max-model-decisions", type=int, required=True)
    parser.add_argument(
        "--confirm-private-content-provider-processing",
        action="store_true",
        help=(
            "Required explicit acknowledgement that private corpus text will be sent "
            "to the configured model provider for moderation/classification only."
        ),
    )
    args = parser.parse_args()

    if not args.confirm_private_content_provider_processing:
        parser.error("--confirm-private-content-provider-processing is required")
    if args.max_model_decisions <= 0:
        parser.error("--max-model-decisions must be positive")
    if args.evidence_output.exists():
        parser.error("--evidence-output must not already exist")

    api_key = os.environ.get("GHERAS_OPENAI_API_KEY")
    if not api_key:
        raise SystemExit("GHERAS_OPENAI_API_KEY is not configured")

    evidence = asyncio.run(_run(args, api_key))
    args.evidence_output.parent.mkdir(parents=True, exist_ok=True)
    args.evidence_output.write_text(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": "SHADOW_EXECUTION_COMPLETE_REVIEW_REQUIRED",
                "evidence_output": str(args.evidence_output),
                "corpus_sha256": evidence["corpus_sha256"],
                "corpus_record_count": evidence["corpus_record_count"],
                "evaluator_version": evidence["evaluator_version"],
                "model_id": evidence["model_id"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
