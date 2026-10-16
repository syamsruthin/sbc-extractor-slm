"""Phase 2: field-level scoring of SBC extractions against the gold labels.

Every label is flattened to leaf paths (e.g. services.specialist_visit.in_network.copay)
and each gold/pred pair gets one outcome:

    correct        both present and equal (numbers within 0.01, text normalized)
    correct_null   both null
    wrong          both present, different
    omission       gold present, pred null           -> missed information
    hallucination  gold null, pred present           -> invented information

Fields are grouped so one score doesn't hide where a model fails:
money, percent, covered, deductible_applies, plan_info, drug_tier_category,
plus list F1 (services_before_deductible, excluded_services) and note presence.

Normalization (applies to gold and pred alike):
  - A null CostShare means "no benefit", the same as covered=false with null prices.
    The teacher uses both forms, so neither should be penalized.
  - Drug tiers are aligned by position; a missing or extra tier scores every leaf as
    an omission or hallucination.

    uv run python eval/score.py eval/predictions/<run>     # scores a run, writes <run>/score.json
"""

import json
import re
import sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from schema import SBCExtraction  # noqa: E402

GOLD_DIR = ROOT / "data/gold/labels"
NO_BENEFIT = {"covered": False, "copay": None, "coinsurance_pct": None, "deductible_applies": None, "note": None}
LIST_FIELDS = ("services_before_deductible", "excluded_services")


def group_of(path: str) -> str:
    leaf = path.rsplit(".", 1)[-1]
    if leaf in ("individual", "family", "copay"):
        return "money"
    if leaf == "coinsurance_pct":
        return "percent"
    if leaf in ("covered", "deductible_applies"):
        return leaf
    if leaf == "category":
        return "drug_tier_category"
    if path in ("plan_name", "issuer", "plan_type", "coverage_period", "referral_required_for_specialist"):
        return "plan_info"
    return "other"


MISSING = object()  # key absent in a schema-invalid prediction (vs. an explicit null)


def obj(x) -> dict:
    return x if isinstance(x, dict) else {}


def cost_share(c, prefix: str, out: dict) -> None:
    if c is MISSING:  # absent from the output: every leaf is an omission
        c = dict.fromkeys(NO_BENEFIT)
    elif c is None:  # explicit null: "no benefit"
        c = NO_BENEFIT
    for k in NO_BENEFIT:
        out[f"{prefix}.{k}"] = obj(c).get(k)


def flatten(label: dict, n_tiers: int) -> dict:
    """Leaf paths -> values. Defensive, so schema-invalid predictions can still be scored."""
    out = {k: label.get(k) for k in ("plan_name", "issuer", "plan_type", "coverage_period",
                                     "referral_required_for_specialist")}
    for field in ("deductible", "out_of_pocket_limit"):
        for net in ("in_network", "out_of_network"):
            amounts = obj(obj(label.get(field)).get(net))
            for k in ("individual", "family"):
                out[f"{field}.{net}.{k}"] = amounts.get(k)
    services = obj(label.get("services"))
    for name in SBCExtraction.model_fields["services"].annotation.model_fields:
        svc = obj(services.get(name))
        for net in ("in_network", "out_of_network"):
            cost_share(svc.get(net, MISSING), f"services.{name}.{net}", out)
    tiers = label.get("drug_tiers") if isinstance(label.get("drug_tiers"), list) else []
    for i in range(n_tiers):  # pad to the longer of gold/pred so both have the same paths
        t = obj(tiers[i]) if i < len(tiers) else None
        out[f"drug_tiers.{i}.category"] = t.get("category") if t else None
        for net in ("in_network", "out_of_network"):
            # a missing tier is missing, not "not covered"
            cost_share(obj(t.get("retail")).get(net, MISSING) if t else MISSING, f"drug_tiers.{i}.retail.{net}", out)
    return out


def str_list(x) -> list[str]:
    return [v for v in x if isinstance(v, str)] if isinstance(x, list) else []


def norm_text(v) -> str:
    return re.sub(r"[^a-z0-9]", "", str(v).lower())


def same(gold, pred) -> bool:
    if isinstance(gold, bool) or isinstance(pred, bool):
        return gold is pred
    if isinstance(gold, (int, float)) and isinstance(pred, (int, float)):
        return abs(gold - pred) < 0.01
    return norm_text(gold) == norm_text(pred)


def outcome(gold, pred) -> str:
    if gold is None and pred is None:
        return "correct_null"
    if gold is None:
        return "hallucination"
    if pred is None:
        return "omission"
    return "correct" if same(gold, pred) else "wrong"


def list_f1(gold: list[str], pred: list[str], threshold: float = 0.8) -> tuple[int, int, int]:
    """Greedy fuzzy matching of short service names; returns (true pos, n_gold, n_pred)."""
    unmatched = [norm_text(p) for p in pred]
    tp = 0
    for g in map(norm_text, gold):
        best = max(unmatched, key=lambda p: SequenceMatcher(None, g, p).ratio(), default=None)
        if best is not None and SequenceMatcher(None, g, best).ratio() >= threshold:
            tp += 1
            unmatched.remove(best)
    return tp, len(gold), len(pred)


