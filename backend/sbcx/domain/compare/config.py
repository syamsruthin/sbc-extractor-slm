"""Versioned engine configuration: reference prices and usage scenarios (YAML under backend/config)."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from sbcx.domain.comparison import Event, Scenario
from sbcx.domain.display import DRUG_LABELS, SERVICE_LABELS


@dataclass(frozen=True)
class ReferencePrices:
    version: str
    source: str
    services: dict[str, float]
    drugs: dict[str, float]

    def with_overrides(self, overrides: dict[str, float]) -> ReferencePrices:
        s, d = dict(self.services), dict(self.drugs)
        for k, v in overrides.items():
            if k in s:
                s[k] = float(v)
            elif k.removeprefix("drug:") in d:
                d[k.removeprefix("drug:")] = float(v)
        return ReferencePrices(self.version + ("+overrides" if overrides else ""), self.source, s, d)

    def flat(self) -> dict[str, float]:
        return {**self.services, **{f"drug:{k}": v for k, v in self.drugs.items()}}

    @staticmethod
    def labels() -> dict[str, str]:
        return {**SERVICE_LABELS, **{f"drug:{k}": v for k, v in DRUG_LABELS.items() if k != "other"}}


@dataclass(frozen=True)
class ScenarioConfig:
    version: str
    event_types: dict[str, dict[str, Any]]
    presets: list[Scenario]

    def preset(self, sid: str) -> Scenario | None:
        return next((p for p in self.presets if p.id == sid), None)


@lru_cache
def load_prices(config_dir: str) -> ReferencePrices:
    d = yaml.safe_load((Path(config_dir) / "reference_prices.yaml").read_text())
    return ReferencePrices(
        str(d["version"]),
        d.get("source", ""),
        {k: float(v) for k, v in d["services"].items()},
        {k: float(v) for k, v in d["drugs"].items()},
    )


@lru_cache
def load_scenarios(config_dir: str) -> ScenarioConfig:
    d = yaml.safe_load((Path(config_dir) / "scenarios.yaml").read_text())
    presets = [
        Scenario(
            id=p["id"],
            label=p["label"],
            description=p.get("description", ""),
            events=[Event(**e) for e in p["events"]],
        )
        for p in d["presets"]
    ]
    return ScenarioConfig(str(d["version"]), d["event_types"], presets)
