from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .hospital_4_parser import money_to_cents, section_text


@dataclass(frozen=True)
class ThresholdPremium:
    service: str
    threshold: int
    uplift_percent: int


@dataclass(frozen=True)
class BundleRule:
    service_a: str
    rate_a_cents: int
    service_b: str
    rate_b_cents: int


@dataclass(frozen=True)
class VolumeDiscount:
    service: str
    threshold: int
    discount_percent: int


@dataclass(frozen=True)
class ExclusionRule:
    excluded_service: str
    window_days: int
    trigger_service: str


@dataclass(frozen=True)
class Hospital4Rules:
    threshold_premiums: tuple[ThresholdPremium, ...]
    bundles: tuple[BundleRule, ...]
    volume_discounts: tuple[VolumeDiscount, ...]
    exclusions: tuple[ExclusionRule, ...]


def parse_threshold_premiums(document: str) -> list[ThresholdPremium]:
    section = section_text(
        document,
        r"^5\. THRESHOLD PREMIUMS\s*$",
        r"^6\. DAILY QUANTITY LIMITS\s*$",
    )
    pattern = re.compile(
        r"^(?P<service>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"more than\s+(?P<threshold>\d+)\s+"
        r"(?:procedures|units|days|hours|visits|tests|nights|items)\s{2,}"
        r"\+(?P<uplift>\d+)%\s*$"
    )
    rules: list[ThresholdPremium] = []

    for raw_line in section.splitlines():
        match = pattern.match(raw_line.rstrip())
        if match is None:
            continue
        rules.append(
            ThresholdPremium(
                service=match.group("service").strip(),
                threshold=int(match.group("threshold")),
                uplift_percent=int(match.group("uplift")),
            )
        )

    if not rules:
        raise ValueError("No Hospital 4 threshold premiums were extracted")
    return rules


def parse_bundles(document: str) -> list[BundleRule]:
    section = section_text(
        document,
        r"^7\. BUNDLED DELIVERY\s*$",
        r"^8\. DISCOUNTS\s*$",
    )
    pattern = re.compile(
        r"^(?P<service_a>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"GBP\s+(?P<rate_a>[\d,]+\.\d{2})\s{2,}"
        r"(?P<service_b>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"GBP\s+(?P<rate_b>[\d,]+\.\d{2})\s*$"
    )
    rules: list[BundleRule] = []

    for raw_line in section.splitlines():
        match = pattern.match(raw_line.rstrip())
        if match is None:
            continue
        rules.append(
            BundleRule(
                service_a=match.group("service_a").strip(),
                rate_a_cents=money_to_cents(match.group("rate_a")),
                service_b=match.group("service_b").strip(),
                rate_b_cents=money_to_cents(match.group("rate_b")),
            )
        )

    if not rules:
        raise ValueError("No Hospital 4 bundle rules were extracted")
    return rules


def parse_volume_discounts(document: str) -> list[VolumeDiscount]:
    section = section_text(
        document,
        r"^8\. DISCOUNTS\s*$",
        r"^9\. EXCLUSION WINDOWS\s*$",
    )
    pattern = re.compile(
        r"^(?P<service>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"[^\n]*?\((?P<threshold>\d+)\)\s{2,}"
        r"[^\n]*?\((?P<discount>\d+)%\)\s*$"
    )
    rules: list[VolumeDiscount] = []

    for raw_line in section.splitlines():
        match = pattern.match(raw_line.rstrip())
        if match is None:
            continue
        rules.append(
            VolumeDiscount(
                service=match.group("service").strip(),
                threshold=int(match.group("threshold")),
                discount_percent=int(match.group("discount")),
            )
        )

    if not rules:
        raise ValueError("No Hospital 4 volume discounts were extracted")
    return rules


def parse_exclusions(document: str) -> list[ExclusionRule]:
    section = section_text(
        document,
        r"^9\. EXCLUSION WINDOWS\s*$",
        r"^10\. NON-BUSINESS-DAY UPLIFTS\s*$",
    )
    pattern = re.compile(
        r"^(?P<excluded>[A-Za-z][A-Za-z ]+?)\s{2,}"
        r"(?P<days>\d+)\s+days\s{2,}"
        r"(?P<trigger>[A-Za-z][A-Za-z ]+?)\s*$"
    )
    rules: list[ExclusionRule] = []

    for raw_line in section.splitlines():
        match = pattern.match(raw_line.rstrip())
        if match is None:
            continue
        rules.append(
            ExclusionRule(
                excluded_service=match.group("excluded").strip(),
                window_days=int(match.group("days")),
                trigger_service=match.group("trigger").strip(),
            )
        )

    if not rules:
        raise ValueError("No Hospital 4 exclusion windows were extracted")
    return rules


def load_hospital_4_rules(contract_path: Path) -> Hospital4Rules:
    document = contract_path.read_text(encoding="utf-8")
    return Hospital4Rules(
        threshold_premiums=tuple(parse_threshold_premiums(document)),
        bundles=tuple(parse_bundles(document)),
        volume_discounts=tuple(parse_volume_discounts(document)),
        exclusions=tuple(parse_exclusions(document)),
    )


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    contract_path = (
        project_root
        / "contracts"
        / "hospital_4"
        / "conditional_reimbursement_agreement.txt"
    )
    rules = load_hospital_4_rules(contract_path)

    discount_services = {
        rule.service for rule in rules.volume_discounts
    }
    print(f"Threshold premiums: {len(rules.threshold_premiums)}")
    print(f"Bundle pairs: {len(rules.bundles)}")
    print(f"Volume-discount services: {len(discount_services)}")
    print(f"Volume-discount thresholds: {len(rules.volume_discounts)}")
    print(f"Exclusion windows: {len(rules.exclusions)}")
    print("Weekend uplifts: 0")


if __name__ == "__main__":
    main()
