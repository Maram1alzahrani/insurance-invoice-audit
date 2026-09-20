from pathlib import Path

import pandas as pd

from .contract_rules import HOSPITAL_1_BUNDLES
from .discount_rules import (
    VOLUME_DISCOUNTS,
    discounted_rate,
)
from .premium_rules import (
    NON_BUSINESS_DAY_UPLIFTS,
    THRESHOLD_PREMIUMS,
    apply_percentage,
)


def build_allowed_rates(
    match_report: pd.DataFrame,
) -> dict[str, set[int]]:
    allowed_rates: dict[str, set[int]] = {}

    valid_rates = match_report.dropna(
        subset=[
            "matched_service",
            "base_rate_cents",
        ]
    )

    for row in valid_rates.itertuples(index=False):
        service = str(row.matched_service)
        base_rate = int(row.base_rate_cents)

        allowed_rates.setdefault(
            service,
            set(),
        ).add(base_rate)

    premium_rules = {
        **{
            service: percentage
            for service, (_, percentage)
            in THRESHOLD_PREMIUMS.items()
        },
        **NON_BUSINESS_DAY_UPLIFTS,
    }

    for service, percentage in premium_rules.items():
        if service not in allowed_rates:
            continue

        base_rate = min(allowed_rates[service])

        allowed_rates[service].add(
            apply_percentage(
                base_rate,
                percentage,
            )
        )

    for service, rule in VOLUME_DISCOUNTS.items():
        allowed_rates.setdefault(
            service,
            set(),
        ).add(int(rule["base_rate"]))

        for _, percentage in rule["thresholds"]:
            allowed_rates[service].add(
                discounted_rate(
                    int(rule["base_rate"]),
                    int(percentage),
                )
            )

    for (
        service_a,
        service_b,
        rate_a,
        rate_b,
    ) in HOSPITAL_1_BUNDLES:
        allowed_rates.setdefault(
            service_a,
            set(),
        ).add(int(rate_a))

        allowed_rates.setdefault(
            service_b,
            set(),
        ).add(int(rate_b))

    return allowed_rates


def find_price_and_unit_violations(
    project_root: Path,
    match_report: pd.DataFrame,
    hospital: int,
) -> tuple[set[str], dict[str, int]]:
    if hospital != 1:
        return set(), {}

    data = match_report.copy()
    allowed_rates = build_allowed_rates(data)

    expected_basis_by_service = (
        data.dropna(
            subset=[
                "matched_service",
                "expected_unit_basis",
            ]
        )
        .drop_duplicates("matched_service")
        .set_index("matched_service")[
            "expected_unit_basis"
        ]
        .to_dict()
    )

    def price_is_allowed(row: pd.Series) -> bool:
        service_rates = allowed_rates.get(
            str(row["matched_service"]),
            set(),
        )

        return int(row["unit_price_cents"]) in service_rates

    data["price_is_allowed"] = data.apply(
        price_is_allowed,
        axis=1,
    )

    reliable_match = (
        (data["match_score"] >= 90)
        & (data["match_margin"] >= 5)
        & ~data[
            "suspected_unknown_service"
        ].fillna(False)
    )

    wrong_unit_lines = data[
        reliable_match
        & ~data["unit_basis_matches"].fillna(False)
        & data["price_is_allowed"]
    ]

    wrong_unit_invoice_ids = set(
        wrong_unit_lines["invoice_id"].astype(str)
    )

    # If a billed price belongs to exactly one contracted service,
    # it provides a strong second signal for identifying that service.
    services_by_rate: dict[int, set[str]] = {}

    for service, rates in allowed_rates.items():
        for rate in rates:
            services_by_rate.setdefault(
                int(rate),
                set(),
            ).add(service)

    for row in data.itertuples(index=False):
        candidate_services = services_by_rate.get(
            int(row.unit_price_cents),
            set(),
        )

        if len(candidate_services) != 1:
            continue

        inferred_service = next(
            iter(candidate_services)
        )

        expected_basis = expected_basis_by_service.get(
            inferred_service
        )

        if expected_basis is None:
            continue

        if row.unit_basis_as_billed != expected_basis:
            wrong_unit_invoice_ids.add(
                str(row.invoice_id)
            )

    wrong_price_lines = data[
        reliable_match
        & data["unit_basis_matches"].fillna(False)
        & ~data["price_is_allowed"]
    ].copy()

    price_adjustments: dict[str, int] = {}

    for row in wrong_price_lines.itertuples(index=False):
        service = str(row.matched_service)
        billed_rate = int(row.unit_price_cents)

        possible_rates = allowed_rates.get(
            service,
            set(),
        )

        if not possible_rates:
            continue

        same_invoice_service = data[
            data["invoice_id"].eq(row.invoice_id)
            & data["matched_service"].eq(service)
            & data["price_is_allowed"]
        ]

        if not same_invoice_service.empty:
            expected_rate = int(
                same_invoice_service[
                    "unit_price_cents"
                ].mode().iloc[0]
            )
        else:
            expected_rate = min(
                possible_rates,
                key=lambda rate: abs(
                    billed_rate - rate
                ),
            )

        adjustment = (
            billed_rate - expected_rate
        ) * int(row.quantity)

        price_adjustments[row.invoice_id] = (
            price_adjustments.get(
                row.invoice_id,
                0,
            )
            + adjustment
        )

    return (
        wrong_unit_invoice_ids,
        price_adjustments,
    )