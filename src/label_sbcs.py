"""Phase 1, step 3: label SBC Markdown with a teacher model via OpenRouter.

The teacher returns JSON constrained to the SBCExtraction schema (structured
outputs), and every label is re-validated with Pydantic before it's saved.
Labels that fail validation are retried, then logged as failures and never saved.

    uv run python src/label_sbcs.py --split train,val --limit 5   # smoke test + true-cost check
    uv run python src/label_sbcs.py --split train,val             # everything in those splits

Labels go to data/labels/v<GUIDELINE_VERSION>/ so labels from different guideline
versions never mix.

Needs OPENROUTER_API_KEY in .env at the repo root.
"""

import argparse
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from pydantic import ValidationError

from schema import ANNOTATION_GUIDELINES, GUIDELINE_VERSION, SBCExtraction, normalize

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "data/markdown"
LABEL_DIR = ROOT / f"data/labels/v{GUIDELINE_VERSION}"
LOG = LABEL_DIR / "_log.jsonl"
SPLITS = ROOT / "data/splits.csv"
API_URL = "https://openrouter.ai/api/v1/chat/completions"
OUT_OF_CREDIT = threading.Event()  # set on HTTP 402 so remaining docs are skipped, not retried

# Same model weights (fp8) from every provider, but prices differ ~10x. Pin the two cheapest
# that enforce JSON schemas; max_price keeps fallbacks away from expensive providers.
PROVIDER_ROUTING = {
    "order": ["StreamLake", "Baidu", "DeepInfra"],
    "require_parameters": True,  # only providers that enforce the schema
    "max_price": {"prompt": 0.1, "completion": 0.2},  # $ per million tokens
}
# Teacher only (not part of SYSTEM_PROMPT, which the zero-shot baseline reuses):
# indented JSON costs ~35% more output tokens for the same content.
MINIFIED = "\n\nOutput minified JSON: no indentation, no newlines."


class Budget:
    """Thread-safe spend tracker. Stops new calls once spend + in-flight reserve hits the cap."""

    def __init__(self, cap: float, reserve: float):
        self.cap, self.reserve, self.spent = cap, reserve, 0.0
        self._lock = threading.Lock()

    def add(self, cost: float) -> None:
        with self._lock:
            self.spent += cost

    def exhausted(self) -> bool:
        return self.spent + self.reserve >= self.cap


BUDGET = Budget(cap=float("inf"), reserve=0.0)
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


def call_teacher(messages: list[dict], model: str, api_key: str,
                 response_format: dict = RESPONSE_FORMAT) -> tuple[str, dict, str]:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}"},
        json={
            "model": model,
            "messages": messages,
            "response_format": response_format,
            "temperature": 0,
            # A typical label is ~4k tokens (the teacher writes indented JSON); long SBCs
            # reach ~8k. The cap bounds the cost of runaway whitespace padding.
            "max_tokens": 12000,
            "reasoning": {"enabled": False},  # thinking tokens are billed as output
            "provider": PROVIDER_ROUTING,
            "usage": {"include": True},
        },
        timeout=600,
    )
    if resp.status_code == 402:
        OUT_OF_CREDIT.set()
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(body["error"])
    return body["choices"][0]["message"]["content"], body.get("usage", {}), body.get("provider", "")


def label_one(md_path: Path, model: str, api_key: str, retries: int = 2) -> dict:
    record = {"plan_id": md_path.stem, "model": model, "attempts": 0, "cost": 0.0}
    out = LABEL_DIR / f"{md_path.stem}.json"
    base = [
        {"role": "system", "content": SYSTEM_PROMPT + MINIFIED},
        {"role": "user", "content": md_path.read_text()},
    ]
    messages = base
    start = time.time()
    for attempt in range(1, retries + 2):
        if OUT_OF_CREDIT.is_set() or BUDGET.exhausted():
            record["error"] = "skipped: budget reached"
            break
        record["attempts"] = attempt
        try:
            content, usage, record["provider"] = call_teacher(messages, model, api_key)
            record["cost"] += usage.get("cost", 0.0)
            BUDGET.add(usage.get("cost", 0.0))
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
    if record.get("error", "").startswith("skipped"):
        record["status"] = "skipped"
    record["seconds"] = round(time.time() - start, 1)
    return record


