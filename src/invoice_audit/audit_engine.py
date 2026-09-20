from __future__ import annotations

from pathlib import Path
from typing import Iterable

import pandas as pd

from .baseline import audit_basic, evaluate_hospital_1
from .canonical_lines import find_canonical_line_ids
from .contract_rules import (
    find_bundle_violations,
    find_exclusion_window_violations,
)
from .discount_rules import find_volume_discount_violations
from .duplicate_rules import find_cross_invoice_duplicates
from .premium_rules import find_premium_violations
from .price_unit_rules import find_price_and_unit_violations
from .service_matcher import build_match_report


def add_error_category(
    predictions: pd.DataFrame,
    invoice_ids: Iterable[str],
    category: str,
    confidence: float,
) -> None:
    invoice_ids = {
        str(invoice_id)
        for invoice_id in invoice_ids
    }

    if not invoice_ids:
        return

    mask = predictions["invoice_id"].astype(str).isin(
        invoice_ids
    )

    predictions.loc[mask, "flagged"] = 1

    def append_category(current: object) -> str:
        categories = {
            value
            for value in str(current).split("|")
            if value and value != "nan"
        }

        categories.add(category)
        return "|".join(sorted(categories))

    predictions.loc[
        mask,
        "error_category",
    ] = predictions.loc[
        mask,
        "error_category",
    ].apply(append_category)

    predictions.loc[
        mask,
        "confidence",
    ] = predictions.loc[
        mask,
        "confidence",
    ].apply(
        lambda current: max(
            float(current),
            confidence,
        )
    )


def find_unknown_services(
    match_report: pd.DataFrame,
) -> set[str]:
    mask = match_report[
        "suspected_unknown_service"
    ].fillna(False)

    return set(
        match_report.loc[
            mask,
            "invoice_id",
        ].astype(str)
    )


def find_daily_cap_adjustments(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> dict[str, int]:
    invoices = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    ).drop_duplicates(
        "invoice_id",
        keep="last",
    )

    data = match_report.merge(
        invoices[
            [
                "invoice_id",
                "patient_id",
            ]
        ],
        on="invoice_id",
        how="left",
        validate="many_to_one",
    )

    data["service_date_parsed"] = pd.to_datetime(
        data["service_date"],
        errors="coerce",
    )

    eligible = data[
        data["daily_cap"].notna()
        & data["service_date_parsed"].notna()
        & ~data[
            "suspected_unknown_service"
        ].fillna(False)
    ].copy()

    if eligible.empty:
        return {}

    eligible["quantity"] = pd.to_numeric(
        eligible["quantity"],
        errors="coerce",
    )

    eligible["daily_cap"] = pd.to_numeric(
        eligible["daily_cap"],
        errors="coerce",
    )

    eligible["unit_price_cents"] = pd.to_numeric(
        eligible["unit_price_cents"],
        errors="coerce",
    )

    eligible = eligible.dropna(
        subset=[
            "quantity",
            "daily_cap",
            "unit_price_cents",
            "patient_id",
            "matched_service",
        ]
    ).copy()

    if eligible.empty:
        return {}

    group_columns = [
        "patient_id",
        "service_date_parsed",
        "matched_service",
    ]

    eligible = eligible.sort_values(
        group_columns + ["line_id"],
        kind="stable",
    ).copy()

    eligible["prior_quantity"] = (
        eligible.groupby(
            group_columns,
            dropna=False,
        )["quantity"].cumsum()
        - eligible["quantity"]
    )

    eligible["remaining_capacity"] = (
        eligible["daily_cap"]
        - eligible["prior_quantity"]
    ).clip(lower=0)

    eligible["billable_quantity"] = eligible[
        [
            "quantity",
            "remaining_capacity",
        ]
    ].min(axis=1)

    eligible["excess_quantity"] = (
        eligible["quantity"]
        - eligible["billable_quantity"]
    ).clip(lower=0)

    eligible["cap_adjustment_cents"] = (
        eligible["excess_quantity"]
        * eligible["unit_price_cents"]
    ).round().astype(int)

    violations = eligible[
        eligible["cap_adjustment_cents"] > 0
    ].copy()

    if violations.empty:
        return {}

    adjustments = (
        violations.groupby("invoice_id")[
            "cap_adjustment_cents"
        ]
        .sum()
        .astype(int)
        .to_dict()
    )

    return {
        str(invoice_id): int(amount)
        for invoice_id, amount in adjustments.items()
    }


def apply_adjustments(
    predictions: pd.DataFrame,
    adjustments: dict[str, int],
) -> None:
    if not adjustments:
        return

    normalized_adjustments = {
        str(invoice_id): int(amount)
        for invoice_id, amount in adjustments.items()
    }

    values = (
        predictions["invoice_id"]
        .astype(str)
        .map(normalized_adjustments)
        .fillna(0)
        .astype(int)
    )

    predictions["expected_total_cents"] = (
        predictions["expected_total_cents"].astype(int)
        - values
    )


