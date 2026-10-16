"""Phase 1, step 7: download every SBC in data/splits.csv (parallel, resumable),
then drop exact-duplicate PDFs so the same document can't appear twice.

    uv run python src/download_split.py --workers 12
"""

import argparse
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests
from tqdm import tqdm

from collect_sbcs import PDF_DIR, download
from build_splits import OUT as SPLITS

_local = threading.local()


def session() -> requests.Session:
    if not hasattr(_local, "s"):  # one Session per thread; Sessions aren't thread-safe
        _local.s = requests.Session()
        _local.s.headers["User-Agent"] = "Mozilla/5.0 (sbc-extractor research project)"
    return _local.s


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    splits = pd.read_csv(SPLITS)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    if "download_status" not in splits:
        splits["download_status"] = None
    # Only rows never attempted: earlier failures are mostly blocked hosts, not flukes.
    todo = splits.download_status.isna()
    rows = list(splits[todo].itertuples())
    with ThreadPoolExecutor(args.workers) as pool:
        statuses = list(tqdm(pool.map(lambda r: download(r, session()), rows), total=len(rows), mininterval=10))
    splits.loc[todo, "download_status"] = ["ok" if s in ("ok", "cached") else s for s in statuses]

    ok = splits.download_status == "ok"
    splits.loc[ok, "sha256"] = [hashlib.sha256((PDF_DIR / f"{p}.pdf").read_bytes()).hexdigest()
                                for p in splits.loc[ok, "plan_id"]]
    dup = ok & splits.duplicated("sha256", keep="first")
    splits.loc[dup, "download_status"] = "duplicate"
    splits.to_csv(SPLITS, index=False)

    print(splits.groupby("split").download_status.value_counts().to_string())


if __name__ == "__main__":
    main()
