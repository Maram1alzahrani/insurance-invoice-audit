from pathlib import Path

import pandas as pd


HOSPITAL_1_BUNDLES = [
    (
        "Advanced Cardiac Recovery Room Occupancy",
        "Routine Cardiac Specimen Analysis",
        16400,
        19150,
    ),
    (
        "Extended Palliative Laboratory Panel",
        "Inpatient Ophthalmic Radiotherapy Fraction",
        15175,
        21500,
    ),
    (
        "Inpatient Hepatic Physiotherapy Session",
        "Specialist Otolaryngologic Theatre Time",
        37500,
        7050,
    ),
]


HOSPITAL_1_EXCLUSIONS = [
    (
        "Advanced Metabolic Anaesthesia Administration",
        "Standard Endocrine Endoscopic Procedure",
        7,
    ),
    (
        "Continuous Immunologic Theatre Time",
        "Supervised Otolaryngologic Sterilisation Service",
        21,
    ),
    (
        "Intensive Ophthalmic Case Conference",
        "Continuous Otolaryngologic Telemetry Monitoring",
        7,
    ),
    (
        "Postoperative Ophthalmic Radiotherapy Fraction",
        "Inpatient Palliative Isolation Room Occupancy",
        30,
    ),
    (
        "Routine Immunologic Ward Bed Occupancy",
        "Comprehensive Otolaryngologic Theatre Time",
        10,
    ),
    (
        "Standard Paediatric Biopsy Procedure",
        "Advanced Infectious Critical Care Occupancy",
        10,
    ),
]


def add_patient_context(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> pd.DataFrame:
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

    return data


def find_bundle_violations(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> dict[str, int]:
    """Return invoice_id and overbilled amount from missed bundles."""

    if hospital != 1:
        return {}

    data = add_patient_context(
        project_root,
        match_report,
        hospital,
    )

    adjustments: dict[str, int] = {}

    grouped = data.dropna(subset=["service_date_parsed"]).groupby(
        ["patient_id", "service_date_parsed"],
        sort=False,
    )

    for _, group in grouped:
        present_services = set(group["matched_service"])

        for service_a, service_b, rate_a, rate_b in HOSPITAL_1_BUNDLES:
            if not {service_a, service_b}.issubset(present_services):
                continue

            expected_rates = {
                service_a: rate_a,
                service_b: rate_b,
            }

            bundle_lines = group[
                group["matched_service"].isin(expected_rates)
            ]

            for row in bundle_lines.itertuples(index=False):
                expected_rate = expected_rates[row.matched_service]

                if (
                    row.unit_price_cents == row.base_rate_cents
                    and row.unit_price_cents != expected_rate
                ):
                    overbilled = (
                        int(row.unit_price_cents) - expected_rate
                    ) * int(row.quantity)

                    adjustments[row.invoice_id] = (
                        adjustments.get(row.invoice_id, 0)
                        + overbilled
                    )

    return adjustments


def find_exclusion_window_violations(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> dict[str, int]:
    """Return invoice_id and non-billable amount from exclusion violations."""

    if hospital != 1:
        return {}

    data = add_patient_context(
        project_root,
        match_report,
        hospital,
    )

    reliable = data[
        data["service_date_parsed"].notna()
        & (data["match_score"] >= 95)
        & ~data["suspected_unknown_service"].fillna(False)
    ].copy()

    excluded_line_ids: set[str] = set()

    for excluded_service, trigger_service, window_days in HOSPITAL_1_EXCLUSIONS:
        excluded_lines = reliable[
            reliable["matched_service"] == excluded_service
        ]

        trigger_lines = reliable[
            reliable["matched_service"] == trigger_service
        ]

        if excluded_lines.empty or trigger_lines.empty:
            continue

        pairs = excluded_lines.merge(
            trigger_lines,
            on="patient_id",
            suffixes=("_excluded", "_trigger"),
        )

        date_difference = (
            pairs["service_date_parsed_excluded"]
            - pairs["service_date_parsed_trigger"]
        ).abs().dt.days

        violating_pairs = pairs[
            date_difference <= window_days
        ]

        excluded_line_ids.update(
            violating_pairs["line_id_excluded"].astype(str)
        )

    violations = reliable[
        reliable["line_id"].astype(str).isin(excluded_line_ids)
    ].copy()

    if violations.empty:
        return {}

    violations["non_billable_amount"] = (
        violations["quantity"].astype(int)
        * violations["unit_price_cents"].astype(int)
    )

    return (
        violations.groupby("invoice_id")["non_billable_amount"]
        .sum()
        .astype(int)
        .to_dict()
    )