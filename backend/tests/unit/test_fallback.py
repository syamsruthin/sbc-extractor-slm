import pytest

from sbcx.domain.benefits import BenefitsDocument, BenefitsExtras, FieldMeta, Source, Versions
from sbcx.domain.extract.fallback import CellOut, grounded, resolve
from sbcx.domain.sbc import SBCExtraction
from sbcx.infra.llm.base import LLMError
from sbcx.infra.llm.fake import FakeLLMClient

SVC = [
    "primary_care_visit",
    "specialist_visit",
    "preventive_care",
    "diagnostic_test",
    "imaging",
    "outpatient_facility_fee",
    "outpatient_surgeon_fee",
    "emergency_room",
    "emergency_transportation",
    "urgent_care",
    "hospital_facility_fee",
    "hospital_surgeon_fee",
    "mental_health_outpatient",
    "mental_health_inpatient",
    "pregnancy_office_visits",
    "childbirth_professional",
    "childbirth_facility",
    "home_health_care",
    "rehabilitation",
    "habilitation",
    "skilled_nursing",
    "durable_medical_equipment",
    "hospice",
    "child_eye_exam",
    "child_glasses",
    "child_dental_checkup",
]
CELL = {"covered": True, "copay": 25.0, "coinsurance_pct": None, "deductible_applies": None, "note": None}


def doc_with(text: str, conf: float, cell: dict | None = None) -> BenefitsDocument:
    services = {k: {"in_network": dict(CELL), "out_of_network": None} for k in SVC}
    services["imaging"]["in_network"] = (
        cell
        if cell is not None
        else {
            "covered": True,
            "copay": None,
            "coinsurance_pct": None,
            "deductible_applies": None,
            "note": None,
        }
    )
    ext = SBCExtraction.model_validate(
        {
            "plan_name": "P",
            "issuer": "I",
            "plan_type": "PPO",
            "coverage_period": None,
            "deductible": {"in_network": {"individual": 1000, "family": 2000}, "out_of_network": None},
            "out_of_pocket_limit": {
                "in_network": {"individual": 5000, "family": 10000},
                "out_of_network": None,
            },
            "services_before_deductible": [],
            "referral_required_for_specialist": None,
            "services": services,
            "drug_tiers": [],
            "excluded_services": [],
        }
    )
    prov = {
        f"services.imaging.in_network.{leaf}": FieldMeta(raw_text=text, confidence=conf)
        for leaf in ("covered", "copay", "coinsurance_pct", "deductible_applies", "note")
    }
    return BenefitsDocument(
        sha256="x",
        versions=Versions(schema_version="2", parser_version="2", guideline_version="1.4"),
        benefits=ext,
        extras=BenefitsExtras(),
        provenance=prov,
    )


def answer(**kw):
    base = {
        "id": "services.imaging.in_network",
        "covered": True,
        "copay": None,
        "coinsurance_pct": None,
        "deductible_applies": None,
        "note": None,
    }
    return {"cells": [base | kw]}


def test_override_when_grounded():
    d = doc_with("Coinsurance: 30% after deductible", 0.5)
    n = resolve(
        d, FakeLLMClient({"cell_fallback": [answer(coinsurance_pct=30.0, deductible_applies=True)]}), "m", 0.6
    )
    assert n == 1
    assert d.benefits.services.imaging.in_network.coinsurance_pct == 30.0
    assert d.provenance["services.imaging.in_network.copay"].source == Source.llm_fallback
    assert any(w.code == "W_FALLBACK_OVERRIDE" for w in d.warnings)


def test_rejects_invented_number():
    d = doc_with("Coinsurance after deductible", 0.5)
    resolve(d, FakeLLMClient({"cell_fallback": [answer(coinsurance_pct=30.0)]}), "m", 0.6)
    assert d.benefits.services.imaging.in_network.coinsurance_pct is None
    assert "needs_review" in d.provenance["services.imaging.in_network.copay"].reasons


def test_agreement_raises_confidence():
    d = doc_with("$25 copay", 0.5, dict(CELL))
    resolve(d, FakeLLMClient({"cell_fallback": [answer(copay=25.0)]}), "m", 0.6)
    m = d.provenance["services.imaging.in_network.copay"]
    assert m.source == Source.parser_llm and m.confidence >= 0.95


def test_llm_down_keeps_parser():
    d = doc_with("$25 copay", 0.5, dict(CELL))
    resolve(d, FakeLLMClient({"cell_fallback": [LLMError("down")]}), "m", 0.6)
    assert d.benefits.services.imaging.in_network.copay == 25.0
    assert "needs_review" in d.provenance["services.imaging.in_network.copay"].reasons


def test_high_confidence_not_sent():
    f = FakeLLMClient({"cell_fallback": []})
    assert resolve(doc_with("$25 copay", 0.9), f, "m", 0.6) == 0 and not f.calls


@pytest.mark.parametrize(
    "text, copay, pct, ok",
    [
        ("$40 copay", 40.0, None, True),
        ("$40 copay", 45.0, None, False),
        ("No charge", 0.0, 0.0, True),
        ("$1,500 then 20%", 1500.0, 20.0, True),
    ],
)
def test_grounded(text, copay, pct, ok):
    c = CellOut(id="x", covered=True, copay=copay, coinsurance_pct=pct, deductible_applies=None, note=None)
    assert grounded(c, text) is ok