def build_enhanced_predictions(
    project_root: Path,
    hospital: int,
) -> pd.DataFrame:
    predictions = audit_basic(
        project_root,
        hospital,
    )

    # Keep the complete match report for rules that depend on
    # total contract-wide service volume.
    full_match_report = build_match_report(
        project_root,
        hospital,
    )

    # Create a second report containing only canonical line items.
    # This prevents duplicated invoice claims from being counted twice.
    canonical_line_ids = find_canonical_line_ids(
        project_root,
        hospital,
    )

    canonical_match_report = full_match_report.loc[
        full_match_report["line_id"]
        .astype(str)
        .isin(canonical_line_ids)
    ].copy()

    unknown_ids = find_unknown_services(
        canonical_match_report
    )

    add_error_category(
        predictions,
        unknown_ids,
        "unknown_service",
        0.95,
    )

    daily_cap_adjustments = (
        find_daily_cap_adjustments(
            project_root,
            canonical_match_report,
            hospital,
        )
    )

    add_error_category(
        predictions,
        daily_cap_adjustments.keys(),
        "daily_cap_exceeded",
        0.99,
    )

    apply_adjustments(
        predictions,
        daily_cap_adjustments,
    )

    duplicate_adjustments = (
        find_cross_invoice_duplicates(
            project_root,
            hospital,
        )
    )

    add_error_category(
        predictions,
        duplicate_adjustments.keys(),
        "cross_invoice_duplicate",
        0.99,
    )

    apply_adjustments(
        predictions,
        duplicate_adjustments,
    )

    bundle_adjustments = find_bundle_violations(
        project_root,
        canonical_match_report,
        hospital,
    )

    add_error_category(
        predictions,
        bundle_adjustments.keys(),
        "bundle_not_applied",
        0.99,
    )

    apply_adjustments(
        predictions,
        bundle_adjustments,
    )

    exclusion_adjustments = (
        find_exclusion_window_violations(
            project_root,
            canonical_match_report,
            hospital,
        )
    )

    add_error_category(
        predictions,
        exclusion_adjustments.keys(),
        "exclusion_window_violation",
        0.99,
    )

    apply_adjustments(
        predictions,
        exclusion_adjustments,
    )

    (
        omitted_premiums,
        incorrect_premiums,
    ) = find_premium_violations(
        project_root,
        canonical_match_report,
        hospital,
    )

    add_error_category(
        predictions,
        omitted_premiums.keys(),
        "premium_omitted",
        0.99,
    )

    apply_adjustments(
        predictions,
        omitted_premiums,
    )

    add_error_category(
        predictions,
        incorrect_premiums.keys(),
        "premium_incorrectly_applied",
        0.99,
    )

    apply_adjustments(
        predictions,
        incorrect_premiums,
    )

    # Volume-discount thresholds depend on the full submitted service
    # volume, so this rule intentionally uses the complete report.
    (
        omitted_discounts,
        incorrect_discounts,
    ) = find_volume_discount_violations(
        project_root,
        full_match_report,
        hospital,
    )

    add_error_category(
        predictions,
        omitted_discounts.keys(),
        "volume_discount_omitted",
        0.99,
    )

    apply_adjustments(
        predictions,
        omitted_discounts,
    )

    add_error_category(
        predictions,
        incorrect_discounts.keys(),
        "volume_discount_incorrectly_applied",
        0.99,
    )

    apply_adjustments(
        predictions,
        incorrect_discounts,
    )

    (
        wrong_unit_ids,
        price_adjustments,
    ) = find_price_and_unit_violations(
        project_root,
        canonical_match_report,
        hospital,
    )

    add_error_category(
        predictions,
        wrong_unit_ids,
        "wrong_unit_basis",
        0.98,
    )

    add_error_category(
        predictions,
        price_adjustments.keys(),
        "unit_price_mismatch",
        0.98,
    )

    apply_adjustments(
        predictions,
        price_adjustments,
    )

    predictions["expected_total_cents"] = (
        predictions["expected_total_cents"].astype(int)
    )

    predictions["billed_total_cents"] = (
        predictions["billed_total_cents"].astype(int)
    )

    return predictions


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]

    predictions = build_enhanced_predictions(
        project_root,
        hospital=1,
    )

    output_path = (
        project_root
        / "reports"
        / "hospital_1_enhanced_predictions.csv"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    predictions.to_csv(
        output_path,
        index=False,
    )

    evaluate_hospital_1(
        predictions,
        project_root
        / "labels"
        / "hospital_1_labels.csv",
    )


if __name__ == "__main__":
    main()