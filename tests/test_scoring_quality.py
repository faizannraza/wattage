import pytest

from wattage.scoring.quality import compute_quality_factor, downgrade_pass_rate


def test_no_quality_map_is_honestly_unmeasured() -> None:
    assert compute_quality_factor(None) == (1.0, False)
    assert compute_quality_factor({}) == (1.0, False)


def test_quality_map_without_eval_scores_is_unmeasured() -> None:
    assert compute_quality_factor({"tasks": {"t1": {"success": True}}}) == (1.0, False)


def test_quality_at_or_above_target_yields_full_factor() -> None:
    quality_map = {"tasks": {"t1": {"eval_score": 0.95}, "t2": {"eval_score": 0.92}}}
    factor, measured = compute_quality_factor(quality_map, target=0.90)
    assert measured is True
    assert factor == 1.0


def test_quality_below_target_scales_the_factor_down() -> None:
    quality_map = {"tasks": {"t1": {"eval_score": 0.45}}}
    factor, measured = compute_quality_factor(quality_map, target=0.90)
    assert measured is True
    assert factor == pytest.approx(0.5)


def test_factor_never_negative() -> None:
    quality_map = {"tasks": {"t1": {"eval_score": 0.0}}}
    factor, _ = compute_quality_factor(quality_map, target=0.90)
    assert factor >= 0.0


def test_downgrade_pass_rate_found() -> None:
    quality_map = {"downgrade_evals": {"tool_select@claude-haiku-4-5": {"pass_rate": 0.97}}}
    assert downgrade_pass_rate(quality_map, "tool_select", "claude-haiku-4-5") == 0.97


def test_downgrade_pass_rate_absent_returns_none() -> None:
    assert downgrade_pass_rate(None, "tool_select", "claude-haiku-4-5") is None
    assert downgrade_pass_rate({}, "tool_select", "claude-haiku-4-5") is None
    assert downgrade_pass_rate(
        {"downgrade_evals": {}}, "tool_select", "claude-haiku-4-5"
    ) is None
