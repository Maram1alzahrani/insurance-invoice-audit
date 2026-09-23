from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path


UNIT_BASIS_MAP = {
    "per procedure": "per_procedure",
    "per hour": "per_hour",
    "per visit": "per_visit",
    "per test": "per_test",
    "per day of service": "per_day",
    "per night of occupancy": "per_night",
    "per item supplied": "per_item",
    "per unit dispensed": "per_unit_dispensed",
    "per hour, per item": "per_hour_per_item",
}


@dataclass(frozen=True)
class Hospital2Rate:
    service: str
    unit_basis: str
    rate_cents: int
    daily_cap: int | None
    identity_rates_cents: str


def money_to_cents(
    value: str,
) -> int:
    cleaned = (
        value.replace("GBP", "")
        .replace(",", "")
        .strip()
    )

    return int(
        Decimal(cleaned)
        * Decimal(100)
    )


def normalize_unit_basis(
    value: str,
) -> str:
    normalized = UNIT_BASIS_MAP.get(
        value.strip()
    )

    if normalized is None:
        raise ValueError(
            f"Unknown unit basis: {value}"
        )

    return normalized


def split_service_clauses(
    document: str,
) -> list[str]:
    clauses: list[str] = []

    for line in document.splitlines():
        stripped = line.strip()

        if re.match(
            r"^\d+\.\d+\s+In respect of ",
            stripped,
        ):
            clauses.append(stripped)

    return clauses


def parse_daily_cap(
    clause: str,
) -> int | None:
    match = re.search(
        r"shall not bill more than "
        r".*?\((\d+)\).*?"
        r"of this Service",
        clause,
        flags=re.IGNORECASE,
    )

    if match is None:
        return None

    return int(
        match.group(1)
    )


def parse_hospital_2_rates(
    contract_path: Path,
) -> list[Hospital2Rate]:
    document = contract_path.read_text(
        encoding="utf-8"
    )

    clauses = split_service_clauses(
        document
    )

    if not clauses:
        raise ValueError(
            "No Hospital 2 service clauses found"
        )

    unit_pattern = "|".join(
        sorted(
            (
                re.escape(unit)
                for unit in UNIT_BASIS_MAP
            ),
            key=len,
            reverse=True,
        )
    )

    rate_pattern = re.compile(
        r"^\d+\.\d+\s+"
        r"In respect of (.*?), "
        r"the Provider shall invoice "
        r"the Payer at the rate of "
        r"GBP ([\d,]+\.\d{2}) "
        rf"({unit_pattern})\.",
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

    parsed_services: list[
        tuple[
            str,
            str,
            int,
            int | None,
            str,
        ]
    ] = []

    seen_services: set[str] = set()

    for clause in clauses:
        match = rate_pattern.search(
            clause
        )

        if match is None:
            raise ValueError(
                "Cannot parse service clause: "
                f"{clause[:160]}"
            )

        service = (
            match.group(1).strip()
        )

        rate_cents = money_to_cents(
            match.group(2)
        )

        unit_basis = normalize_unit_basis(
            match.group(3).lower()
        )

        if service in seen_services:
            raise ValueError(
                f"Duplicate service: {service}"
            )

        seen_services.add(
            service
        )

        parsed_services.append(
            (
                service,
                unit_basis,
                rate_cents,
                parse_daily_cap(
                    clause
                ),
                clause,
            )
        )

    identity_rates: dict[
        str,
        set[int],
    ] = {
        service: set()
        for service in seen_services
    }

    for (
        service,
        _,
        _,
        _,
        clause,
    ) in parsed_services:
        bundle_match = (
            bundle_pattern.search(
                clause
            )
        )

        if bundle_match is None:
            continue

        (
            other_service,
            service_rate,
            other_rate,
        ) = bundle_match.groups()

        other_service = (
            other_service.strip()
        )

        if other_service not in seen_services:
            raise ValueError(
                "Bundle references unknown "
                f"service: {other_service}"
            )

        identity_rates[
            service
        ].add(
            money_to_cents(
                service_rate
            )
        )

        identity_rates[
            other_service
        ].add(
            money_to_cents(
                other_rate
            )
        )

    rules: list[
        Hospital2Rate
    ] = []

    for (
        service,
        unit_basis,
        rate_cents,
        daily_cap,
        _,
    ) in parsed_services:
        additional_rates = "|".join(
            str(rate)
            for rate in sorted(
                identity_rates[
                    service
                ]
            )
        )

        rules.append(
            Hospital2Rate(
                service=service,
                unit_basis=unit_basis,
                rate_cents=rate_cents,
                daily_cap=daily_cap,
                identity_rates_cents=(
                    additional_rates
                ),
            )
        )

    return rules


def write_rules(
    rules: list[Hospital2Rate],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    fieldnames = [
        "service",
        "unit_basis",
        "rate_cents",
        "daily_cap",
        "identity_rates_cents",
    ]

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=fieldnames,
        )

        writer.writeheader()

        for rule in rules:
            writer.writerow(
                asdict(rule)
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

    output_path = (
        project_root
        / "config"
        / "hospital_2_rates.csv"
    )

    rules = parse_hospital_2_rates(
        contract_path
    )

    write_rules(
        rules,
        output_path,
    )

    daily_cap_count = sum(
        rule.daily_cap is not None
        for rule in rules
    )

    bundle_identity_count = sum(
        bool(
            rule.identity_rates_cents
        )
        for rule in rules
    )

    print(
        f"Extracted {len(rules)} services"
    )

    print(
        "Services with daily caps:",
        daily_cap_count,
    )

    print(
        "Services with bundle identity rates:",
        bundle_identity_count,
    )

    print(
        "Saved to "
        f"{output_path.relative_to(project_root)}"
    )


if __name__ == "__main__":
    main()