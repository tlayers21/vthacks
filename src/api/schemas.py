"""Request validation at the route boundary.

The one place pydantic earns its keep, exactly as config.py reserves it for. Note what is
absent: no customer_id, no department_id. Identity comes from the session, so accepting it here
would hand the caller a way to spend someone else's budget.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from policy import CATEGORIES

Category = Literal[
    "travel",
    "food",
    "client meals",
    "software",
    "equipment",
    "marketing",
    "training",
    "office supplies",
    "shipping",
    "other",
]


class ExpenseIn(BaseModel):
    amount_cents: int = Field(gt=0, le=100_000_000)
    category: Category
    merchant: str | None = Field(default=None, max_length=100)
    description: str | None = Field(default=None, max_length=1000)
    # Preview only. On a real submit the attached file decides this, not the caller
    has_receipt: bool = False

    @field_validator("merchant", "description")
    @classmethod
    def _blank_to_none(cls, value: str | None) -> str | None:
        return value.strip() or None if value else None

    @field_validator("has_receipt", mode="before")
    @classmethod
    def _checkbox_to_bool(cls, value):
        # Multipart sends strings, so "false" would otherwise be truthy
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return value


class DecisionIn(BaseModel):
    approve: bool


class SwitchIn(BaseModel):
    user_id: str = Field(min_length=1, max_length=64)


def _categories_match_policy() -> None:
    if set(Category.__args__) != set(CATEGORIES):
        raise RuntimeError("api.schemas Category drifted from policy.CATEGORIES")


_categories_match_policy()
