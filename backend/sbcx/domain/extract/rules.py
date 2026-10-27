"""Business-rule checks. A failed rule never changes a value: it adds a warning and lowers the
confidence of the fields involved."""

from sbcx.domain.benefits import Warning
from sbcx.domain.sbc import SBCExtraction

# ACA in-network out-of-pocket maximum (self-only, family) by plan year. Used only for warnings.
LEGAL_OOP_MAX = {2025: (9200, 18400), 2026: (10600, 21200)}


def _year(period: str | None) -> int | None:
    import re

    m = re.search(r"(20\d\d)", period or "")
    return int(m.group(1)) if m else None


def check(ext: SBCExtraction, anchored: int) -> list[Warning]:
    w: list[Warning] = []
    for name in ("deductible", "out_of_pocket_limit"):
        na = getattr(ext, name)
        for net in ("in_network", "out_of_network"):
            a = getattr(na, net)
            if a and a.individual is not None and a.family is not None and a.family < a.individual:
                w.append(
                    Warning(
                        code="W_FAMILY_LT_INDIVIDUAL",
                        path=f"{name}.{net}",
                        message=f"Family {name.replace('_', ' ')} is lower than the individual amount.",
                    )
                )
    for net in ("in_network", "out_of_network"):
        d, o = getattr(ext.deductible, net), getattr(ext.out_of_pocket_limit, net)
        if d and o and d.individual is not None and o.individual is not None and o.individual < d.individual:
            w.append(
                Warning(
                    code="W_OOP_LT_DEDUCTIBLE",
                    path=f"out_of_pocket_limit.{net}.individual",
                    message="Out-of-pocket limit is lower than the deductible.",
                )
            )
    lim = LEGAL_OOP_MAX.get(_year(ext.coverage_period) or 0)
    oi = ext.out_of_pocket_limit.in_network
    if lim and oi and oi.individual and oi.individual > lim[0]:
        w.append(
            Warning(
                code="W_OOP_ABOVE_LEGAL_MAX",
                path="out_of_pocket_limit.in_network.individual",
                message=f"In-network out-of-pocket limit is above the legal maximum (${lim[0]:,}).",
            )
        )
    if ext.deductible.in_network is None:
        w.append(
            Warning(
                code="W_NO_DEDUCTIBLE_FOUND",
                path="deductible.in_network",
                message="No in-network deductible was found.",
            )
        )
    if oi is None:
        w.append(
            Warning(
                code="W_NO_OOP_FOUND",
                path="out_of_pocket_limit.in_network",
                message="No in-network out-of-pocket limit was found.",
            )
        )
    for key, svc in ext.services:
        for net in ("in_network", "out_of_network"):
            c = getattr(svc, net)
            if c is None:
                continue
            if (c.copay or 0) > 5000 or (c.coinsurance_pct or 0) > 100:
                w.append(
                    Warning(
                        code="W_IMPLAUSIBLE_AMOUNT",
                        path=f"services.{key}.{net}",
                        message="Implausible cost-sharing amount.",
                    )
                )
            if (
                c.covered
                and c.copay is None
                and c.coinsurance_pct is None
                and c.deductible_applies is None
                and not c.note
            ):
                w.append(
                    Warning(
                        code="W_COVERED_NO_PRICE",
                        path=f"services.{key}.{net}",
                        message="Covered, but no price was found.",
                    )
                )
    if anchored < 20:
        w.append(
            Warning(code="W_LOW_ANCHOR_COVERAGE", message=f"Only {anchored} of 26 benefit rows were found.")
        )
    if not ext.drug_tiers:
        w.append(
            Warning(
                code="W_NO_DRUG_TIERS", path="drug_tiers", message="No prescription drug tiers were found."
            )
        )
    return w
