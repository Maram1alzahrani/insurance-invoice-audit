from pathlib import Path
import re

import pandas as pd


def normalize_description(description: object) -> str:
    text = str(description)

    text = re.sub(
        r"/[A-Za-z]{2}-\d+",
        " ",
        text,
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text.lower(),
    )

    return " ".join(text.split())


def find_cross_invoice_duplicates(
    project_root: Path,
    hospital: int,
) -> dict[str, int]:
    """
    Find an exact service copied from a valid hospital stay
    into another invoice for the same patient.
    """

    invoices = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    ).drop_duplicates(
        "invoice_id",
        keep="last",
    )

    lines = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_line_items.csv"
    )

    invoices["admission_date_parsed"] = pd.to_datetime(
        invoices["admission_date"],
        errors="coerce",
    )

    invoices["discharge_date_parsed"] = pd.to_datetime(
        invoices["discharge_date"],
        errors="coerce",
    )

    lines["service_date_parsed"] = pd.to_datetime(
        lines["service_date"],
        errors="coerce",
    )

    lines["description_normalized"] = lines[
        "description"
    ].map(normalize_description)

    data = lines.merge(
        invoices[
            [
                "invoice_id",
                "patient_id",
                "admission_date_parsed",
                "discharge_date_parsed",
            ]
        ],
        on="invoice_id",
        how="left",
        validate="many_to_one",
    )

    data["within_hospital_stay"] = (
        data["service_date_parsed"].notna()
        & data["service_date_parsed"].between(
            data["admission_date_parsed"],
            data["discharge_date_parsed"],
        )
    )

    signature = [
        "patient_id",
        "service_date_parsed",
        "description_normalized",
        "quantity",
        "unit_basis_as_billed",
        "unit_price_cents",
        "line_total_cents",
    ]

    duplicate_candidates = data[
        data.duplicated(
            signature,
            keep=False,
        )
        & data["service_date_parsed"].notna()
    ].copy()

    invalid_line_ids: set[str] = set()

    for _, group in duplicate_candidates.groupby(
        signature,
        dropna=False,
    ):
        if group["invoice_id"].nunique() < 2:
            continue

        # Only flag the copied occurrence when another occurrence
        # belongs to the patient's genuine hospital stay.
        if group["within_hospital_stay"].any():
            copied_lines = group[
                ~group["within_hospital_stay"]
            ]

            invalid_line_ids.update(
                copied_lines["line_id"].astype(str)
            )

    violations = data[
        data["line_id"].astype(str).isin(
            invalid_line_ids
        )
    ].copy()

    if violations.empty:
        return {}

    violations["duplicate_amount"] = (
        violations["quantity"].astype(int)
        * violations["unit_price_cents"].astype(int)
    )

    return (
        violations.groupby("invoice_id")[
            "duplicate_amount"
        ]
        .sum()
        .astype(int)
        .to_dict()
    )