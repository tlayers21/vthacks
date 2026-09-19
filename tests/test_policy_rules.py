import pytest

from policy import CATEGORIES, ORG_FALLBACK, POLICY_RULES, PolicyRule, StaticRuleSource


@pytest.fixture
def source() -> StaticRuleSource:
    return StaticRuleSource()


def test_department_override_beats_org_default(source):
    # Engineering (1) has its own software rule
    assert source.rule_for(1, "software") == POLICY_RULES[(1, "software")]
    assert source.rule_for(1, "software") != POLICY_RULES[(None, "software")]


def test_department_without_override_falls_back_to_org(source):
    assert source.rule_for(3, "software") == POLICY_RULES[(None, "software")]


def test_unknown_department_falls_back_to_org(source):
    assert source.rule_for(999, "travel") == POLICY_RULES[(None, "travel")]


def test_unknown_category_falls_back_to_org_fallback(source):
    assert source.rule_for(1, "nonexistent") == ORG_FALLBACK


@pytest.mark.parametrize("category", CATEGORIES)
def test_every_category_resolves(source, category):
    assert isinstance(source.rule_for(1, category), PolicyRule)


@pytest.mark.parametrize(("key", "rule"), POLICY_RULES.items())
def test_auto_approve_limit_never_exceeds_per_expense_limit(key, rule):
    assert rule.auto_approve_limit_cents <= rule.per_expense_limit_cents


def test_injected_rules_replace_the_defaults():
    tiny = PolicyRule(per_expense_limit_cents=100, auto_approve_limit_cents=50)
    source = StaticRuleSource(rules={(None, "food"): tiny}, fallback=tiny)
    assert source.rule_for(1, "food") == tiny
