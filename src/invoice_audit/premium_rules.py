from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd


THRESHOLD_PREMIUMS = {
    "Ambulatory Ophthalmic Case Conference": (6, 20),
    "Ambulatory Ophthalmic Dialysis Session": (10, 20),
    "Continuous Musculoskeletal Wound Care": (8, 40),
    "Emergency Dermatologic Case Conference": (10, 40),
    "Preoperative Geriatric Ventilation Support": (8, 20),
    "Preoperative Renal Wound Care": (8, 25),
    "Routine Psychiatric Rehabilitation Programme": (8, 25),
    "Specialist Neurological Recovery Room Occupancy": (8, 30),
    "Standard Pulmonary Dialysis Session": (8, 25),
}


NON_BUSINESS_DAY_UPLIFTS = {
    "Advanced Neurological Consultation": 20,
    "Assisted Geriatric Infusion Therapy": 12,
    "Assisted Infectious Discharge Planning": 12,
    "Emergency Renal Radiotherapy Fraction": 20,
    "Focused Orthopaedic Transport Service": 10,
    "Specialist Dermatologic Transport Service": 12,
    "Supervised Musculoskeletal Dialysis Session": 12,
}


def apply_percentage(
    amount_cents: int,
    percentage: int,
) -> int:
    value = (
        Decimal(int(amount_cents))
        * Decimal(100 + percentage)
        / Decimal(100)
    )

    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def find_premium_violations(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """
    Return two dictionaries containing billed minus expected adjustments:

    1. premium omitted
    2. premium incorrectly applied
    """

    if hospital != 1:
        return {}, {}

    invoices = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    ).drop_duplicates("invoice_id", keep="last")

    data = match_report.merge(
        invoices[["invoice_id", "patient_id"]],
        on="invoice_id",
        how="left",
        validate="many_to_one",
    )

    data["service_date_parsed"] = pd.to_datetime(
        data["service_date"],
        errors="coerce",
    )

    premium_services = (
        set(THRESHOLD_PREMIUMS)
        | set(NON_BUSINESS_DAY_UPLIFTS)
    )

    data = data[
        data["matched_service"].isin(premium_services)
        & data["service_date_parsed"].notna()
        & (data["match_score"] >= 95)
        & data["unit_basis_matches"].fillna(False)
        & ~data["suspected_unknown_service"].fillna(False)
    ].copy()

    if data.empty:
        return {}, {}

    def get_percentage(service: str) -> int:
        if service in THRESHOLD_PREMIUMS:
            return THRESHOLD_PREMIUMS[service][1]

        return NON_BUSINESS_DAY_UPLIFTS[service]

    data["premium_percentage"] = data[
        "matched_service"
    ].map(get_percentage)

    data["premium_rate_cents"] = data.apply(
        lambda row: apply_percentage(
            int(row["base_rate_cents"]),
            int(row["premium_percentage"]),
        ),
        axis=1,
    )

    # This protects against ambiguous short descriptions.
    data = data[
        (data["unit_price_cents"] == data["base_rate_cents"])
        | (
            data["unit_price_cents"]
            == data["premium_rate_cents"]
        )
    ].copy()

    if data.empty:
        return {}, {}

    threshold_mask = data["matched_service"].isin(
        THRESHOLD_PREMIUMS
    )

    threshold_lines = data[threshold_mask].copy()

    if not threshold_lines.empty:
        threshold_lines["daily_quantity"] = (
            threshold_lines.groupby(
                [
                    "patient_id",
                    "service_date_parsed",
                    "matched_service",
                ]
            )["quantity"].transform("sum")
        )

        daily_quantities = threshold_lines.set_index(
            "line_id"
        )["daily_quantity"]

        data["daily_quantity"] = data["line_id"].map(
            daily_quantities
        )
    else:
        data["daily_quantity"] = pd.NA

    omitted: dict[str, int] = {}
    incorrectly_applied: dict[str, int] = {}

    for row in data.itertuples(index=False):
        if row.matched_service in THRESHOLD_PREMIUMS:
            threshold, _ = THRESHOLD_PREMIUMS[
                row.matched_service
            ]

            premium_required = (
                int(row.daily_quantity) > threshold
            )
        else:
            premium_required = (
                row.service_date_parsed.weekday() >= 5
            )

        base_rate = int(row.base_rate_cents)
        premium_rate = int(row.premium_rate_cents)
        billed_rate = int(row.unit_price_cents)
        quantity = int(row.quantity)

        if premium_required and billed_rate == base_rate:
            adjustment = (
                billed_rate - premium_rate
            ) * quantity

            omitted[row.invoice_id] = (
                omitted.get(row.invoice_id, 0)
                + adjustment
            )

        elif not premium_required and billed_rate == premium_rate:
            adjustment = (
                billed_rate - base_rate
            ) * quantity

            incorrectly_applied[row.invoice_id] = (
                incorrectly_applied.get(row.invoice_id, 0)
                + adjustment
            )

    return omitted, incorrectly_applied