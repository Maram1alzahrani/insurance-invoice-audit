from __future__ import annotations

import csv
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, ROUND_HALF_UP
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
class Hospital5Rate:
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


def multiply_rate(
    rate_cents: int,
    multiplier: Decimal,
) -> int:
    value = (
        Decimal(rate_cents)
        * multiplier
    )

    return int(
        value.quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        )
    )


def parse_daily_cap(
    value: str,
) -> int | None:
    if value.strip() in {
        "",
        "—",
        "-",
    }:
        return None

    match = re.search(
        r"\d+",
        value,
    )

    if match is None:
        raise ValueError(
            f"Cannot parse daily cap: {value}"
        )

    return int(
        match.group()
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


def extract_table(
    document: str,
    heading: str,
) -> list[list[str]]:
    lines = document.splitlines()

    try:
        start = lines.index(
            heading
        )
    except ValueError as error:
        raise ValueError(
            f"Section not found: {heading}"
        ) from error

    table_lines: list[str] = []
    started = False

    for line in lines[
        start + 1:
    ]:
        stripped = line.strip()

        if (
            started
            and stripped.startswith("#")
        ):
            break

        if stripped.startswith("|"):
            table_lines.append(
                stripped
            )
            started = True

    if not table_lines:
        raise ValueError(
            f"No table found under: {heading}"
        )

    rows: list[list[str]] = []

    for line in table_lines:
        cells = [
            cell.strip()
            for cell in line.strip("|").split("|")
        ]

        is_separator = all(
            re.fullmatch(
                r":?-+:?",
                cell,
            )
            for cell in cells
        )

        if not is_separator:
            rows.append(cells)

    return rows


def parse_multiplier_table(
    document: str,
    heading: str,
) -> dict[
    str,
    dict[str, Decimal],
]:
    rows = extract_table(
        document,
        heading,
    )

    header, *data_rows = rows
    dimensions = header[1:]

    result: dict[
        str,
        dict[str, Decimal],
    ] = {}

    for row in data_rows:
        service = row[0]
        values = row[1:]

        if len(values) != len(
            dimensions
        ):
            raise ValueError(
                "Multiplier column mismatch "
                f"for service: {service}"
            )

        result[service] = {
            dimension: Decimal(value)
            for dimension, value in zip(
                dimensions,
                values,
            )
        }

    return result


def parse_hospital_5_rates(
    contract_path: Path,
) -> list[Hospital5Rate]:
    document = contract_path.read_text(
        encoding="utf-8"
    )

    base_rows = extract_table(
        document,
        "## 4. Table 1 — Base Rates",
    )

    base_header, *base_data = (
        base_rows
    )

    expected_base_header = [
        "Service",
        "Unit basis",
        "Base rate",
        "Daily cap",
    ]

    if (
        base_header
        != expected_base_header
    ):
        raise ValueError(
            "Unexpected Hospital 5 "
            f"rate columns: {base_header}"
        )

    facility_multipliers = (
        parse_multiplier_table(
            document,
            "### Table 2 — Facility Multipliers",
        )
    )

    plan_multipliers = (
        parse_multiplier_table(
            document,
            "### Table 3 — Plan-Tier Multipliers",
        )
    )

    base_services = {
        row[0]
        for row in base_data
    }

    if (
        set(facility_multipliers)
        != base_services
    ):
        raise ValueError(
            "Facility multiplier services "
            "do not match base-rate services"
        )

    if (
        set(plan_multipliers)
        != base_services
    ):
        raise ValueError(
            "Plan multiplier services "
            "do not match base-rate services"
        )

    bundle_rows = extract_table(
        document,
        "## 7. Bundled Services",
    )

    bundle_header, *bundle_data = (
        bundle_rows
    )

    expected_bundle_header = [
        "Service A",
        "Substituted rate A",
        "Service B",
        "Substituted rate B",
    ]

    if (
        bundle_header
        != expected_bundle_header
    ):
        raise ValueError(
            "Unexpected bundle columns: "
            f"{bundle_header}"
        )

    bundle_rates: dict[
        str,
        int,
    ] = {}

    for (
        service_a,
        rate_a,
        service_b,
        rate_b,
    ) in bundle_data:
        bundle_rates[
            service_a
        ] = money_to_cents(
            rate_a
        )

        bundle_rates[
            service_b
        ] = money_to_cents(
            rate_b
        )

    rules: list[
        Hospital5Rate
    ] = []

    seen_services: set[str] = set()

    for (
        service,
        unit_basis,
        base_rate,
        daily_cap,
    ) in base_data:
        if service in seen_services:
            raise ValueError(
                f"Duplicate service: {service}"
            )

        seen_services.add(
            service
        )

        base_rate_cents = (
            money_to_cents(
                base_rate
            )
        )

        starting_rates = {
            base_rate_cents
        }

        if service in bundle_rates:
            starting_rates.add(
                bundle_rates[
                    service
                ]
            )

        identity_rates: set[int] = set()

        for starting_rate in (
            starting_rates
        ):
            for facility_multiplier in (
                facility_multipliers[
                    service
                ].values()
            ):
                after_facility = (
                    multiply_rate(
                        starting_rate,
                        facility_multiplier,
                    )
                )

                for plan_multiplier in (
                    plan_multipliers[
                        service
                    ].values()
                ):
                    identity_rates.add(
                        multiply_rate(
                            after_facility,
                            plan_multiplier,
                        )
                    )

        rules.append(
            Hospital5Rate(
                service=service,
                unit_basis=(
                    normalize_unit_basis(
                        unit_basis
                    )
                ),
                rate_cents=(
                    base_rate_cents
                ),
                daily_cap=(
                    parse_daily_cap(
                        daily_cap
                    )
                ),
                identity_rates_cents=(
                    "|".join(
                        str(rate)
                        for rate in sorted(
                            identity_rates
                        )
                    )
                ),
            )
        )

    return rules


def write_rules(
    rules: list[Hospital5Rate],
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
        / "hospital_5"
        / "network_reimbursement_agreement.md"
    )

    output_path = (
        project_root
        / "config"
        / "hospital_5_rates.csv"
    )

    rules = parse_hospital_5_rates(
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

    print(
        f"Extracted {len(rules)} services"
    )

    print(
        "Services with daily caps:",
        daily_cap_count,
    )

    print(
        "Saved to "
        f"{output_path.relative_to(project_root)}"
    )


if __name__ == "__main__":
    main()