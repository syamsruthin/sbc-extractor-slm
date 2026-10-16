"""Phase 1, step 4: build gold-set review sheets.

SBC row labels are fixed by the CMS template, so each service field can be lined
up with its source table row automatically. Each sheet puts the source cell next
to the extracted value and flags likely errors with deterministic rules, so a
human checks a short list instead of re-reading 8 pages.

    uv run python src/review_sheet.py 10091OR0780001-01 23552TN0020036-01 ...
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MD_DIR = ROOT / "data/markdown"
LABEL_DIR = ROOT / "data/gold/teacher_labels"  # what the gold review is based on
OUT_DIR = ROOT / "data/gold/review"

# field -> (row-label regex, which match to use). "Physician/surgeon fees" and
# similar labels appear once for outpatient surgery and again for hospital stays.
SERVICE_ROWS = {
    "primary_care_visit": (r"primary care visit", 0),
    "specialist_visit": (r"specialist visit", 0),
    "preventive_care": (r"preventive care", 0),
    "diagnostic_test": (r"diagnostic test", 0),
    "imaging": (r"imaging", 0),
    "outpatient_facility_fee": (r"facility fee", 0),
    "outpatient_surgeon_fee": (r"physician ?/ ?surgeon fee", 0),
    "emergency_room": (r"emergency room", 0),
    "emergency_transportation": (r"emergency medical\s*transportation", 0),
    "urgent_care": (r"urgent care", 0),
    "hospital_facility_fee": (r"facility fee", 1),
    "hospital_surgeon_fee": (r"physician ?/ ?surgeon fee", 1),
    "mental_health_outpatient": (r"outpatient services", 0),
    "mental_health_inpatient": (r"inpatient services", 0),
    "pregnancy_office_visits": (r"^office visits", 0),
    "childbirth_professional": (r"childbirth/delivery\s*professional", 0),
    "childbirth_facility": (r"childbirth/delivery\s*facility", 0),
    "home_health_care": (r"home health", 0),
    "rehabilitation": (r"rehabilitation services", 0),
    "habilitation": (r"(?<!re)habilitation services", 0),
    "skilled_nursing": (r"skilled nursing", 0),
    "durable_medical_equipment": (r"durable medical", 0),
    "hospice": (r"hospice", 0),
    "child_eye_exam": (r"eye exam", 0),
    "child_glasses": (r"glasses", 0),
    "child_dental_checkup": (r"dental check", 0),
}

NUM = re.compile(r"\$\s*([\d,]+(?:\.\d+)?)|([\d.]+)\s*%")


def clean(cell: str) -> str:
    return re.sub(r"\s+", " ", cell.replace("<br>", " ").replace("*", "").replace("_", "")).strip()


def table_rows(md: str) -> list[list[str]]:
    return [[clean(c) for c in line.strip().strip("|").split("|")]
            for line in md.splitlines() if line.lstrip().startswith("|")]


def find_row(rows: list[list[str]], pattern: str, nth: int) -> list[str] | None:
    # PDF conversion often drops spaces ("Specialistvisit"), so match with all
    # whitespace removed from both the cell and the pattern.
    pattern = re.sub(r"\\s\*| \?| ", "", pattern)
    hits = []
    for r, cells in enumerate(rows):
        for i, cell in enumerate(cells):
            if re.search(pattern, cell.replace(" ", ""), re.I) and len(cell) < 90:
                found = cells[i + 1:]  # the cells after the row label
                if not any(found[:2]) and r + 1 < len(rows):
                    # Header row with empty prices (e.g. HMSA): use the first sub-row.
                    sub = rows[r + 1]
                    j = next((k for k, c in enumerate(sub) if c and k > 0), 1)
                    found = [f"[{sub[j - 1]}] {c}" if c else c for c in sub[j:]]
                hits.append(found)
                break
    return hits[nth] if len(hits) > nth else None


def numbers(text: str) -> set[float]:
    return {float((a or b).replace(",", "")) for a, b in NUM.findall(text)}


def fmt(c: dict | None) -> str:
    if c is None:
        return "null"
    if not c["covered"]:
        return "not covered"
    parts = []
    if c["copay"] is not None:
        parts.append(f"${c['copay']:g} copay")
    if c["coinsurance_pct"] is not None:
        parts.append(f"{c['coinsurance_pct']:g}% coins")
    parts.append({True: "ded applies", False: "no ded", None: "ded ?"}[c["deductible_applies"]])
    if c["note"]:
        parts.append(f"note: {c['note']}")
    return "; ".join(parts) or "covered, no price"


def check(c: dict | None, src: str) -> list[str]:
    """Rule-based flags comparing one extracted cost-share with its source cell."""
    if c is None or not src:
        return []
    s = src.lower().replace(" ", "")
    flags = []
    if "notcovered" in s and c["covered"] and "nocharge" not in s and not numbers(src):
        flags.append("source says not covered")
    if not c["covered"]:
        if "notcovered" not in s and "excluded" not in s:
            flags.append("marked not covered; source doesn't say so")
        return flags
    if s.startswith("nocharge") and (c["copay"] != 0 or c["coinsurance_pct"] != 0):
        flags.append("'No charge' should be copay=0, coinsurance=0")
    if c["copay"] is None and c["coinsurance_pct"] is None and numbers(src):
        flags.append("source has a price; structured fields empty")
    src_nums = numbers(src)
    for key in ("copay", "coinsurance_pct"):
        v = c[key]
        if v not in (None, 0) and v not in src_nums:
            flags.append(f"{key}={v:g} not found in source cell")
    if "deductibledoesnotapply" in s and "afterdeductible" not in s and c["deductible_applies"] is not False:
        flags.append("source: deductible does not apply")
    if "afterdeductible" in s and "deductibledoesnotapply" not in s and c["deductible_applies"] is not True:
        flags.append("source: after deductible")
    return flags


def sheet(plan_id: str) -> tuple[str, int]:
    md = (MD_DIR / f"{plan_id}.md").read_text()
    label = json.loads((LABEL_DIR / f"{plan_id}.json").read_text())
    rows = table_rows(md)
    n_flags = 0
    out = [f"# Review: {plan_id}", "",
           f"**{label['plan_name']}** · {label['issuer']} · {label['plan_type']} · {label['coverage_period']}", "",
           "Check each row against the PDF (`data/raw/sbc_pdfs/{0}.pdf`). Rows marked ⚠️ need attention;"
           " spot-check the rest.".format(plan_id), "",
           "## Deductible and out-of-pocket limit", ""]
    for field, pattern in [("deductible", r"overall\s*deductible"), ("out_of_pocket_limit", r"out-of-pocket\s*limit\s*for")]:
        src = find_row(rows, pattern, 0)
        out += [f"- **{field}** → `{json.dumps(label[field])}`",
                f"  - source: {(src[0] if src else 'NOT FOUND')[:300]}"]
    out += ["", "## Services", "",
            "| | field | source (in-network) | extracted (in-network) | source (out-of-network) | extracted (out-of-network) |",
            "|---|---|---|---|---|---|"]
    for field, (pattern, nth) in SERVICE_ROWS.items():
        src = find_row(rows, pattern, nth) or []
        # Columns after the label: in-network tier(s)..., out-of-network, limitations.
        # Tiered-network plans have 2+ in-network columns; in_network is the first.
        src_in = src[0] if len(src) > 0 else ""
        src_out = src[-2] if len(src) >= 3 else (src[1] if len(src) > 1 else "")
        svc = label["services"][field]
        flags = check(svc["in_network"], src_in) + [f"OON: {f}" for f in check(svc["out_of_network"], src_out)]
        if not src:
            flags.append("source row not found; check the PDF")
        n_flags += bool(flags)
        mark = "⚠️ " + "<br>".join(flags) if flags else ""
        out.append(f"| {mark} | {field} | {src_in[:160]} | {fmt(svc['in_network'])} | {src_out[:120]} | {fmt(svc['out_of_network'])} |")
    out += ["", "## Drug tiers", "", "Source rows:", ""]
    out += [f"- {' | '.join(r)[:220]}" for r in rows
            if any(re.search(r"(drug|tier \d)", c, re.I) and len(c) < 90 for c in r[:2])][:8]
    out += ["", "Extracted:", ""]
    out += [f"- {t['name']} → {t['category']}: {fmt(t['retail']['in_network'])}" for t in label["drug_tiers"]]
    out += ["", "## Lists", "",
            f"- **services_before_deductible**: {label['services_before_deductible']}",
            f"- **excluded_services**: {label['excluded_services']}",
            f"- **referral_required_for_specialist**: {label['referral_required_for_specialist']}", ""]
    return "\n".join(out), n_flags


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for plan_id in sys.argv[1:]:
        text, n_flags = sheet(plan_id)
        (OUT_DIR / f"{plan_id}.md").write_text(text)
        print(f"{plan_id:<20} {n_flags:>2} flagged service rows")


if __name__ == "__main__":
    main()
