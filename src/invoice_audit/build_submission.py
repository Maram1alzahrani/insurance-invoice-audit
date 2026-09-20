from __future__ import annotations

from pathlib import Path

import pandas as pd


HOSPITALS = (3, 4)

SUBMISSION_COLUMNS = [
    "invoice_id",
    "flagged",
    "error_category",
    "expected_total_cents",
    "billed_total_cents",
    "confidence",
]


def validate_integer_column(
    frame: pd.DataFrame,
    column: str,
    hospital: int,
) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")

    if values.isna().any():
        raise ValueError(
            f"Hospital {hospital}: {column} contains missing "
            "or non-numeric values."
        )

    if (values % 1 != 0).any():
        raise ValueError(
            f"Hospital {hospital}: {column} must contain "
            "integer cents only."
        )

    return values.astype("int64")


def load_and_validate(
    project_root: Path,
    hospital: int,
) -> pd.DataFrame:
    prediction_path = (
        project_root
        / "reports"
        / f"hospital_{hospital}_predictions.csv"
    )
    invoice_path = (
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    )

    if not prediction_path.exists():
        raise FileNotFoundError(
            f"Missing prediction file: {prediction_path}"
        )

    predictions = pd.read_csv(prediction_path)
    missing_columns = [
        column
        for column in SUBMISSION_COLUMNS
        if column not in predictions.columns
    ]

    if missing_columns:
        raise ValueError(
            f"Hospital {hospital}: missing columns "
            f"{missing_columns}"
        )

    predictions = predictions[SUBMISSION_COLUMNS].copy()
    predictions["invoice_id"] = (
        predictions["invoice_id"].astype(str).str.strip()
    )

    if predictions["invoice_id"].duplicated().any():
        duplicated = predictions.loc[
            predictions["invoice_id"].duplicated(keep=False),
            "invoice_id",
        ].tolist()
        raise ValueError(
            f"Hospital {hospital}: duplicated invoice IDs: "
            f"{duplicated[:5]}"
        )

    invoice_ids = set(
        pd.read_csv(invoice_path, usecols=["invoice_id"])[
            "invoice_id"
        ]
        .astype(str)
        .str.strip()
        .unique()
    )
    prediction_ids = set(predictions["invoice_id"])

    missing_ids = invoice_ids - prediction_ids
    unexpected_ids = prediction_ids - invoice_ids

    if missing_ids or unexpected_ids:
        raise ValueError(
            f"Hospital {hospital}: coverage mismatch. "
            f"Missing={len(missing_ids)}, "
            f"unexpected={len(unexpected_ids)}"
        )

    flagged = pd.to_numeric(
        predictions["flagged"],
        errors="coerce",
    )

    if flagged.isna().any() or not flagged.isin([0, 1]).all():
        raise ValueError(
            f"Hospital {hospital}: flagged must contain "
            "only 0 or 1."
        )

    predictions["flagged"] = flagged.astype("int64")
    predictions["expected_total_cents"] = (
        validate_integer_column(
            predictions,
            "expected_total_cents",
            hospital,
        )
    )
    predictions["billed_total_cents"] = (
        validate_integer_column(
            predictions,
            "billed_total_cents",
            hospital,
        )
    )

    confidence = pd.to_numeric(
        predictions["confidence"],
        errors="coerce",
    )

    if confidence.isna().any() or not confidence.between(0, 1).all():
        raise ValueError(
            f"Hospital {hospital}: confidence must be "
            "between 0 and 1."
        )

    predictions["confidence"] = confidence
    predictions["error_category"] = (
        predictions["error_category"]
        .fillna("")
        .astype(str)
        .str.strip()
    )

    missing_categories = predictions[
        predictions["flagged"].eq(1)
        & predictions["error_category"].eq("")
    ]

    if not missing_categories.empty:
        raise ValueError(
            f"Hospital {hospital}: flagged invoices must "
            "have an error category."
        )

    predictions.loc[
        predictions["flagged"].eq(0),
        "error_category",
    ] = ""

    return predictions


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]

    hospital_results = []

    for hospital in HOSPITALS:
        predictions = load_and_validate(
            project_root,
            hospital,
        )
        hospital_results.append(predictions)

        print(
            f"Hospital {hospital}: "
            f"{len(predictions)} rows, "
            f"{int(predictions['flagged'].sum())} flagged"
        )

    submission = pd.concat(
        hospital_results,
        ignore_index=True,
    )

    if submission["invoice_id"].duplicated().any():
        raise ValueError(
            "Duplicate invoice IDs found across hospitals."
        )

    submission = submission.sort_values(
        "invoice_id",
        kind="stable",
    ).reset_index(drop=True)

    output_path = project_root / "submission.csv"
    submission.to_csv(
        output_path,
        index=False,
        columns=SUBMISSION_COLUMNS,
    )

    print(f"Total rows: {len(submission)}")
    print(f"Total flagged: {int(submission['flagged'].sum())}")
    print("Validation passed")
    print(f"Saved to {output_path.name}")


if __name__ == "__main__":
    main()
