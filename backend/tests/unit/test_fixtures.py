from sbcx.domain.comparison import ComparisonResult
from tests.fixtures import f1, f1_compare


def test_f1_reproduces_stored_scenario_totals():
    """Scenario math is unchanged since engine 1.2.0: every total and out-of-pocket range matches the stored result."""
    stored = ComparisonResult.model_validate(f1()["result"])
    now = f1_compare()
    assert [s.scenario.id for s in now.scenarios] == [s.scenario.id for s in stored.scenarios]
    for a, b in zip(now.scenarios, stored.scenarios, strict=True):
        for k in b.per_plan:
            assert a.per_plan[k].total == b.per_plan[k].total, (a.scenario.id, k)
            assert a.per_plan[k].out_of_pocket == b.per_plan[k].out_of_pocket, (a.scenario.id, k)
    assert now.headline.best_case == stored.headline.best_case
    assert now.headline.worst_case == stored.headline.worst_case
