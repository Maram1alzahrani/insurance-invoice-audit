from __future__ import annotations

from pathlib import Path

import pandas as pd

from .canonical_lines import (
    find_canonical_line_ids,
)
from .hospital_5_contract_rules import (
    Hospital5Rules,
    load_hospital_5_rules,
)
from .hospital_5_engine import (
    add_invoice_context,
    build_volume_discount_lookup,
    calculate_line_expectations,
    find_excluded_lines,
)
from .service_matcher import (
    build_match_report,
)


HOSPITAL = 5


def prepare_data(
    project_root: Path,
    report: pd.DataFrame,
) -> pd.DataFrame:
    data = add_invoice_context(
        project_root,
        report,
    )

    data["reliable_match"] = (
        ~data[
            "suspected_unknown_service"
        ].fillna(False)
        & data[
            "matched_service"
        ].notna()
        & data[
            "base_rate_cents"
        ].notna()
    )

    return data


def threshold_line_ids(
    data: pd.DataFrame,
    rules: Hospital5Rules,
) -> set[str]:
    reliable = data[
        data["reliable_match"]
        & data[
            "service_date_parsed"
        ].notna()
    ].copy()

    reliable["aggregate_quantity"] = (
        reliable.groupby(
            [
                "patient_id",
                "service_date_parsed",
                "matched_service",
            ],
            dropna=False,
        )["quantity"].transform("sum")
    )

    affected: set[str] = set()

    for (
        service,
        (
            threshold,
            _,
        ),
    ) in rules.threshold_premiums.items():
        mask = (
            reliable[
                "matched_service"
            ].eq(service)
            & (
                reliable[
                    "aggregate_quantity"
                ]
                > threshold
            )
        )

        affected.update(
            reliable.loc[
                mask,
                "line_id",
            ].astype(str)
        )

    return affected


def bundle_line_ids(
    data: pd.DataFrame,
    rules: Hospital5Rules,
) -> set[str]:
    reliable = data[
        data["reliable_match"]
        & data[
            "service_date_parsed"
        ].notna()
    ]

    affected: set[str] = set()

    grouped = reliable.groupby(
        [
            "patient_id",
            "service_date_parsed",
        ],
        dropna=False,
        sort=False,
    )

    for _, group in grouped:
        present_services = set(
            group["matched_service"]
        )

        for (
            service_a,
            service_b,
            _,
            _,
        ) in rules.bundles:
            if not {
                service_a,
                service_b,
            }.issubset(
                present_services
            ):
                continue

            mask = group[
                "matched_service"
            ].isin(
                [
                    service_a,
                    service_b,
                ]
            )

            affected.update(
                group.loc[
                    mask,
                    "line_id",
                ].astype(str)
            )

    return affected


def capped_line_ids(
    data: pd.DataFrame,
) -> set[str]:
    eligible = data[
        data["reliable_match"]
        & data["daily_cap"].notna()
        & data[
            "service_date_parsed"
        ].notna()
    ].copy()

    affected: set[str] = set()

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
            group[
                "daily_cap"
            ].iloc[0]
        )

        remaining_capacity = daily_cap

        for _, row in group.iterrows():
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

            if billable_quantity < quantity:
                affected.add(
                    str(row["line_id"])
                )

            remaining_capacity -= (
                billable_quantity
            )

    return affected


def print_set_comparison(
    name: str,
    expected: set[str],
    current: set[str],
) -> int:
    missing = expected - current
    extra = current - expected

    print(f"\n{name}")
    print(
        "Expected affected lines:",
        len(expected),
    )
    print(
        "Current affected lines:",
        len(current),
    )
    print(
        "Missing from current:",
        len(missing),
    )
    print(
        "Unexpected in current:",
        len(extra),
    )

    if missing:
        print(
            "Missing examples:",
            sorted(missing)[:10],
        )

    if extra:
        print(
            "Unexpected examples:",
            sorted(extra)[:10],
        )

    return len(missing) + len(extra)


