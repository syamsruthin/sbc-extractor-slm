"""Phase 1, step 3: label SBC Markdown with a teacher model via OpenRouter.

The teacher returns JSON constrained to the SBCExtraction schema (structured
outputs), and every label is re-validated with Pydantic before it's saved.
Labels that fail validation are retried, then logged as failures and never saved.

    uv run python src/label_sbcs.py --limit 1      # smoke test
    uv run python src/label_sbcs.py                # all unlabeled docs

Needs OPENROUTER_API_KEY in .env at the repo root.
"""

import argparse
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from schema import ANNOTATION_GUIDELINES, SBCExtraction, normalize

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "data/markdown"
LABEL_DIR = ROOT / "data/labels"
LOG = ROOT / "data/labels/_log.jsonl"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_MODEL = "deepseek/deepseek-v4-flash"

SYSTEM_PROMPT = f"""You extract structured data from US health plan Summary of Benefits \
and Coverage (SBC) documents. The SBC is given as Markdown converted from PDF; \
words may be run together (e.g. "deductibledoes not apply").

Follow these rules exactly:
{ANNOTATION_GUIDELINES}"""


def strict_schema(schema: dict) -> dict:
    """Disallow extra keys everywhere, as strict structured outputs require."""
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
        for value in schema.values():
            strict_schema(value)
    elif isinstance(schema, list):
        for item in schema:
            strict_schema(item)
    return schema


RESPONSE_FORMAT = {
    "type": "json_schema",
    "json_schema": {
        "name": "sbc_extraction",
        "strict": True,
        "schema": strict_schema(SBCExtraction.model_json_schema()),
    },
}


def call_teacher(messages: list[dict], model: str, api_key: str) -> tuple[str, dict]:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "response_format": RESPONSE_FORMAT,
            "temperature": 0,
            # A typical label is ~4k tokens (the teacher writes indented JSON); long SBCs
            # reach ~8k. The cap bounds the cost of runaway whitespace padding.
            "max_tokens": 12000,
            "reasoning": {"enabled": False},  # thinking tokens are billed as output
            "provider": {"require_parameters": True},  # only providers that enforce the schema
            "usage": {"include": True},
        },
        timeout=600,
    )
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["choices"][0]["message"]["content"], body.get("usage", {})


def label_one(md_path: Path, model: str, api_key: str, retries: int = 2) -> dict:
    record = {"plan_id": md_path.stem, "model": model, "attempts": 0, "cost": 0.0}
    out = LABEL_DIR / f"{md_path.stem}.json"
    base = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": md_path.read_text()},
    ]
    messages = base
    start = time.time()
    for attempt in range(1, retries + 2):
        record["attempts"] = attempt
        try:
            content, usage = call_teacher(messages, model, api_key)
            record["cost"] += usage.get("cost", 0.0)
            record["prompt_tokens"] = usage.get("prompt_tokens")
            record["completion_tokens"] = usage.get("completion_tokens")
            label = normalize(SBCExtraction.model_validate_json(content))
        except ValidationError as e:
            record["error"] = f"ValidationError: {str(e)[:300]}"
            if any(err["type"] == "json_invalid" for err in e.errors()):
                messages = base  # truncated output: feedback can't help, start over
            else:
                # Valid JSON that breaks a constraint (e.g. note too long): show the
                # teacher its own answer and the exact errors so it can fix them.
                messages = base + [
                    {"role": "assistant", "content": content},
                    {"role": "user", "content": f"Fix these validation errors and return the full corrected JSON:\n{e}"},
                ]
            continue
        except (requests.RequestException, RuntimeError, KeyError) as e:
            record["error"] = f"{type(e).__name__}: {str(e)[:300]}"
            time.sleep(2 * attempt)
            continue
        out.write_text(label.model_dump_json(indent=2))
        record.pop("error", None)
        record["status"] = "ok"
        break
    else:
        record["status"] = "failed"
        out.unlink(missing_ok=True)  # never leave a stale label from an older run
    record["seconds"] = round(time.time() - start, 1)
    return record


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true", help="relabel docs that already have labels")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY not found in .env at the repo root")

    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    todo = [p for p in sorted(MD_DIR.glob("*.md"))
            if args.overwrite or not (LABEL_DIR / f"{p.stem}.json").exists()]
    todo = todo[: args.limit] if args.limit else todo
    print(f"labeling {len(todo)} docs with {args.model}")

    results = []
    with ThreadPoolExecutor(args.workers) as pool, LOG.open("a") as log:
        futures = [pool.submit(label_one, p, args.model, api_key) for p in todo]
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            log.write(json.dumps(r) + "\n")
            print(f"  {r['plan_id']:<20} {r['status']:<7} {r['seconds']:>6}s  ${r['cost']:.4f}  "
                  f"out={r.get('completion_tokens')}  {r.get('error', '')}")

    ok = [r for r in results if r["status"] == "ok"]
    total = sum(r["cost"] for r in results)
    print(f"\n{len(ok)}/{len(results)} ok | total ${total:.4f} | "
          f"${total / max(len(ok), 1):.4f} per labeled doc")


if __name__ == "__main__":
    main()