def prioritize(docs: list[Path], splits: pd.DataFrame, val_first: int) -> list[Path]:
    """Order docs so a run cut short by the budget still leaves a useful dataset:
    a val subset first, then train round-robin across families, then the rest of val."""
    meta = splits.set_index("plan_id")
    by_split = {"train": [], "val": []}
    for p in docs:
        by_split[meta.loc[p.stem, "split"]].append(p)

    def round_robin(paths: list[Path]) -> list[Path]:
        rank = {}
        keyed = []
        for p in paths:
            fam = meta.loc[p.stem, "family"]
            rank[fam] = rank.get(fam, -1) + 1
            keyed.append((rank[fam], fam, p))
        return [p for *_, p in sorted(keyed)]

    val, train = round_robin(by_split["val"]), round_robin(by_split["train"])
    return val[:val_first] + train + val[val_first:]


def key_usage(api_key: str) -> dict:
    """Spend as OpenRouter bills it, for checking the per-call costs we log."""
    r = requests.get("https://openrouter.ai/api/v1/key", headers={"Authorization": f"Bearer {api_key}"}, timeout=30)
    data = r.json()["data"]
    return {"usage": data["usage"], "limit_remaining": data.get("limit_remaining")}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true", help="relabel docs that already have labels")
    parser.add_argument("--split", default=None, help="comma-separated splits from data/splits.csv, e.g. train,val")
    parser.add_argument("--budget", type=float, default=None, help="max $ to spend in this run")
    parser.add_argument("--keep", type=float, default=1.0, help="never let the key's remaining limit drop below this")
    parser.add_argument("--val-first", type=int, default=60, help="label this many val docs before train")
    args = parser.parse_args()

    load_dotenv(ROOT / ".env")
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("OPENROUTER_API_KEY not found in .env at the repo root")

    LABEL_DIR.mkdir(parents=True, exist_ok=True)
    docs = sorted(MD_DIR.glob("*.md"))
    if args.split:
        splits = pd.read_csv(SPLITS)
        wanted = set(splits.loc[splits.split.isin(args.split.split(",")) & (splits.download_status == "ok"), "plan_id"])
        docs = [p for p in docs if p.stem in wanted]
        docs = prioritize(docs, splits, args.val_first)
    todo = [p for p in docs if args.overwrite or not (LABEL_DIR / f"{p.stem}.json").exists()]
    todo = todo[: args.limit] if args.limit else todo
    print(f"labeling {len(todo)} docs with {args.model} (guidelines v{GUIDELINE_VERSION})")
    before = key_usage(api_key)
    print(f"key: ${before['usage']:.4f} used, ${before['limit_remaining']} remaining")
    cap = args.budget if args.budget is not None else float("inf")
    if before["limit_remaining"] is not None:
        cap = min(cap, before["limit_remaining"] - args.keep)
    # Room for every in-flight doc to finish, incl. retries, at cheap-provider prices.
    BUDGET.cap, BUDGET.reserve = cap, args.workers * 0.004
    print(f"budget: ${cap:.4f} (stops starting new docs at ${cap - BUDGET.reserve:.4f})")

    results = []
    with ThreadPoolExecutor(args.workers) as pool, LOG.open("a") as log:
        futures = [pool.submit(label_one, p, args.model, api_key) for p in todo]
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if r["status"] != "skipped":
                log.write(json.dumps(r) + "\n")
                log.flush()  # a killed run keeps its log
            if r.get("status") != "skipped":
                print(f"  {r['plan_id']:<20} {r['status']:<7} {r['seconds']:>6}s  ${r['cost']:.4f}  "
                      f"out={r.get('completion_tokens')}  {r.get('provider', '')}  {r.get('error', '')}  "
                      f"[spent ${BUDGET.spent:.4f}]", flush=True)

    results = [r for r in results if r["status"] != "skipped"]
    ok = [r for r in results if r["status"] == "ok"]
    total = sum(r["cost"] for r in results)
    billed = key_usage(api_key)["usage"] - before["usage"]
    print(f"\n{len(ok)}/{len(results)} ok | logged ${total:.4f} | billed ${billed:.4f} | "
          f"${billed / max(len(ok), 1):.4f} billed per labeled doc")
    if OUT_OF_CREDIT.is_set():
        print("STOPPED: OpenRouter returned 402 (out of credit or key limit reached)")


if __name__ == "__main__":
    main()
