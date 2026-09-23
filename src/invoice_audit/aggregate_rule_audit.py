from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from .canonical_lines import (
    find_canonical_line_ids,
)
from .hospital_2_contract_rules import (
    load_hospital_2_rules,
)
from .hospital_2_engine import (
    add_invoice_context as add_h2_context,
)
from .hospital_2_engine import (
    calculate_line_expectations as calculate_h2,
)
from .hospital_2_engine import (
    find_excluded_lines as find_h2_exclusions,
)
from .hospital_3_contract_rules import (
    load_hospital_3_rules,
)
from .hospital_3_engine import (
    add_invoice_context as add_h3_context,
)
from .hospital_3_engine import (
    calculate_line_expectations as calculate_h3,
)
from .hospital_3_engine import (
    find_excluded_lines as find_h3_exclusions,
)
from .service_matcher import (
    build_match_report,
)


def prepare_data(
    project_root: Path,
    report: pd.DataFrame,
    add_context: Callable[
        [Path, pd.DataFrame],
        pd.DataFrame,
    ],
) -> pd.DataFrame:
    data = add_context(
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
    rules: Any,
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
    rules: Any,
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


def build_expected_discount_lookup(
    report: pd.DataFrame,
    rules: Any,
) -> dict[str, int]:
    utilisation = report.copy()

    utilisation["service_date_parsed"] = (
        pd.to_datetime(
            utilisation["service_date"],
            errors="coerce",
        )
    )

    utilisation["quantity"] = pd.to_numeric(
        utilisation["quantity"],
        errors="coerce",
    ).fillna(0)

    utilisation["reliable_match"] = (
        ~utilisation[
            "suspected_unknown_service"
        ].fillna(False)
        & utilisation[
            "matched_service"
        ].notna()
        & utilisation[
            "base_rate_cents"
        ].notna()
    )

    lookup: dict[str, int] = {}

    for (
        service,
        thresholds,
    ) in rules.volume_discounts.items():
        candidates = utilisation[
            utilisation["reliable_match"]
            & utilisation[
                "matched_service"
            ].eq(service)
            & utilisation[
                "service_date_parsed"
            ].notna()
        ].sort_values(
            [
                "service_date_parsed",
                "line_id",
            ],
            kind="stable",
        )

        prior_quantities = (
            candidates["quantity"].cumsum()
            - candidates["quantity"]
        )

        for index, prior_quantity in (
            prior_quantities.items()
        ):
            percentage = 0

            for (
                threshold,
                candidate_percentage,
            ) in thresholds:
                if prior_quantity > threshold:
                    percentage = (
                        candidate_percentage
                    )

            lookup[
                str(
                    candidates.at[
                        index,
                        "line_id",
                    ]
                )
            ] = percentage

    return lookup


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
    rules: Any,
) -> int:
    expected_lookup = (
        build_expected_discount_lookup(
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

    differences = expected.ne(
        current
    )

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

    return int(
        differences.sum()
    )


def get_hospital_components(
    hospital: int,
    project_root: Path,
) -> tuple[
    Any,
    Callable[
        [Path, pd.DataFrame],
        pd.DataFrame,
    ],
    Callable[
        [Path],
        tuple[
            pd.DataFrame,
            dict[str, set[str]],
        ],
    ],
    Callable[
        [pd.DataFrame, Any],
        set[str],
    ],
]:
    if hospital == 2:
        contract_path = (
            project_root
            / "contracts"
            / "hospital_2"
            / "master_services_agreement.md"
        )

        rules = load_hospital_2_rules(
            contract_path
        )

        return (
            rules,
            add_h2_context,
            calculate_h2,
            find_h2_exclusions,
        )

    if hospital == 3:
        contract_path = (
            project_root
            / "contracts"
            / "hospital_3"
            / "base_agreement.md"
        )

        rules = load_hospital_3_rules(
            contract_path
        )

        return (
            rules,
            add_h3_context,
            calculate_h3,
            find_h3_exclusions,
        )

    raise ValueError(
        "Hospital must be 2 or 3."
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--hospital",
        type=int,
        required=True,
        choices=[2, 3],
    )

    args = parser.parse_args()

    hospital = args.hospital

    project_root = (
        Path(__file__).resolve().parents[2]
    )

    (
        rules,
        add_context,
        calculate_expectations,
        find_exclusions,
    ) = get_hospital_components(
        hospital,
        project_root,
    )

    full_report = build_match_report(
        project_root,
        hospital=hospital,
    )

    full_data = prepare_data(
        project_root,
        full_report,
        add_context,
    )

    canonical_line_ids = (
        find_canonical_line_ids(
            project_root,
            hospital=hospital,
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
        find_exclusions(
            full_data,
            rules,
        )
        & canonical_ids
    )

    current_exclusions = (
        find_exclusions(
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
        calculate_expectations(
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
        "\nHospital:",
        hospital,
    )

    print(
        "Total aggregate-rule differences:",
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