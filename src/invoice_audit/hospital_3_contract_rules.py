from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .hospital_3_parser import (
    extract_markdown_table,
    money_to_cents,
)


@dataclass(frozen=True)
class Hospital3Rules:
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


def extract_integer(value: str) -> int:
    match = re.search(r"\d+", value)

    if match is None:
        raise ValueError(
            f"Integer not found in: {value}"
        )

    return int(match.group())


def extract_percentage(value: str) -> int:
    match = re.search(r"(\d+)\s*%", value)

    if match is None:
        raise ValueError(
            f"Percentage not found in: {value}"
        )

    return int(match.group(1))


def parse_threshold_premiums(
    document: str,
) -> dict[str, tuple[int, int]]:
    rows = extract_markdown_table(
        document,
        "## 4. Threshold Premiums",
    )

    header, *data_rows = rows

    expected_header = [
        "Service",
        "Daily quantity threshold",
        "Uplift",
    ]

    if header != expected_header:
        raise ValueError(
            "Unexpected threshold premium columns: "
            f"{header}"
        )

    rules: dict[
        str,
        tuple[int, int],
    ] = {}

    for service, threshold, uplift in data_rows:
        rules[service] = (
            extract_integer(threshold),
            extract_percentage(uplift),
        )

    return rules


def parse_weekend_uplifts(
    document: str,
) -> dict[str, int]:
    rows = extract_markdown_table(
        document,
        "## 5. Non-Business-Day Uplifts",
    )

    header, *data_rows = rows

    expected_header = [
        "Service",
        "Uplift",
    ]

    if header != expected_header:
        raise ValueError(
            "Unexpected weekend uplift columns: "
            f"{header}"
        )

    return {
        service: extract_percentage(uplift)
        for service, uplift in data_rows
    }


def parse_volume_discounts(
    document: str,
) -> dict[str, list[tuple[int, int]]]:
    rows = extract_markdown_table(
        document,
        "## 6. Cumulative Volume Discounts",
    )

    header, *data_rows = rows

    expected_header = [
        "Service",
        "Cumulative utilisation",
        "Discount",
    ]

    if header != expected_header:
        raise ValueError(
            "Unexpected volume discount columns: "
            f"{header}"
        )

    rules: dict[
        str,
        list[tuple[int, int]],
    ] = {}

    for (
        service,
        utilisation,
        discount,
    ) in data_rows:
        rules.setdefault(
            service,
            [],
        ).append(
            (
                extract_integer(utilisation),
                extract_percentage(discount),
            )
        )

    for service in rules:
        rules[service] = sorted(
            rules[service],
            key=lambda item: item[0],
        )

    return rules


def parse_bundles(
    document: str,
) -> list[tuple[str, str, int, int]]:
    rows = extract_markdown_table(
        document,
        "## 8. Bundled Services",
    )

    header, *data_rows = rows

    expected_header = [
        "Service A",
        "Service B",
        "Bundled rate A",
        "Bundled rate B",
    ]

    if header != expected_header:
        raise ValueError(
            "Unexpected bundle columns: "
            f"{header}"
        )

    return [
        (
            service_a,
            service_b,
            money_to_cents(rate_a),
            money_to_cents(rate_b),
        )
        for (
            service_a,
            service_b,
            rate_a,
            rate_b,
        ) in data_rows
    ]


def parse_exclusions(
    document: str,
) -> list[tuple[str, str, int]]:
    rows = extract_markdown_table(
        document,
        "## 9. Exclusion Windows",
    )

    header, *data_rows = rows

    expected_header = [
        "Service",
        "Not billable within",
        "Of this Service",
    ]

    if header != expected_header:
        raise ValueError(
            "Unexpected exclusion columns: "
            f"{header}"
        )

    return [
        (
            excluded_service,
            trigger_service,
            extract_integer(window),
        )
        for (
            excluded_service,
            window,
            trigger_service,
        ) in data_rows
    ]


def load_hospital_3_rules(
    contract_path: Path,
) -> Hospital3Rules:
    document = contract_path.read_text(
        encoding="utf-8"
    )

    return Hospital3Rules(
        threshold_premiums=(
            parse_threshold_premiums(
                document
            )
        ),
        weekend_uplifts=(
            parse_weekend_uplifts(
                document
            )
        ),
        volume_discounts=(
            parse_volume_discounts(
                document
            )
        ),
        bundles=parse_bundles(
            document
        ),
        exclusions=parse_exclusions(
            document
        ),
    )


def main() -> None:
    project_root = (
        Path(__file__).resolve().parents[2]
    )

    contract_path = (
        project_root
        / "contracts"
        / "hospital_3"
        / "base_agreement.md"
    )

    rules = load_hospital_3_rules(
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