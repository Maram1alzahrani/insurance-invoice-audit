from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

import pandas as pd

from .audit_engine import (
    add_error_category,
    apply_adjustments,
)
from .baseline import audit_basic
from .canonical_lines import (
    find_canonical_line_ids,
)
from .duplicate_rules import (
    find_cross_invoice_duplicates,
)
from .hospital_3_contract_rules import (
    Hospital3Rules,
    load_hospital_3_rules,
)
from .service_matcher import build_match_report


HOSPITAL = 3


def apply_uplift(
    rate_cents: int,
    percentage: int,
) -> int:
    value = (
        Decimal(int(rate_cents))
        * Decimal(100 + int(percentage))
        / Decimal(100)
    )

    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def apply_discount(
    rate_cents: int,
    percentage: int,
) -> int:
    value = (
        Decimal(int(rate_cents))
        * Decimal(100 - int(percentage))
        / Decimal(100)
    )

    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def record_category(
    categories: dict[str, set[str]],
    invoice_ids: pd.Series,
    category: str,
) -> None:
    for invoice_id in invoice_ids.astype(str):
        categories[invoice_id].add(category)


def add_invoice_context(
    project_root: Path,
    report: pd.DataFrame,
) -> pd.DataFrame:
    invoices = pd.read_csv(
        project_root
        / "invoices"
        / "hospital_3_invoices.csv"
    ).drop_duplicates(
        "invoice_id",
        keep="last",
    )

    data = report.merge(
        invoices[
            [
                "invoice_id",
                "patient_id",
                "invoice_date",
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

    data["invoice_date_parsed"] = pd.to_datetime(
        data["invoice_date"],
        errors="coerce",
    )

    data["quantity"] = pd.to_numeric(
        data["quantity"],
        errors="coerce",
    ).fillna(0)

    data["unit_price_cents"] = pd.to_numeric(
        data["unit_price_cents"],
        errors="coerce",
    ).fillna(0)

    data["line_total_cents"] = pd.to_numeric(
        data["line_total_cents"],
        errors="coerce",
    ).fillna(0)

    data["base_rate_cents"] = pd.to_numeric(
        data["base_rate_cents"],
        errors="coerce",
    )

    data["daily_cap"] = pd.to_numeric(
        data["daily_cap"],
        errors="coerce",
    )

    return data


def apply_bundle_rates(
    data: pd.DataFrame,
    rules: Hospital3Rules,
) -> None:
    reliable = data[
        data["reliable_match"]
        & data["service_date_parsed"].notna()
    ]

    grouped = reliable.groupby(
        [
            "patient_id",
            "service_date_parsed",
        ],
        sort=False,
    )

    for _, group in grouped:
        present_services = set(
            group["matched_service"]
        )

        for (
            service_a,
            service_b,
            rate_a,
            rate_b,
        ) in rules.bundles:
            if not {
                service_a,
                service_b,
            }.issubset(present_services):
                continue

            rates = {
                service_a: rate_a,
                service_b: rate_b,
            }

            for service, rate in rates.items():
                indexes = group.index[
                    group["matched_service"].eq(
                        service
                    )
                ]

                data.loc[
                    indexes,
                    "expected_rate_cents",
                ] = int(rate)

                data.loc[
                    indexes,
                    "bundle_applies",
                ] = True


def apply_threshold_premiums(
    data: pd.DataFrame,
    rules: Hospital3Rules,
) -> None:
    reliable = data[
        data["reliable_match"]
        & data["service_date_parsed"].notna()
    ].copy()

    reliable["daily_quantity"] = (
        reliable.groupby(
            [
                "patient_id",
                "service_date_parsed",
                "matched_service",
            ],
            dropna=False,
        )["quantity"].transform("sum")
    )

    daily_quantity_by_line = (
        reliable.set_index("line_id")[
            "daily_quantity"
        ]
    )

    data["daily_quantity"] = (
        data["line_id"].map(
            daily_quantity_by_line
        )
    )

    for (
        service,
        (
            threshold,
            percentage,
        ),
    ) in rules.threshold_premiums.items():
        mask = (
            data["reliable_match"]
            & data["matched_service"].eq(
                service
            )
            & (
                data["daily_quantity"]
                > threshold
            )
        )

        indexes = data.index[mask]

        for index in indexes:
            current_rate = int(
                data.at[
                    index,
                    "expected_rate_cents",
                ]
            )

            data.at[
                index,
                "expected_rate_cents",
            ] = apply_uplift(
                current_rate,
                percentage,
            )

        data.loc[
            indexes,
            "threshold_premium_applies",
        ] = True


def apply_weekend_uplifts(
    data: pd.DataFrame,
    rules: Hospital3Rules,
) -> None:
    for (
        service,
        percentage,
    ) in rules.weekend_uplifts.items():
        mask = (
            data["reliable_match"]
            & data["matched_service"].eq(
                service
            )
            & data[
                "service_date_parsed"
            ].notna()
            & (
                data[
                    "service_date_parsed"
                ].dt.weekday
                >= 5
            )
        )

        indexes = data.index[mask]

        for index in indexes:
            current_rate = int(
                data.at[
                    index,
                    "expected_rate_cents",
                ]
            )

            data.at[
                index,
                "expected_rate_cents",
            ] = apply_uplift(
                current_rate,
                percentage,
            )

        data.loc[
            indexes,
            "weekend_uplift_applies",
        ] = True


def apply_volume_discounts(
    data: pd.DataFrame,
    rules: Hospital3Rules,
) -> None:
    for (
        service,
        thresholds,
    ) in rules.volume_discounts.items():
        candidates = data[
            data["reliable_match"]
            & data["matched_service"].eq(
                service
            )
            & data[
                "service_date_parsed"
            ].notna()
        ].sort_values(
            [
                "service_date_parsed",
                "line_id",
            ],
            kind="stable",
        )

        if candidates.empty:
            continue

        prior_quantities = (
            candidates["quantity"].cumsum()
            - candidates["quantity"]
        )

        for index, prior_quantity in (
            prior_quantities.items()
        ):
            discount_percentage = 0

            for (
                threshold,
                percentage,
            ) in thresholds:
                if prior_quantity > threshold:
                    discount_percentage = (
                        percentage
                    )

            if discount_percentage == 0:
                continue

            current_rate = int(
                data.at[
                    index,
                    "expected_rate_cents",
                ]
            )

            data.at[
                index,
                "expected_rate_cents",
            ] = apply_discount(
                current_rate,
                discount_percentage,
            )

            data.at[
                index,
                "discount_percentage",
            ] = discount_percentage


def apply_daily_caps(
    data: pd.DataFrame,
    categories: dict[str, set[str]],
) -> None:
    eligible = data[
        data["reliable_match"]
        & data["daily_cap"].notna()
        & data["service_date_parsed"].notna()
    ].copy()

    grouped = eligible.groupby(
        [
            "patient_id",
            "service_date_parsed",
            "matched_service",
        ],
        dropna=False,
        sort=False,
    )

    for _, group in grouped:
        group = group.sort_values(
            "line_id",
            kind="stable",
        )

        daily_cap = int(
            group["daily_cap"].iloc[0]
        )

        remaining_capacity = daily_cap

        for index, row in group.iterrows():
            quantity = max(
                int(row["quantity"]),
                0,
            )

            billable_quantity = min(
                quantity,
                max(
                    remaining_capacity,
                    0,
                ),
            )

            data.at[
                index,
                "billable_quantity",
            ] = billable_quantity

            remaining_capacity -= (
                billable_quantity
            )

            if billable_quantity < quantity:
                categories[
                    str(row["invoice_id"])
                ].add(
                    "daily_cap_exceeded"
                )


def find_excluded_lines(
    data: pd.DataFrame,
    rules: Hospital3Rules,
) -> set[str]:
    reliable = data[
        data["reliable_match"]
        & data["service_date_parsed"].notna()
    ].copy()

    excluded_line_ids: set[str] = set()

    for (
        excluded_service,
        trigger_service,
        window_days,
    ) in rules.exclusions:
        excluded_lines = reliable[
            reliable["matched_service"].eq(
                excluded_service
            )
        ]

        trigger_lines = reliable[
            reliable["matched_service"].eq(
                trigger_service
            )
        ]

        if (
            excluded_lines.empty
            or trigger_lines.empty
        ):
            continue

        pairs = excluded_lines.merge(
            trigger_lines,
            on="patient_id",
            suffixes=(
                "_excluded",
                "_trigger",
            ),
        )

        date_difference = (
            pairs[
                "service_date_parsed_excluded"
            ]
            - pairs[
                "service_date_parsed_trigger"
            ]
        ).abs().dt.days

        violations = pairs[
            date_difference <= window_days
        ]

        excluded_line_ids.update(
            violations[
                "line_id_excluded"
            ].astype(str)
        )

    return excluded_line_ids


def calculate_line_expectations(
    project_root: Path,
) -> tuple[
    pd.DataFrame,
    dict[str, set[str]],
]:
    full_report = build_match_report(
        project_root,
        hospital=HOSPITAL,
    )

    canonical_line_ids = (
        find_canonical_line_ids(
            project_root,
            hospital=HOSPITAL,
        )
    )

    report = full_report[
        full_report["line_id"]
        .astype(str)
        .isin(canonical_line_ids)
    ].copy()

    data = add_invoice_context(
        project_root,
        report,
    )

    rules = load_hospital_3_rules(
        project_root
        / "contracts"
        / "hospital_3"
        / "base_agreement.md"
    )

    categories: dict[
        str,
        set[str],
    ] = defaultdict(set)

    data["reliable_match"] = (
        ~data[
            "suspected_unknown_service"
        ].fillna(False)
        & data["matched_service"].notna()
        & data["base_rate_cents"].notna()
    )

    data["expected_rate_cents"] = (
        data["base_rate_cents"]
        .fillna(data["unit_price_cents"])
        .astype(int)
    )

    data["billable_quantity"] = (
        data["quantity"]
        .clip(lower=0)
        .astype(int)
    )

    data["bundle_applies"] = False
    data["threshold_premium_applies"] = False
    data["weekend_uplift_applies"] = False
    data["discount_percentage"] = 0

    unknown_mask = data[
        "suspected_unknown_service"
    ].fillna(False)

    record_category(
        categories,
        data.loc[
            unknown_mask,
            "invoice_id",
        ],
        "unknown_service",
    )

    unavailable_mask = data[
        "service_not_yet_contracted"
    ].fillna(False)

    record_category(
        categories,
        data.loc[
            unavailable_mask,
            "invoice_id",
        ],
        "service_not_contracted_on_date",
    )

    apply_bundle_rates(
        data,
        rules,
    )

    apply_threshold_premiums(
        data,
        rules,
    )

    apply_weekend_uplifts(
        data,
        rules,
    )

    apply_volume_discounts(
        data,
        rules,
    )

    apply_daily_caps(
        data,
        categories,
    )

    excluded_line_ids = find_excluded_lines(
        data,
        rules,
    )

    exclusion_mask = (
        data["line_id"]
        .astype(str)
        .isin(excluded_line_ids)
    )

    record_category(
        categories,
        data.loc[
            exclusion_mask,
            "invoice_id",
        ],
        "exclusion_window_violation",
    )

    reliable_active = (
        data["reliable_match"]
        & ~unavailable_mask
        & ~exclusion_mask
    )

    wrong_unit_mask = (
        reliable_active
        & ~data[
            "unit_basis_matches"
        ].fillna(False)
    )

    record_category(
        categories,
        data.loc[
            wrong_unit_mask,
            "invoice_id",
        ],
        "wrong_unit_basis",
    )

    billed_rates = (
        data["unit_price_cents"]
        .fillna(0)
        .astype(int)
    )

    expected_rates = (
        data["expected_rate_cents"]
        .fillna(0)
        .astype(int)
    )

    rate_mismatch_mask = (
        reliable_active
        & (billed_rates != expected_rates)
    )

    record_category(
        categories,
        data.loc[
            rate_mismatch_mask,
            "invoice_id",
        ],
        "contract_rate_mismatch",
    )

    bundle_mismatch = (
        rate_mismatch_mask
        & data["bundle_applies"]
    )

    record_category(
        categories,
        data.loc[
            bundle_mismatch,
            "invoice_id",
        ],
        "bundle_rate_mismatch",
    )

    premium_mismatch = (
        rate_mismatch_mask
        & (
            data[
                "threshold_premium_applies"
            ]
            | data[
                "weekend_uplift_applies"
            ]
        )
    )

    record_category(
        categories,
        data.loc[
            premium_mismatch,
            "invoice_id",
        ],
        "premium_or_uplift_mismatch",
    )

    discount_mismatch = (
        rate_mismatch_mask
        & (
            data[
                "discount_percentage"
            ]
            > 0
        )
    )

    record_category(
        categories,
        data.loc[
            discount_mismatch,
            "invoice_id",
        ],
        "volume_discount_mismatch",
    )

    unavailable_or_excluded = (
        unavailable_mask
        | exclusion_mask
    )

    data["expected_line_total_cents"] = (
        data["expected_rate_cents"]
        .astype(int)
        * data["billable_quantity"]
        .astype(int)
    )

    data.loc[
        unavailable_or_excluded,
        "expected_line_total_cents",
    ] = 0

    # An unknown service cannot be repriced safely.
    # Preserve its arithmetic total and lower confidence later.
    data.loc[
        unknown_mask,
        "expected_line_total_cents",
    ] = (
        data.loc[
            unknown_mask,
            "quantity",
        ].astype(int)
        * data.loc[
            unknown_mask,
            "unit_price_cents",
        ].astype(int)
    )

    return data, categories


def build_hospital_3_predictions(
    project_root: Path,
) -> pd.DataFrame:
    predictions = audit_basic(
        project_root,
        hospital=HOSPITAL,
    )

    line_results, categories = (
        calculate_line_expectations(
            project_root
        )
    )

    expected_totals = (
        line_results.groupby("invoice_id")[
            "expected_line_total_cents"
        ]
        .sum()
        .astype(int)
    )

    mapped_totals = predictions[
        "invoice_id"
    ].map(expected_totals)

    has_total = mapped_totals.notna()

    predictions.loc[
        has_total,
        "expected_total_cents",
    ] = mapped_totals.loc[
        has_total
    ].astype(int)

    high_confidence_categories = {
        "service_not_contracted_on_date",
        "daily_cap_exceeded",
        "exclusion_window_violation",
        "wrong_unit_basis",
        "contract_rate_mismatch",
        "bundle_rate_mismatch",
        "premium_or_uplift_mismatch",
        "volume_discount_mismatch",
    }

    for invoice_id, invoice_categories in (
        categories.items()
    ):
        for category in sorted(
            invoice_categories
        ):
            confidence = (
                0.75
                if category
                == "unknown_service"
                else 0.95
                if category
                in high_confidence_categories
                else 0.85
            )

            add_error_category(
                predictions,
                [invoice_id],
                category,
                confidence,
            )

    duplicate_adjustments = (
        find_cross_invoice_duplicates(
            project_root,
            hospital=HOSPITAL,
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

    predictions[
        "expected_total_cents"
    ] = predictions[
        "expected_total_cents"
    ].astype(int)

    predictions[
        "billed_total_cents"
    ] = predictions[
        "billed_total_cents"
    ].astype(int)

    return predictions


def print_summary(
    predictions: pd.DataFrame,
) -> None:
    print(
        "Invoices:",
        len(predictions),
    )

    print(
        "Flagged:",
        int(predictions["flagged"].sum()),
    )

    print(
        "Flag rate:",
        f"{predictions['flagged'].mean():.3%}",
    )

    categories = (
        predictions.loc[
            predictions["flagged"].eq(1),
            "error_category",
        ]
        .fillna("")
        .str.split("|")
        .explode()
    )

    category_counts = (
        categories[
            categories.ne("")
        ]
        .value_counts()
        .sort_index()
    )

    print("\nCategory counts:")

    for category, count in (
        category_counts.items()
    ):
        print(
            f"{category}: {count}"
        )


def main() -> None:
    project_root = (
        Path(__file__).resolve().parents[2]
    )

    predictions = (
        build_hospital_3_predictions(
            project_root
        )
    )

    output_path = (
        project_root
        / "reports"
        / "hospital_3_predictions.csv"
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    predictions.to_csv(
        output_path,
        index=False,
    )

    print_summary(
        predictions
    )

    print(
        "\nSaved to "
        f"{output_path.relative_to(project_root)}"
    )


if __name__ == "__main__":
    main()
