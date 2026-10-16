"""Phase 1, step 6: assign every SBC to a template family and build train/val splits.

A "family" is a group of SBCs likely to share one document template. Splitting by
family (not by plan or issuer ID) keeps layouts the model trained on out of val/test:

  - family = registered domain of the SBC URL (centene.com, uhc.com, lablue.com, ...)
    This catches hidden links: HMO Louisiana and BCBS Louisiana both publish on lablue.com.
  - exception: generic CDNs host unrelated insurers, so there it's domain + brand.

Gold families are excluded entirely. A few whole families are held out as validation.
Within each split, sampling is round-robin across families so big insurers don't
dominate the training set.

    uv run python src/build_splits.py --target 2000
    uv run python src/build_splits.py --topup 400   # after a download: add train docs from families that downloaded well
"""

import argparse
import re
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd

from build_gold import GOLD_IDS
from collect_sbcs import build_manifest

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data/splits.csv"
GENERIC_HOSTS = {"cloudfront.net", "windows.net", "widen.net", "stylelabs.cloud",
                 "amazonaws.com", "azureedge.net", "googleapis.com", "box.com", "sharepoint.com"}


def family(url: str, issuer: str) -> str:
    host = (urlparse(url.strip()).hostname or "").lower()
    domain = ".".join(host.split(".")[-2:])
    if domain in GENERIC_HOSTS:
        brand = re.sub(r"[^a-z]", "", issuer.lower().split()[0])
        return f"{domain}:{brand}"
    return domain


def round_robin(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    df = df.sample(frac=1, random_state=seed)
    df["rank_in_family"] = df.groupby("family").cumcount()
    return df.sort_values(["rank_in_family", "family"]).head(n).drop(columns="rank_in_family")


def topup(n: int, seed: int, min_success: float = 0.8) -> None:
    """Add n train docs from train families whose downloads mostly succeeded.

    Some insurers block scripted downloads entirely; retrying them is pointless,
    so the extra docs come from families that are known to work.
    """
    splits = pd.read_csv(OUT)
    train = splits[splits.split == "train"]
    rate = train.groupby("family").download_status.apply(lambda s: (s == "ok").mean())
    good = set(rate[rate >= min_success].index)
    m = build_manifest()
    m["family"] = [family(u, i) for u, i in zip(m.sbc_url, m.issuer)]
    pool = m[m.family.isin(good) & ~m.plan_id.isin(splits.plan_id)]
    extra = round_robin(pool, n, seed).assign(split="train")
    pd.concat([splits, extra]).to_csv(OUT, index=False)
    print(f"added {len(extra)} train docs from {extra.family.nunique()} families "
          f"(of {len(good)} with >= {min_success:.0%} download success)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=2000, help="docs to download (expect ~15% loss)")
    parser.add_argument("--val-frac", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--topup", type=int, default=0)
    args = parser.parse_args()
    if args.topup:
        return topup(args.topup, args.seed)

    m = build_manifest()
    m["family"] = [family(u, i) for u, i in zip(m.sbc_url, m.issuer)]
    gold_families = set(m.loc[m.plan_id.isin(GOLD_IDS), "family"])
    assert len(gold_families) == len(GOLD_IDS), "every gold doc should be found in the PUF"
    pool = m[~m.family.isin(gold_families)]

    # Validation = whole families, picked at random among those with 20+ docs,
    # until they hold ~val_frac of the download target.
    sizes = pool.family.value_counts()
    candidates = sizes[sizes >= 20].sample(frac=1, random_state=args.seed)
    n_val_target = int(args.target * args.val_frac)
    val_families, per_family_cap = [], 40
    for fam in candidates.index:
        if sum(min(sizes[f], per_family_cap) for f in val_families) >= n_val_target:
            break
        val_families.append(fam)

    val = round_robin(pool[pool.family.isin(val_families)], n_val_target, args.seed)
    train = round_robin(pool[~pool.family.isin(val_families)], args.target - len(val), args.seed)
    splits = pd.concat([train.assign(split="train"), val.assign(split="val")])
    splits.to_csv(OUT, index=False)

    print(f"families: {m.family.nunique()} total | {len(gold_families)} gold (excluded, "
          f"{m.family.isin(gold_families).sum()} docs) | {len(val_families)} val")
    print(f"gold families: {sorted(gold_families)}")
    print(f"val families:  {val_families}")
    for name, part in splits.groupby("split"):
        top = part.family.value_counts()
        print(f"{name}: {len(part)} docs, {part.family.nunique()} families, "
              f"largest {top.index[0]}={top.iloc[0]}, metal {part.metal.value_counts().to_dict()}")
    assert not set(train.family) & set(val.family) and not set(splits.family) & gold_families
    print(f"-> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
