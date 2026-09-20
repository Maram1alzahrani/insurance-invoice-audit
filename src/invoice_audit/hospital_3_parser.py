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

BASE_EFFECTIVE_DATE = "2024-01-01"
AMENDMENT_EFFECTIVE_DATE = "2025-01-01"


@dataclass(frozen=True)
class TemporalRateRule:
    service: str
    unit_basis: str
    rate_cents: int
    daily_cap: int | None
    amended_rate_cents: int | None
    amendment_effective_date: str | None
    available_from: str


def money_to_cents(value: str) -> int:
    cleaned = (
        value.replace("GBP", "")
        .replace(",", "")
        .strip()
    )

    return int(Decimal(cleaned) * 100)


def parse_daily_cap(value: str) -> int | None:
    if value.strip() in {"", "—", "-"}:
        return None

    match = re.search(r"\d+", value)

    if match is None:
        raise ValueError(
            f"Cannot parse daily cap: {value}"
        )

    return int(match.group())


def normalize_unit_basis(value: str) -> str:
    normalized = UNIT_BASIS_MAP.get(value.strip())

    if normalized is None:
        raise ValueError(
            f"Unknown unit basis: {value}"
        )

    return normalized


def extract_markdown_table(
    document: str,
    heading: str,
) -> list[list[str]]:
    lines = document.splitlines()

    try:
        start = lines.index(heading)
    except ValueError as error:
        raise ValueError(
            f"Section not found: {heading}"
        ) from error

    table_lines: list[str] = []

    for line in lines[start + 1:]:
        stripped = line.strip()

        if stripped.startswith("## "):
            break

        if stripped.startswith("|"):
            table_lines.append(stripped)

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
            re.fullmatch(r":?-+:?", cell)
            for cell in cells
        )

        if not is_separator:
            rows.append(cells)

    return rows


def parse_hospital_3_rates(
    appendix_path: Path,
    amendment_path: Path,
) -> list[TemporalRateRule]:
    appendix_document = appendix_path.read_text(
        encoding="utf-8"
    )

    amendment_document = amendment_path.read_text(
        encoding="utf-8"
    )

    appendix_rows = extract_markdown_table(
        appendix_document,
        "## B.1 Rates",
    )

    appendix_header, *appendix_data = appendix_rows

    expected_appendix_header = [
        "Service",
        "Unit basis",
        "Rate",
        "Daily cap",
    ]

    if appendix_header != expected_appendix_header:
        raise ValueError(
            "Unexpected Appendix B columns: "
            f"{appendix_header}"
        )

    rules_by_service: dict[
        str,
        TemporalRateRule,
    ] = {}

    for (
        service,
        unit_basis,
        rate,
        daily_cap,
    ) in appendix_data:
        if service in rules_by_service:
            raise ValueError(
                f"Duplicate base service: {service}"
            )

        rules_by_service[service] = TemporalRateRule(
            service=service,
            unit_basis=normalize_unit_basis(
                unit_basis
            ),
            rate_cents=money_to_cents(rate),
            daily_cap=parse_daily_cap(daily_cap),
            amended_rate_cents=None,
            amendment_effective_date=None,
            available_from=BASE_EFFECTIVE_DATE,
        )

    substituted_rows = extract_markdown_table(
        amendment_document,
        "## A1.2 Substituted Rates",
    )

    substituted_header, *substituted_data = (
        substituted_rows
    )

    expected_substituted_header = [
        "Service",
        "Unit basis",
        "Rate to 31 December 2024",
        "Rate from 1 January 2025",
    ]

    if (
        substituted_header
        != expected_substituted_header
    ):
        raise ValueError(
            "Unexpected substituted-rate columns: "
            f"{substituted_header}"
        )

    for (
        service,
        unit_basis,
        old_rate,
        new_rate,
    ) in substituted_data:
        if service not in rules_by_service:
            raise ValueError(
                "Amendment references unknown service: "
                f"{service}"
            )

        current = rules_by_service[service]
        normalized_basis = normalize_unit_basis(
            unit_basis
        )

        if normalized_basis != current.unit_basis:
            raise ValueError(
                f"Unit basis changed unexpectedly: {service}"
            )

        old_rate_cents = money_to_cents(old_rate)

        if old_rate_cents != current.rate_cents:
            raise ValueError(
                f"Old amendment rate does not match "
                f"Appendix B for: {service}"
            )

        rules_by_service[service] = (
            TemporalRateRule(
                service=current.service,
                unit_basis=current.unit_basis,
                rate_cents=current.rate_cents,
                daily_cap=current.daily_cap,
                amended_rate_cents=money_to_cents(
                    new_rate
                ),
                amendment_effective_date=(
                    AMENDMENT_EFFECTIVE_DATE
                ),
                available_from=current.available_from,
            )
        )

    additional_rows = extract_markdown_table(
        amendment_document,
        "## A1.3 Additional Services",
    )

    additional_header, *additional_data = (
        additional_rows
    )

    expected_additional_header = [
        "Service",
        "Unit basis",
        "Rate",
    ]

    if (
        additional_header
        != expected_additional_header
    ):
        raise ValueError(
            "Unexpected additional-service columns: "
            f"{additional_header}"
        )

    for service, unit_basis, rate in additional_data:
        if service in rules_by_service:
            raise ValueError(
                f"Additional service already exists: "
                f"{service}"
            )

        rules_by_service[service] = TemporalRateRule(
            service=service,
            unit_basis=normalize_unit_basis(
                unit_basis
            ),
            rate_cents=money_to_cents(rate),
            daily_cap=None,
            amended_rate_cents=None,
            amendment_effective_date=None,
            available_from=AMENDMENT_EFFECTIVE_DATE,
        )

    return list(rules_by_service.values())


def write_rules(
    rules: list[TemporalRateRule],
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
        "amended_rate_cents",
        "amendment_effective_date",
        "available_from",
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
            writer.writerow(asdict(rule))


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]

    contract_dir = (
        project_root
        / "contracts"
        / "hospital_3"
    )

    rules = parse_hospital_3_rates(
        contract_dir
        / "appendix_b_rate_schedule.md",
        contract_dir
        / "amendment_no_1.md",
    )

    output_path = (
        project_root
        / "config"
        / "hospital_3_rates.csv"
    )

    write_rules(
        rules,
        output_path,
    )

    amended_count = sum(
        rule.amended_rate_cents is not None
        for rule in rules
    )

    added_count = sum(
        rule.available_from
        == AMENDMENT_EFFECTIVE_DATE
        for rule in rules
    )

    print(f"Extracted {len(rules)} services")
    print(f"Amended services: {amended_count}")
    print(f"Added services: {added_count}")
    print(
        "Saved to "
        f"{output_path.relative_to(project_root)}"
    )


if __name__ == "__main__":
    main()