def audit_volume_discounts(
    full_report: pd.DataFrame,
    current_results: pd.DataFrame,
    rules: Hospital5Rules,
) -> int:
    expected_lookup = (
        build_volume_discount_lookup(
            full_report,
            rules,
        )
    )

    expected = (
        current_results["line_id"]
        .astype(str)
        .map(expected_lookup)
        .fillna(0)
        .astype(int)
    )

    current = (
        current_results[
            "discount_percentage"
        ]
        .fillna(0)
        .astype(int)
    )

    differences = expected.ne(current)

    print(
        "\nCumulative volume discounts"
    )

    print(
        "Expected discounted lines:",
        int(expected.gt(0).sum()),
    )

    print(
        "Current discounted lines:",
        int(current.gt(0).sum()),
    )

    print(
        "Differences:",
        int(differences.sum()),
    )

    if differences.any():
        review = current_results.loc[
            differences,
            [
                "line_id",
                "invoice_id",
                "matched_service",
            ],
        ].copy()

        review[
            "expected_discount"
        ] = expected.loc[
            differences
        ].to_numpy()

        review[
            "current_discount"
        ] = current.loc[
            differences
        ].to_numpy()

        print(
            review.head(10).to_string(
                index=False
            )
        )

    return int(differences.sum())


def main() -> None:
    project_root = (
        Path(__file__).resolve().parents[2]
    )

    contract_path = (
        project_root
        / "contracts"
        / "hospital_5"
        / "network_reimbursement_agreement.md"
    )

    rules = load_hospital_5_rules(
        contract_path
    )

    full_report = build_match_report(
        project_root,
        hospital=HOSPITAL,
    )

    full_data = prepare_data(
        project_root,
        full_report,
    )

    canonical_line_ids = (
        find_canonical_line_ids(
            project_root,
            hospital=HOSPITAL,
        )
    )

    canonical_data = full_data[
        full_data["line_id"]
        .astype(str)
        .isin(canonical_line_ids)
    ].copy()

    canonical_ids = set(
        canonical_data[
            "line_id"
        ].astype(str)
    )

    total_differences = 0

    expected_thresholds = (
        threshold_line_ids(
            full_data,
            rules,
        )
        & canonical_ids
    )

    current_thresholds = (
        threshold_line_ids(
            canonical_data,
            rules,
        )
    )

    total_differences += (
        print_set_comparison(
            "Threshold premiums",
            expected_thresholds,
            current_thresholds,
        )
    )

    expected_bundles = (
        bundle_line_ids(
            full_data,
            rules,
        )
        & canonical_ids
    )

    current_bundles = (
        bundle_line_ids(
            canonical_data,
            rules,
        )
    )

    total_differences += (
        print_set_comparison(
            "Bundled services",
            expected_bundles,
            current_bundles,
        )
    )

    expected_caps = (
        capped_line_ids(
            full_data,
        )
        & canonical_ids
    )

    current_caps = (
        capped_line_ids(
            canonical_data,
        )
    )

    total_differences += (
        print_set_comparison(
            "Daily quantity caps",
            expected_caps,
            current_caps,
        )
    )

    expected_exclusions = (
        find_excluded_lines(
            full_data,
            rules,
        )
        & canonical_ids
    )

    current_exclusions = (
        find_excluded_lines(
            canonical_data,
            rules,
        )
    )

    total_differences += (
        print_set_comparison(
            "Exclusion windows",
            expected_exclusions,
            current_exclusions,
        )
    )

    current_results, _ = (
        calculate_line_expectations(
            project_root
        )
    )

    total_differences += (
        audit_volume_discounts(
            full_report,
            current_results,
            rules,
        )
    )

    print(
        "\nTotal aggregate-rule differences:",
        total_differences,
    )

    if total_differences == 0:
        print(
            "Aggregate-rule validation passed"
        )
    else:
        print(
            "Review required before submission"
        )


if __name__ == "__main__":
    main()