"""The spend rules themselves, as a typed constant.

Rules are code, not rows: finance cannot change a limit without a deploy. That is a deliberate
trade -- it keeps the rule set reviewable in git and lets the engine stay a pure function with
no database behind it. `RuleSource` is the seam where a database-backed source drops in later
without touching a single call site.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from .models import CATEGORIES, PolicyRule

# Used when a category has no entry at all, so lookup is total and never raises
ORG_FALLBACK = PolicyRule(
    per_expense_limit_cents=25_000, auto_approve_limit_cents=10_000
)

# (department_id | None, category) -> rule. None means org-wide.
POLICY_RULES: Mapping[tuple[int | None, str], PolicyRule] = MappingProxyType(
    {
        # Org-wide defaults, one per category
        (None, "travel"): PolicyRule(300_000, 50_000),
        (None, "food"): PolicyRule(15_000, 7_500),
        (None, "client meals"): PolicyRule(50_000, 10_000),
        (None, "software"): PolicyRule(250_000, 25_000),
        (None, "equipment"): PolicyRule(500_000, 100_000),
        (None, "marketing"): PolicyRule(1_000_000, 100_000),
        (None, "training"): PolicyRule(250_000, 50_000),
        (None, "office supplies"): PolicyRule(50_000, 10_000),
        (None, "shipping"): PolicyRule(50_000, 10_000),
        (None, "other"): PolicyRule(25_000, 10_000),
        # Engineering buys cloud and tooling, so its software ceiling is higher
        (1, "software"): PolicyRule(1_000_000, 100_000),
        # Marketing's whole job is spending on marketing
        (2, "marketing"): PolicyRule(2_500_000, 250_000),
    }
)


def _assert_rules_coherent() -> None:
    """An inverted pair would make the auto-approve band unreachable."""
    for key, rule in POLICY_RULES.items():
        if rule.auto_approve_limit_cents > rule.per_expense_limit_cents:
            raise ValueError(f"{key}: auto-approve limit exceeds per-expense limit")
    missing = {c for _, c in POLICY_RULES} - set(CATEGORIES)
    if missing:
        raise ValueError(f"rules reference unknown categories: {sorted(missing)}")


_assert_rules_coherent()


class RuleSource(Protocol):
    def rule_for(self, department_id: int, category: str) -> PolicyRule: ...


class StaticRuleSource:
    """Resolves against POLICY_RULES, most specific first."""

    def __init__(
        self,
        rules: Mapping[tuple[int | None, str], PolicyRule] = POLICY_RULES,
        fallback: PolicyRule = ORG_FALLBACK,
    ) -> None:
        self._rules = rules
        self._fallback = fallback

    def rule_for(self, department_id: int, category: str) -> PolicyRule:
        return (
            self._rules.get((department_id, category))
            or self._rules.get((None, category))
            or self._fallback
        )


_default_source: RuleSource = StaticRuleSource()


def default_rule_source() -> RuleSource:
    return _default_source


def overridden_categories(
    department_id: int,
    rules: Mapping[tuple[int | None, str], PolicyRule] = POLICY_RULES,
) -> set[str]:
    """Categories where this department has its own rule instead of the org-wide one."""
    return {category for dept, category in rules if dept == department_id}


def resolved_rules(
    department_id: int, source: RuleSource | None = None
) -> dict[str, PolicyRule]:
    """Every category's effective rule for one department. Backs the finance policy table."""
    src = source or default_rule_source()
    return {category: src.rule_for(department_id, category) for category in CATEGORIES}
