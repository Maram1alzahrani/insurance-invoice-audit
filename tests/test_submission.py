from pathlib import Path

import pandas as pd
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUBMISSION_PATH = PROJECT_ROOT / "submission.csv"
EXPECTED_COLUMNS = [
    "invoice_id",
    "flagged",
    "error_category",
    "expected_total_cents",
    "billed_total_cents",
    "confidence",
]
HOSPITALS = (3, 4)


@pytest.fixture(scope="module")
def submission() -> pd.DataFrame:
    assert SUBMISSION_PATH.exists(), (
        "submission.csv is missing. Run "
        "python -m src.invoice_audit.build_submission first."
    )
    return pd.read_csv(SUBMISSION_PATH)


def expected_invoice_ids() -> set[str]:
    invoice_ids: set[str] = set()

    for hospital in HOSPITALS:
        path = (
            PROJECT_ROOT
            / "invoices"
            / f"hospital_{hospital}_invoices.csv"
        )
        values = pd.read_csv(path, usecols=["invoice_id"])[
            "invoice_id"
        ]
        invoice_ids.update(values.astype(str).str.strip().unique())

    return invoice_ids


def test_columns_are_exact(submission: pd.DataFrame) -> None:
    assert submission.columns.tolist() == EXPECTED_COLUMNS


def test_all_hospital_3_and_4_invoices_are_included_once(
    submission: pd.DataFrame,
) -> None:
    actual_ids = submission["invoice_id"].astype(str).str.strip()

    assert not actual_ids.duplicated().any()
    assert set(actual_ids) == expected_invoice_ids()


def test_flagged_is_binary(submission: pd.DataFrame) -> None:
    assert submission["flagged"].notna().all()
    assert set(submission["flagged"].unique()).issubset({0, 1})


@pytest.mark.parametrize(
    "column",
    ["expected_total_cents", "billed_total_cents"],
)
def test_money_columns_are_integer_cents(
    submission: pd.DataFrame,
    column: str,
) -> None:
    values = pd.to_numeric(submission[column], errors="coerce")

    assert values.notna().all()
    assert (values % 1 == 0).all()


def test_confidence_is_valid(submission: pd.DataFrame) -> None:
    confidence = pd.to_numeric(
        submission["confidence"],
        errors="coerce",
    )

    assert confidence.notna().all()
    assert confidence.between(0, 1).all()


def test_flagged_rows_have_error_categories(
    submission: pd.DataFrame,
) -> None:
    categories = (
        submission["error_category"].fillna("").astype(str).str.strip()
    )

    assert categories[submission["flagged"].eq(1)].ne("").all()
    assert categories[submission["flagged"].eq(0)].eq("").all()


def test_submission_is_sorted_by_invoice_id(
    submission: pd.DataFrame,
) -> None:
    invoice_ids = submission["invoice_id"].astype(str).tolist()
    assert invoice_ids == sorted(invoice_ids)
