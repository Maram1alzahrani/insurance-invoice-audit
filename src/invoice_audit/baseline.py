from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pandas as pd

try:
    from .canonical_lines import find_canonical_line_ids
except ImportError:
    from canonical_lines import find_canonical_line_ids


EXPECTED_CONTRACTS = {
    1: "INS-H1-2024-0417",
    2: "INS-H2-2024-1183",
    3: "INS-H3-2024-0562",
    4: "INS-H4-2024-2049",
    5: "INS-H5-2024-0731",
}

TERM_START = pd.Timestamp("2024-01-01")
TERM_END = pd.Timestamp("2025-12-31")


def audit_basic(data_dir: Path, hospital: int) -> pd.DataFrame:
    invoice_path = (
        data_dir / "invoices" / f"hospital_{hospital}_invoices.csv"
    )
    line_path = (
        data_dir / "invoices" / f"hospital_{hospital}_line_items.csv"
    )

    invoices_all = pd.read_csv(invoice_path)
    lines_all = pd.read_csv(line_path)

    # For duplicated invoice IDs, keep only the line-item group that belongs
    # to the final invoice row. The complete raw data remains available for
    # duplicate detection.
    canonical_line_ids = find_canonical_line_ids(
        data_dir,
        hospital,
    )

    lines = lines_all.loc[
        lines_all["line_id"].astype(str).isin(canonical_line_ids)
    ].copy()

    # The final invoice row is the canonical claim.
    invoices = invoices_all.drop_duplicates(
        "invoice_id",
        keep="last",
    ).copy()

    invoices = invoices.set_index(
        "invoice_id",
        drop=False,
    )

    reasons: dict[str, set[str]] = defaultdict(set)

    # Duplicate detection must use all invoice rows.
    duplicate_ids = invoices_all.loc[
        invoices_all.duplicated("invoice_id", keep=False),
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in duplicate_ids:
        reasons[invoice_id].add("duplicate_invoice_id")

    # Check every invoice row because an incorrect duplicated row is still
    # a contract-number violation.
    bad_contract_ids = invoices_all.loc[
        invoices_all["contract_number"]
        != EXPECTED_CONTRACTS[hospital],
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in bad_contract_ids:
        reasons[invoice_id].add(
            "contract_number_mismatch"
        )

    invoice_dates = pd.to_datetime(
        invoices["invoice_date"],
        errors="coerce",
    )

    service_dates = pd.to_datetime(
        lines["service_date"],
        errors="coerce",
    )

    malformed_ids = lines.loc[
        service_dates.isna(),
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in malformed_ids:
        reasons[invoice_id].add(
            "malformed_service_date"
        )

    valid_lines = lines.loc[
        service_dates.notna()
    ].copy()

    valid_lines["service_date_parsed"] = (
        service_dates.loc[service_dates.notna()]
    )

    outside_ids = valid_lines.loc[
        ~valid_lines["service_date_parsed"].between(
            TERM_START,
            TERM_END,
        ),
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in outside_ids:
        reasons[invoice_id].add(
            "service_date_out_of_window"
        )

    dated_lines = valid_lines.merge(
        invoice_dates.rename("invoice_date_parsed"),
        left_on="invoice_id",
        right_index=True,
        how="left",
    )

    after_invoice_ids = dated_lines.loc[
        dated_lines["service_date_parsed"]
        > dated_lines["invoice_date_parsed"],
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in after_invoice_ids:
        reasons[invoice_id].add(
            "service_date_after_invoice_date"
        )

    calculated_line_total = (
        lines["quantity"] * lines["unit_price_cents"]
    )

    bad_line_ids = lines.loc[
        calculated_line_total
        != lines["line_total_cents"],
        "invoice_id",
    ].astype(str).unique()

    for invoice_id in bad_line_ids:
        reasons[invoice_id].add(
            "line_total_arithmetic"
        )

    billed_line_sums = lines.groupby(
        "invoice_id"
    )["line_total_cents"].sum()

    corrected_line_sums = calculated_line_total.groupby(
        lines["invoice_id"]
    ).sum()

    comparable = invoices.join(
        billed_line_sums.rename("line_sum")
    )

    bad_invoice_total_ids = comparable.index[
        comparable["line_sum"].notna()
        & (
            comparable["invoice_total_cents"]
            != comparable["line_sum"]
        )
    ]

    for invoice_id in bad_invoice_total_ids:
        reasons[str(invoice_id)].add(
            "invoice_total_mismatch"
        )

    rows = []

    for invoice_id, invoice in invoices.iterrows():
        invoice_id = str(invoice_id)

        categories = sorted(
            reasons.get(invoice_id, set())
        )

        needs_recalculation = bool(
            {
                "line_total_arithmetic",
                "invoice_total_mismatch",
            }.intersection(categories)
        )

        if (
            needs_recalculation
            and invoice_id in corrected_line_sums.index
        ):
            expected_total = int(
                corrected_line_sums.loc[invoice_id]
            )
        else:
            expected_total = int(
                invoice["invoice_total_cents"]
            )

        rows.append(
            {
                "invoice_id": invoice_id,
                "flagged": int(bool(categories)),
                "error_category": "|".join(categories),
                "expected_total_cents": expected_total,
                "billed_total_cents": int(
                    invoice["invoice_total_cents"]
                ),
                "confidence": (
                    0.99 if categories else 0.70
                ),
            }
        )

    return pd.DataFrame(rows)


def contains_category(
    series: pd.Series,
    category: str,
) -> pd.Series:
    return series.fillna("").str.split("|").apply(
        lambda values: category in values
    )


def evaluate_hospital_1(
    predictions: pd.DataFrame,
    labels_path: Path,
) -> None:
    labels = pd.read_csv(labels_path)

    merged = labels.merge(
        predictions,
        on="invoice_id",
        suffixes=("_label", "_pred"),
        validate="one_to_one",
    )

    actual = merged["is_erroneous"] == 1
    predicted = merged["flagged"] == 1

    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())

    precision = (
        tp / (tp + fp)
        if tp + fp
        else 0.0
    )

    recall = (
        tp / (tp + fn)
        if tp + fn
        else 0.0
    )

    f1 = (
        2 * precision * recall
        / (precision + recall)
        if precision + recall
        else 0.0
    )

    print(f"TP={tp} FP={fp} FN={fn} TN={tn}")

    print(
        f"precision={precision:.3f} "
        f"recall={recall:.3f} "
        f"f1={f1:.3f}"
    )

    actual_categories = (
        merged["error_categories"]
        .fillna("")
        .str.split("|")
        .explode()
    )

    predicted_categories = (
        merged["error_category"]
        .fillna("")
        .str.split("|")
        .explode()
    )

    categories = sorted(
        (
            set(actual_categories)
            | set(predicted_categories)
        )
        - {""}
    )

    print("\nPer-category detection:")

    for category in categories:
        actual_ids = set(
            merged.loc[
                contains_category(
                    merged["error_categories"],
                    category,
                ),
                "invoice_id",
            ]
        )

        predicted_ids = set(
            merged.loc[
                contains_category(
                    merged["error_category"],
                    category,
                ),
                "invoice_id",
            ]
        )

        hits = len(actual_ids & predicted_ids)
        false_positives = len(
            predicted_ids - actual_ids
        )

        print(
            f"{category}: "
            f"{hits}/{len(actual_ids)} detected; "
            f"{false_positives} false positives"
        )


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]

    baseline_predictions = audit_basic(
        project_root,
        hospital=1,
    )

    output_path = (
        project_root
        / "reports"
        / "hospital_1_baseline_predictions.csv"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    baseline_predictions.to_csv(
        output_path,
        index=False,
    )

    evaluate_hospital_1(
        baseline_predictions,
        project_root
        / "labels"
        / "hospital_1_labels.csv",
    )