def score_doc(gold: dict, pred: dict | None) -> dict:
    """Outcomes per field for one document. pred=None means the output was unusable."""
    pred_tiers = pred.get("drug_tiers") if pred else None
    n_tiers = max(len(gold["drug_tiers"]), len(pred_tiers) if isinstance(pred_tiers, list) else 0)
    g = flatten(gold, n_tiers)
    p = flatten(pred, n_tiers) if pred else {}
    fields = {}
    for path, gv in g.items():
        if path.endswith(".note"):
            continue  # free text: scored as presence below, not exact match
        fields[path] = outcome(gv, p.get(path)) if pred else ("omission" if gv is not None else "correct_null")
    notes = {path: (gv is not None, p.get(path) is not None) for path, gv in g.items() if path.endswith(".note")}
    lists = {f: list_f1(gold[f], str_list(pred.get(f)) if pred else []) for f in LIST_FIELDS}
    return {"fields": fields, "notes": notes, "lists": lists}


def summarize(docs: dict[str, dict]) -> dict:
    by_group = defaultdict(Counter)
    for d in docs.values():
        for path, o in d["fields"].items():
            by_group[group_of(path)][o] += 1
            by_group["ALL"][o] += 1
    summary = {}
    for group, c in sorted(by_group.items()):
        total = sum(c.values())
        gold_null = c["correct_null"] + c["hallucination"]
        summary[group] = {
            "n": total,
            "accuracy": round((c["correct"] + c["correct_null"]) / total, 4),
            "wrong": c["wrong"],
            "omission": c["omission"],
            "hallucination": c["hallucination"],
            "hallucination_rate": round(c["hallucination"] / gold_null, 4) if gold_null else None,
        }
    for f in LIST_FIELDS:
        tp = sum(d["lists"][f][0] for d in docs.values())
        n_gold = sum(d["lists"][f][1] for d in docs.values())
        n_pred = sum(d["lists"][f][2] for d in docs.values())
        prec, rec = tp / n_pred if n_pred else 0.0, tp / n_gold if n_gold else 0.0
        summary[f"list:{f}"] = {"precision": round(prec, 4), "recall": round(rec, 4),
                                "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0}
    agree = [g == p for d in docs.values() for g, p in d["notes"].values()]
    summary["note_presence_agreement"] = round(sum(agree) / len(agree), 4) if agree else None
    return summary


def load_pred(path: Path) -> tuple[dict | None, str]:
    """Returns (label, status): ok / schema_error / invalid_json / missing.

    schema_error outputs are still scored field by field (e.g. a note over 150 chars
    shouldn't zero out an otherwise correct extraction); strict validity is reported
    separately. invalid_json outputs score as all-omission.
    """
    if not path.exists():
        return None, "missing"
    text = path.read_text()
    try:
        return SBCExtraction.model_validate_json(text).model_dump(mode="json"), "ok"
    except ValueError:
        pass
    try:
        data = json.loads(text)
    except ValueError:
        return None, "invalid_json"
    return (data, "schema_error") if isinstance(data, dict) else (None, "invalid_json")


def score_run(run_dir: Path) -> dict:
    docs, statuses = {}, {}
    for gold_path in sorted(GOLD_DIR.glob("*.json")):
        gold = json.loads(gold_path.read_text())
        pred, statuses[gold_path.stem] = load_pred(run_dir / gold_path.name)
        docs[gold_path.stem] = score_doc(gold, pred)
    valid = {k: v for k, v in docs.items() if statuses[k] in ("ok", "schema_error")}
    return {
        "run": run_dir.name,
        "n_docs": len(docs),
        "status": dict(Counter(statuses.values())),
        "schema_valid_rate": round(sum(v == "ok" for v in statuses.values()) / len(statuses), 4),
        "json_parse_rate": round(sum(v in ("ok", "schema_error") for v in statuses.values()) / len(statuses), 4),
        "all_docs": summarize(docs),  # unparseable outputs count as all-omission
        "parsed_docs": summarize(valid) if valid else None,
        "per_doc_accuracy": {
            k: round(sum(o in ("correct", "correct_null") for o in d["fields"].values()) / len(d["fields"]), 4)
            for k, d in docs.items()
        },
        "errors": [
            {"plan_id": k, "path": path, "outcome": o}
            for k, d in valid.items() for path, o in d["fields"].items()
            if o in ("wrong", "omission", "hallucination")
        ],
    }


def print_report(r: dict) -> None:
    print(f"run: {r['run']}  docs: {r['n_docs']}  status: {r['status']}")
    print(f"JSON parse rate: {r['json_parse_rate']:.0%}   strict schema-valid rate: {r['schema_valid_rate']:.0%}")
    for scope in ("all_docs", "parsed_docs"):
        s = r[scope]
        if not s:
            continue
        print(f"\n[{scope}]  {'group':<20}{'n':>6}{'acc':>8}{'wrong':>7}{'omit':>6}{'halluc':>8}{'h-rate':>8}")
        for group, m in s.items():
            if isinstance(m, dict) and "accuracy" in m:
                h = f"{m['hallucination_rate']:.1%}" if m["hallucination_rate"] is not None else "-"
                print(f"{'':>13}{group:<20}{m['n']:>6}{m['accuracy']:>8.1%}{m['wrong']:>7}"
                      f"{m['omission']:>6}{m['hallucination']:>8}{h:>8}")
        for f in LIST_FIELDS:
            m = s[f"list:{f}"]
            print(f"{'':>13}{f:<28} P {m['precision']:.1%}  R {m['recall']:.1%}  F1 {m['f1']:.1%}")
        print(f"{'':>13}note presence agreement: {s['note_presence_agreement']:.1%}")


def main() -> None:
    run_dir = Path(sys.argv[1]).resolve()
    report = score_run(run_dir)
    (run_dir / "score.json").write_text(json.dumps(report, indent=2))
    print_report(report)


if __name__ == "__main__":
    main()
