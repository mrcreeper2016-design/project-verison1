"""Canonical list of companies the platform supports.

A user (DevRel/speaker/applicant) can either belong to one of these companies
or have no company at all. The list is intentionally short and hard-coded —
when business grows, move this to a DB-backed `Company` model.
"""
from __future__ import annotations


ALLOWED_COMPANIES: tuple[str, ...] = (
    "Сбер",
    "Т-Банк",
    "Авито",
    "Яндекс",
)


def get_company_choices(blank_label: str = "— без компании —") -> list[tuple[str, str]]:
    """Choices for a Django ChoiceField — empty option first."""
    return [("", blank_label)] + [(c, c) for c in ALLOWED_COMPANIES]


def is_allowed_company(value: str) -> bool:
    return value == "" or value in ALLOWED_COMPANIES
