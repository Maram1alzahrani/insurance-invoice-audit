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
class RateRule:
    service: str
    unit_basis: str
    rate_cents: int
    daily_cap: int | None


def money_to_cents(value: str) -> int:
    cleaned = value.replace("GBP", "").replace(",", "").strip()
    return int(Decimal(cleaned) * 100)


def section_text(document: str, start: str, end: str) -> str:
    start_match = re.search(start, document, flags=re.MULTILINE)
    if start_match is None:
        raise ValueError(f"Section not found: {start}")

    end_match = re.search(
        end,
        document[start_match.end():],
        flags=re.MULTILINE,
    )

    if end_match is None:
        return document[start_match.end():]

    return document[
        start_match.end():
        start_match.end() + end_match.start()
    ]


def parse_base_rates(document: str) -> list[tuple[str, str, int]]:
    section = section_text(
        document,
        r"^3\. BASE RATES\s*$",
        r"^4\. ORDER OF ADJUSTMENTS\s*$",
    )

    unit_pattern = "|".join(
        re.escape(value)
        for value in sorted(
            UNIT_BASIS_MAP,
            key=len,
            reverse=True,
        )
    )

    row_pattern = re.compile(
        rf"^(?P<service>[A-Za-z][A-Za-z ]+?)\s{{2,}}"
        rf"(?P<unit>{unit_pattern})\s{{2,}}"
        r"GBP\s+(?P<rate>[\d,]+\.\d{2})\s*$"
    )

    rows: list[tuple[str, str, int]] = []

    for raw_line in section.splitlines():
        match = row_pattern.match(raw_line.rstrip())
        if match is None:
            continue

        rows.append(
            (
                match.group("service").strip(),
                UNIT_BASIS_MAP[match.group("unit")],
                money_to_cents(match.group("rate")),
            )
        )

    if not rows:
        raise ValueError("No Hospital 4 base rates were extracted")

    services = [service for service, _, _ in rows]
    if len(services) != len(set(services)):
        raise ValueError("Duplicate services found in Hospital 4 base rates")

    return rows


def parse_daily_caps(document: str) -> dict[str, int]:
    section = section_text(
        document,
        r"^6\. DAILY QUANTITY LIMITS\s*$",
        r"^7\. BUNDLED DELIVERY\s*$",
    )

    row_pattern = re.compile(
        r"^(?P<service>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"(?P<cap>\d+)\s+"
        r"(?:nights|days|hours|items|units|procedures|visits|tests)\s*$"
    )

    caps: dict[str, int] = {}

    for raw_line in section.splitlines():
        match = row_pattern.match(raw_line.rstrip())
        if match is None:
            continue

        service = match.group("service").strip()
        if service in caps:
            raise ValueError(f"Duplicate daily cap for service: {service}")

        caps[service] = int(match.group("cap"))

    if not caps:
        raise ValueError("No Hospital 4 daily quantity limits were extracted")

    return caps


def parse_hospital_4_contract(contract_path: Path) -> list[RateRule]:
    document = contract_path.read_text(encoding="utf-8")
    base_rates = parse_base_rates(document)
    daily_caps = parse_daily_caps(document)

    contracted_services = {service for service, _, _ in base_rates}
    unknown_cap_services = set(daily_caps) - contracted_services

    if unknown_cap_services:
        raise ValueError(
            "Daily caps reference services missing from the rate table: "
            + ", ".join(sorted(unknown_cap_services))
        )

    return [
        RateRule(
            service=service,
            unit_basis=unit_basis,
            rate_cents=rate_cents,
            daily_cap=daily_caps.get(service),
        )
        for service, unit_basis, rate_cents in base_rates
    ]


def write_rules(rules: list[RateRule], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8", newline="") as file:
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
        writer.writerows(asdict(rule) for rule in rules)


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contract_path = (
        project_root
        / "contracts"
        / "hospital_4"
        / "conditional_reimbursement_agreement.txt"
    )
    output_path = project_root / "config" / "hospital_4_rates.csv"

    rules = parse_hospital_4_contract(contract_path)
    write_rules(rules, output_path)

    capped_services = sum(rule.daily_cap is not None for rule in rules)
    print(f"Extracted {len(rules)} services")
    print(f"Services with daily caps: {capped_services}")
    print(f"Saved to {output_path.relative_to(project_root)}")


if __name__ == "__main__":
    main()
