from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd


VOLUME_DISCOUNTS = {
    "Ambulatory Pulmonary Recovery Room Occupancy": {
        "unit_basis": "per_night",
        "base_rate": 112825,
        "thresholds": [(60, 10)],
    },
    "Comprehensive Infectious Nursing Observation": {
        "unit_basis": "per_day",
        "base_rate": 169825,
        "thresholds": [(80, 10), (240, 25)],
    },
    "Extended Geriatric Wound Care": {
        "unit_basis": "per_item",
        "base_rate": 10100,
        "thresholds": [(60, 15)],
    },
    "Intensive Gastrointestinal Isolation Room Occupancy": {
        "unit_basis": "per_night",
        "base_rate": 160725,
        "thresholds": [(60, 12), (180, 30)],
    },
    "Intermittent Pulmonary Rehabilitation Programme": {
        "unit_basis": "per_visit",
        "base_rate": 13450,
        "thresholds": [(120, 10)],
    },
    "Preoperative Immunologic Endoscopic Procedure": {
        "unit_basis": "per_procedure",
        "base_rate": 151975,
        "thresholds": [(80, 12), (240, 20)],
    },
    "Standard Otolaryngologic Radiotherapy Fraction": {
        "unit_basis": "per_item",
        "base_rate": 25250,
        "thresholds": [(60, 12), (180, 30)],
    },
}


def discounted_rate(
    base_rate: int,
    discount_percentage: int,
) -> int:
    value = (
        Decimal(base_rate)
        * Decimal(100 - discount_percentage)
        / Decimal(100)
    )

    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def find_volume_discount_violations(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Return billed-minus-expected adjustments for:

    1. omitted discounts
    2. incorrectly applied discounts
    """

    if hospital != 1:
        return {}, {}

    data = match_report.copy()

    data["service_date_parsed"] = pd.to_datetime(
        data["service_date"],
        errors="coerce",
    )

    data = data[
        data["service_date_parsed"].notna()
    ].copy()

    omitted: dict[str, int] = {}
    incorrectly_applied: dict[str, int] = {}

    for service, rule in VOLUME_DISCOUNTS.items():
        base_rate = int(rule["base_rate"])
        unit_basis = str(rule["unit_basis"])
        thresholds = list(rule["thresholds"])

        allowed_rates = {base_rate}

        for _, percentage in thresholds:
            allowed_rates.add(
                discounted_rate(
                    base_rate,
                    percentage,
                )
            )

        text_match = (
            data["matched_service"] == service
        )

        price_and_basis_match = (
            data["unit_basis_as_billed"].eq(unit_basis)
            & data["unit_price_cents"].isin(allowed_rates)
        )

        # Price and basis act as a second identity signal when the
        # free-text description is heavily abbreviated.
        candidates = data[
            text_match | price_and_basis_match
        ].copy()

        candidates = candidates.sort_values(
            [
                "service_date_parsed",
                "line_id",
            ]
        )

        candidates["prior_quantity"] = (
            candidates["quantity"].cumsum()
            - candidates["quantity"]
        )

        reliable_targets = candidates[
            candidates["matched_service"].eq(service)
            & candidates["unit_basis_matches"].fillna(False)
            & candidates["unit_price_cents"].isin(allowed_rates)
            & ~candidates[
                "suspected_unknown_service"
            ].fillna(False)
        ]

        for row in reliable_targets.itertuples(index=False):
            discount_percentage = 0

            for threshold, percentage in thresholds:
                if int(row.prior_quantity) > threshold:
                    discount_percentage = percentage

            expected_rate = discounted_rate(
                base_rate,
                discount_percentage,
            )

            billed_rate = int(row.unit_price_cents)
            quantity = int(row.quantity)

            if billed_rate == expected_rate:
                continue

            adjustment = (
                billed_rate - expected_rate
            ) * quantity

            if billed_rate > expected_rate:
                omitted[row.invoice_id] = (
                    omitted.get(row.invoice_id, 0)
                    + adjustment
                )
            else:
                incorrectly_applied[row.invoice_id] = (
                    incorrectly_applied.get(
                        row.invoice_id,
                        0,
                    )
                    + adjustment
                )

    return omitted, incorrectly_applied