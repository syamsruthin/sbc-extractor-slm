"""Phase 1, step 1: build an SBC manifest from the CMS Plan Attributes PUF and
download a diverse sample of SBC PDFs.

Sampling is round-robin across issuers so a small sample still covers many
different insurer layouts (layout diversity matters more than volume).

    uv run python src/collect_sbcs.py --n 30
"""

import argparse
import time
from pathlib import Path

import pandas as pd
import requests
from tqdm import tqdm

ROOT = Path(__file__).resolve().parent.parent
PUF_CSV = ROOT / "data/raw/puf/plan-attributes-puf.csv"
PDF_DIR = ROOT / "data/raw/sbc_pdfs"
MANIFEST = ROOT / "data/manifest.csv"
MAX_BYTES = 10 * 1024 * 1024  # an SBC is ~8 pages; anything bigger is not one


def build_manifest() -> pd.DataFrame:
    df = pd.read_csv(PUF_CSV, low_memory=False)
    df = df[(df["DentalOnlyPlan"] == "No") & df["URLForSummaryofBenefitsCoverage"].notna()]
    cols = {
        "PlanId": "plan_id",
        "StateCode": "state",
        "IssuerId": "issuer_id",
        "IssuerMarketPlaceMarketingName": "issuer",
        "PlanMarketingName": "plan_name",
        "MetalLevel": "metal",
        "PlanType": "plan_type",
        "URLForSummaryofBenefitsCoverage": "sbc_url",
    }
    # Several plan variants (e.g. cost-sharing reductions) can share one SBC URL.
    return df[list(cols)].rename(columns=cols).drop_duplicates("sbc_url").reset_index(drop=True)


def sample_round_robin(manifest: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    shuffled = manifest.sample(frac=1, random_state=seed)
    shuffled["rank_in_issuer"] = shuffled.groupby("issuer_id").cumcount()
    return shuffled.sort_values(["rank_in_issuer", "issuer_id"]).head(n).drop(columns="rank_in_issuer")


def download(row: pd.Series, session: requests.Session) -> str:
    out = PDF_DIR / f"{row.plan_id}.pdf"
    if out.exists():
        return "cached"
    try:
        resp = session.get(row.sbc_url, timeout=30, stream=True)
        resp.raise_for_status()
        content = resp.raw.read(MAX_BYTES + 1, decode_content=True)
    except requests.RequestException as e:
        return f"error: {type(e).__name__}"
    if len(content) > MAX_BYTES:
        return "too_large"
    if not content.startswith(b"%PDF"):
        return "not_pdf"  # e.g. an HTML landing page instead of the document
    out.write_bytes(content)
    return "ok"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    manifest = build_manifest()
    print(f"{len(manifest)} unique medical SBC URLs from {manifest.issuer_id.nunique()} issuers")

    sample = sample_round_robin(manifest, args.n, args.seed)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "Mozilla/5.0 (sbc-extractor research project)"

    statuses = []
    for _, row in tqdm(sample.iterrows(), total=len(sample)):
        statuses.append(download(row, session))
        time.sleep(0.5)
    sample["download_status"] = statuses

    sample.to_csv(MANIFEST, index=False)
    print(sample["download_status"].value_counts().to_string())
    print(f"manifest -> {MANIFEST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
