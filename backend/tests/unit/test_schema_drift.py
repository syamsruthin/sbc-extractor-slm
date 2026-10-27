"""The backend's copy of the v1 schema must stay identical to src/schema.py, which the labels,
gold set and eval/score.py are built on."""

import importlib.util

from sbcx.domain import sbc
from sbcx.domain.benefits import BenefitsDocument
from sbcx.domain.comparison import ComparisonRequest, ComparisonResult


def _load_src_schema(repo_root):
    spec = importlib.util.spec_from_file_location("src_schema", repo_root / "src/schema.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sbc_schema_matches_src(repo_root):
    src = _load_src_schema(repo_root)
    assert sbc.SBCExtraction.model_json_schema() == src.SBCExtraction.model_json_schema()
    assert sbc.ANNOTATION_GUIDELINES == src.ANNOTATION_GUIDELINES


def test_contract_schemas_build():
    for model in (BenefitsDocument, ComparisonRequest, ComparisonResult):
        assert model.model_json_schema()["title"] == model.__name__


def test_comparison_request_rules():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ComparisonRequest(document_ids=["a"])
    with pytest.raises(ValidationError):
        ComparisonRequest(document_ids=["a", "a"])
    with pytest.raises(ValidationError):
        ComparisonRequest(document_ids=["a", "b"], base_document_id="c")
    assert ComparisonRequest(document_ids=["a", "b"]).scenario_ids == ["low", "moderate", "high"]


def test_openapi_builds(client):
    assert client.get("/openapi.json").status_code == 200
