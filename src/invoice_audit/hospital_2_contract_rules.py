from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .hospital_2_parser import (
    money_to_cents,
    split_service_clauses,
)


@dataclass(frozen=True)
class Hospital2Rules:
    threshold_premiums: dict[
        str,
        tuple[int, int],
    ]

    weekend_uplifts: dict[
        str,
        int,
    ]

    volume_discounts: dict[
        str,
        list[tuple[int, int]],
    ]

    bundles: list[
        tuple[str, str, int, int]
    ]

    exclusions: list[
        tuple[str, str, int]
    ]


def load_hospital_2_rules(
    contract_path: Path,
) -> Hospital2Rules:
    document = contract_path.read_text(
        encoding="utf-8"
    )

    clauses = split_service_clauses(
        document
    )

    service_pattern = re.compile(
        r"^\d+\.\d+\s+"
        r"In respect of (.*?), "
        r"the Provider shall invoice",
        flags=re.IGNORECASE,
    )

    threshold_pattern = re.compile(
        r"aggregate quantity .*?"
        r"exceeds .*?\((\d+)\).*?"
        r"increased by .*?\((\d+)%\)",
        flags=re.IGNORECASE,
    )

    weekend_pattern = re.compile(
        r"does not fall on a Business Day.*?"
        r"increased by .*?\((\d+)%\)",
        flags=re.IGNORECASE,
    )

    discount_pattern = re.compile(
        r"cumulative utilisation .*?"
        r"exceeds .*?\((\d+)\).*?"
        r"discount of .*?\((\d+)%\)",
        flags=re.IGNORECASE,
    )

    bundle_pattern = re.compile(
        r"Where this Service and (.*?) "
        r"are both delivered .*?"
        r"this Service at GBP "
        r"([\d,]+\.\d{2}).*?"
        r"and .*? at GBP "
        r"([\d,]+\.\d{2}).*?"
        r"in substitution",
        flags=re.IGNORECASE,
    )

    exclusion_pattern = re.compile(
        r"This Service is not billable where "
        r"(.*?) has been delivered "
        r"to the same Patient within .*?"
        r"\((\d+)\) days",
        flags=re.IGNORECASE,
    )

    threshold_premiums: dict[
        str,
        tuple[int, int],
    ] = {}

    weekend_uplifts: dict[
        str,
        int,
    ] = {}

    volume_discounts: dict[
        str,
        list[tuple[int, int]],
    ] = {}

    bundles_by_pair: dict[
        frozenset[str],
        tuple[str, str, int, int],
    ] = {}

    exclusions: list[
        tuple[str, str, int]
    ] = []

    known_services: set[str] = set()

    for clause in clauses:
        service_match = service_pattern.search(
            clause
        )

        if service_match is None:
            raise ValueError(
                "Cannot identify service in clause: "
                f"{clause[:160]}"
            )

        service = service_match.group(1).strip()

        if service in known_services:
            raise ValueError(
                f"Duplicate service clause: {service}"
            )

        known_services.add(service)

        threshold_match = (
            threshold_pattern.search(
                clause
            )
        )

        if threshold_match is not None:
            threshold_premiums[
                service
            ] = (
                int(
                    threshold_match.group(1)
                ),
                int(
                    threshold_match.group(2)
                ),
            )

        weekend_match = (
            weekend_pattern.search(
                clause
            )
        )

        if weekend_match is not None:
            weekend_uplifts[
                service
            ] = int(
                weekend_match.group(1)
            )

        discounts = [
            (
                int(threshold),
                int(percentage),
            )
            for (
                threshold,
                percentage,
            ) in discount_pattern.findall(
                clause
            )
        ]

        if discounts:
            volume_discounts[
                service
            ] = sorted(
                discounts,
                key=lambda item: item[0],
            )

        bundle_match = (
            bundle_pattern.search(
                clause
            )
        )

        if bundle_match is not None:
            (
                other_service,
                service_rate,
                other_rate,
            ) = bundle_match.groups()

            other_service = (
                other_service.strip()
            )

            candidate = (
                service,
                other_service,
                money_to_cents(
                    service_rate
                ),
                money_to_cents(
                    other_rate
                ),
            )

            pair = frozenset(
                (
                    service,
                    other_service,
                )
            )

            existing = bundles_by_pair.get(
                pair
            )

            if existing is not None:
                existing_rates = {
                    existing[0]: existing[2],
                    existing[1]: existing[3],
                }

                candidate_rates = {
                    candidate[0]: candidate[2],
                    candidate[1]: candidate[3],
                }

                if (
                    existing_rates
                    != candidate_rates
                ):
                    raise ValueError(
                        "Conflicting bundle clauses: "
                        f"{sorted(pair)}"
                    )

            bundles_by_pair[
                pair
            ] = candidate

        exclusion_match = (
            exclusion_pattern.search(
                clause
            )
        )

        if exclusion_match is not None:
            (
                trigger_service,
                window_days,
            ) = exclusion_match.groups()

            exclusions.append(
                (
                    service,
                    trigger_service.strip(),
                    int(window_days),
                )
            )

    for (
        service_a,
        service_b,
        _,
        _,
    ) in bundles_by_pair.values():
        if (
            service_a not in known_services
            or service_b not in known_services
        ):
            raise ValueError(
                "Bundle references an unknown "
                f"service: {service_a}, {service_b}"
            )

    for (
        excluded_service,
        trigger_service,
        _,
    ) in exclusions:
        if (
            excluded_service not in known_services
            or trigger_service not in known_services
        ):
            raise ValueError(
                "Exclusion references an unknown "
                f"service: {excluded_service}, "
                f"{trigger_service}"
            )

    return Hospital2Rules(
        threshold_premiums=(
            threshold_premiums
        ),
        weekend_uplifts=(
            weekend_uplifts
        ),
        volume_discounts=(
            volume_discounts
        ),
        bundles=list(
            bundles_by_pair.values()
        ),
        exclusions=exclusions,
    )


def main() -> None:
    project_root = (
        Path(__file__).resolve().parents[2]
    )

    contract_path = (
        project_root
        / "contracts"
        / "hospital_2"
        / "master_services_agreement.md"
    )

    rules = load_hospital_2_rules(
        contract_path
    )

    print(
        "Threshold premiums:",
        len(rules.threshold_premiums),
    )

    print(
        "Weekend uplifts:",
        len(rules.weekend_uplifts),
    )

    print(
        "Volume-discount services:",
        len(rules.volume_discounts),
    )

    print(
        "Bundle pairs:",
        len(rules.bundles),
    )

    print(
        "Exclusion windows:",
        len(rules.exclusions),
    )


if __name__ == "__main__":
    main()