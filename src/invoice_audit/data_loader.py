from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd


INVOICE_COLUMNS = {
    "invoice_id",
    "hospital_id",
    "contract_number",
    "invoice_date",
    "patient_id",
    "facility_code",
    "plan_tier",
    "admission_date",
    "discharge_date",
    "invoice_total_cents",
}

LINE_COLUMNS = {
    "line_id",
    "invoice_id",
    "line_no",
    "service_date",
    "description",
    "quantity",
    "unit_basis_as_billed",
    "unit_price_cents",
    "line_total_cents",
}


@dataclass
class HospitalData:
    invoices: pd.DataFrame
    line_items: pd.DataFrame


def validate_columns(
    frame: pd.DataFrame,
    required: set[str],
    filename: str,
) -> None:
    missing = required - set(frame.columns)

    if missing:
        raise ValueError(
            f"{filename} is missing columns: {sorted(missing)}"
        )


def normalize_descriptions(
    descriptions: pd.Series,
) -> pd.Series:
    return (
        descriptions.astype("string")
        .str.replace(
            r"/[A-Za-z]{2}-\d+",
            " ",
            regex=True,
        )
        .str.lower()
        .str.replace(
            r"[^a-z0-9]+",
            " ",
            regex=True,
        )
        .str.replace(
            r"\s+",
            " ",
            regex=True,
        )
        .str.strip()
    )


def load_hospital_data(
    project_root: Path,
    hospital: int,
) -> HospitalData:
    if hospital not in range(1, 6):
        raise ValueError(
            "hospital must be between 1 and 5"
        )

    invoice_path = (
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    )

    line_path = (
        project_root
        / "invoices"
        / f"hospital_{hospital}_line_items.csv"
    )

    invoices = pd.read_csv(invoice_path)
    lines = pd.read_csv(line_path)

    validate_columns(
        invoices,
        INVOICE_COLUMNS,
        invoice_path.name,
    )

    validate_columns(
        lines,
        LINE_COLUMNS,
        line_path.name,
    )

    # Keep the original columns unchanged and add parsed columns.
    invoices["invoice_date_parsed"] = pd.to_datetime(
        invoices["invoice_date"],
        errors="coerce",
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

    lines["description_normalized"] = (
        normalize_descriptions(
            lines["description"]
        )
    )

    lines["calculated_line_total_cents"] = (
        lines["quantity"]
        * lines["unit_price_cents"]
    )

    return HospitalData(
        invoices=invoices,
        line_items=lines,
    )


def build_quality_summary(
    data: HospitalData,
) -> dict[str, object]:
    invoices = data.invoices
    lines = data.line_items

    invoice_ids = set(invoices["invoice_id"])
    line_invoice_ids = set(lines["invoice_id"])

    duplicate_invoice_mask = invoices.duplicated(
        "invoice_id",
        keep=False,
    )

    canonical_invoices = (
        invoices.drop_duplicates(
            "invoice_id",
            keep="last",
        )
        .set_index("invoice_id")
    )

    line_sums = lines.groupby("invoice_id")[
        "line_total_cents"
    ].sum()

    comparable = canonical_invoices.join(
        line_sums.rename("line_sum")
    )

    return {
        "invoice_rows": int(len(invoices)),
        "unique_invoice_ids": int(
            invoices["invoice_id"].nunique()
        ),
        "duplicate_invoice_ids": int(
            invoices.loc[
                duplicate_invoice_mask,
                "invoice_id",
            ].nunique()
        ),
        "line_item_rows": int(len(lines)),
        "unique_line_ids": int(
            lines["line_id"].nunique()
        ),
        "orphan_line_invoice_ids": int(
            len(line_invoice_ids - invoice_ids)
        ),
        "invoices_without_lines": int(
            len(invoice_ids - line_invoice_ids)
        ),
        "malformed_invoice_dates": int(
            invoices["invoice_date_parsed"]
            .isna()
            .sum()
        ),
        "malformed_service_dates": int(
            lines["service_date_parsed"]
            .isna()
            .sum()
        ),
        "line_arithmetic_mismatches": int(
            (
                lines["calculated_line_total_cents"]
                != lines["line_total_cents"]
            ).sum()
        ),
        "invoice_total_mismatches": int(
            (
                comparable["invoice_total_cents"]
                != comparable["line_sum"]
            ).sum()
        ),
        "missing_invoice_values": int(
            invoices[list(INVOICE_COLUMNS)]
            .isna()
            .sum()
            .sum()
        ),
        "missing_line_values": int(
            lines[list(LINE_COLUMNS)]
            .isna()
            .sum()
            .sum()
        ),
    }


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    summaries = {}

    for hospital in range(1, 6):
        hospital_data = load_hospital_data(
            project_root,
            hospital,
        )

        summaries[f"hospital_{hospital}"] = (
            build_quality_summary(hospital_data)
        )

    output_path = (
        project_root
        / "reports"
        / "data_quality_summary.json"
    )

    output_path.write_text(
        json.dumps(summaries, indent=2),
        encoding="utf-8",
    )

    for hospital, summary in summaries.items():
        print(hospital, summary)

    print(
        f"Saved to {output_path.relative_to(project_root)}"
    )