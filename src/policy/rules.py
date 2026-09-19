"""Resolving a spend rule for a (department, category).

Rules live in the `policy_rules` table so finance can change a limit from the dashboard.
`RuleSource` is the seam that made that possible without touching a call site: `DbRuleSource`
resolves against rows, `StaticRuleSource` against a literal mapping, and the engine cannot
tell the difference.

Nothing here touches the database. `DbRuleSource` takes a mapping that db/policies.py has
already loaded, which is what keeps this package free of SQL and the engine a pure function.

`DEFAULT_POLICY_RULES` is no longer read at runtime -- it is the seed, and the only definition
of what a fresh database starts with.
"""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Protocol

from .models import CATEGORIES, PolicyRule

# Used when a category has no entry at all, so lookup is total and never raises
ORG_FALLBACK = PolicyRule(
    per_expense_limit_cents=25_000, auto_approve_limit_cents=10_000
)

# Org-wide and category-independent, so it sits here rather than in PolicyRule (spec 7.2).
# Zero means every expense: since services/expense_flags.py reads the receipt and compares
# it against the claim, an expense with no receipt is an expense nothing can check.
RECEIPT_REQUIRED_OVER_CENTS = 0

# (department_id | None, category) -> rule. None means org-wide. Seed data only: what a fresh
# database is populated with, never consulted once the table exists.
DEFAULT_POLICY_RULES: Mapping[tuple[int | None, str], PolicyRule] = MappingProxyType(
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
    """An inverted pair would make the auto-approve band unreachable.

    The table carries the same rule as a CHECK, so this only guards the seed data.
    """
    for key, rule in DEFAULT_POLICY_RULES.items():
        if rule.auto_approve_limit_cents > rule.per_expense_limit_cents:
            raise ValueError(f"{key}: auto-approve limit exceeds per-expense limit")
    missing = {c for _, c in DEFAULT_POLICY_RULES} - set(CATEGORIES)
    if missing:
        raise ValueError(f"rules reference unknown categories: {sorted(missing)}")


_assert_rules_coherent()


class RuleSource(Protocol):
    def rule_for(self, department_id: int, category: str) -> PolicyRule: ...


class StaticRuleSource:
    """Resolves against a literal mapping, most specific first. Used by tests and the seed."""

    def __init__(
        self,
        rules: Mapping[tuple[int | None, str], PolicyRule] = DEFAULT_POLICY_RULES,
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


class DbRuleSource(StaticRuleSource):
    """The live source. Takes rows already loaded by db.policies.rules_map().

    A mapping rather than a connection on purpose: policy/ executes no SQL, so the engine
    stays a pure function of the values handed to it.
    """


def overridden_categories(
    department_id: int,
    rules: Mapping[tuple[int | None, str], PolicyRule],
) -> set[str]:
    """Categories where this department has its own rule instead of the org-wide one."""
    return {category for dept, category in rules if dept == department_id}


def resolved_rules(department_id: int, source: RuleSource) -> dict[str, PolicyRule]:
    """Every category's effective rule for one department. Backs the finance policy table."""
    return {category: source.rule_for(department_id, category) for category in CATEGORIES}
