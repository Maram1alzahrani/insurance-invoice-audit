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
}


@dataclass(frozen=True)
class RateRule:
    service: str
    unit_basis: str
    rate_cents: int
    daily_cap: int | None


def money_to_cents(value: str) -> int:
    value = value.replace("GBP", "").replace(",", "").strip()
    return int(Decimal(value) * 100)


def parse_daily_cap(value: str) -> int | None:
    if value.strip() in {"", "—", "-"}:
        return None

    match = re.search(r"\d+", value)

    if match is None:
        raise ValueError(f"Cannot parse daily cap: {value}")

    return int(match.group())


def extract_rate_table(document: str) -> list[list[str]]:
    lines = document.splitlines()
    heading = "## 4. Rate Schedule"

    try:
        start = lines.index(heading)
    except ValueError as error:
        raise ValueError("Rate Schedule section not found") from error

    table_lines = []

    for line in lines[start + 1:]:
        stripped = line.strip()

        if stripped.startswith("## "):
            break

        if stripped.startswith("|"):
            table_lines.append(stripped)

    rows = []

    for line in table_lines:
        cells = [
            cell.strip()
            for cell in line.strip("|").split("|")
        ]

        is_separator = all(
            re.fullmatch(r":?-+:?", cell)
            for cell in cells
        )

        if not is_separator:
            rows.append(cells)

    return rows


def parse_rate_schedule(
    contract_path: Path,
) -> list[RateRule]:
    document = contract_path.read_text(encoding="utf-8")
    header, *data_rows = extract_rate_table(document)

    expected_header = [
        "Service",
        "Unit basis",
        "Rate",
        "Daily cap",
    ]

    if header != expected_header:
        raise ValueError(
            f"Unexpected rate table columns: {header}"
        )

    rules = []

    for service, unit_basis, rate, daily_cap in data_rows:
        normalized_basis = UNIT_BASIS_MAP.get(unit_basis)

        if normalized_basis is None:
            raise ValueError(
                f"Unknown unit basis: {unit_basis}"
            )

        rules.append(
            RateRule(
                service=service,
                unit_basis=normalized_basis,
                rate_cents=money_to_cents(rate),
                daily_cap=parse_daily_cap(daily_cap),
            )
        )

    services = [rule.service for rule in rules]

    if len(services) != len(set(services)):
        raise ValueError("Duplicate services found")

    return rules


def write_rules(
    rules: list[RateRule],
    output_path: Path,
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "service",
                "unit_basis",
                "rate_cents",
                "daily_cap",
            ],
        )

        writer.writeheader()
        writer.writerows(
            asdict(rule) for rule in rules
        )


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]

    contract_path = (
        project_root
        / "contracts"
        / "hospital_1"
        / "provider_services_agreement.md"
    )

    output_path = (
        project_root
        / "config"
        / "hospital_1_rates.csv"
    )

    rate_rules = parse_rate_schedule(contract_path)
    write_rules(rate_rules, output_path)

    print(f"Extracted {len(rate_rules)} rate rules")
    print(f"Saved to {output_path.relative_to(project_root)}")
    print("First rule:", rate_rules[0])