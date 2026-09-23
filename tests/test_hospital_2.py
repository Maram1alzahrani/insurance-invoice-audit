from dataclasses import asdict
from pathlib import Path

import pandas as pd

from src.invoice_audit.hospital_2_contract_rules import (
    load_hospital_2_rules,
)
from src.invoice_audit.hospital_2_parser import (
    parse_hospital_2_rates,
)
from src.invoice_audit.service_matcher import (
    ServiceMatcher,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

CONTRACT_PATH = (
    PROJECT_ROOT
    / "contracts"
    / "hospital_2"
    / "master_services_agreement.md"
)


def test_hospital_2_rate_extraction() -> None:
    rates = parse_hospital_2_rates(
        CONTRACT_PATH
    )

    assert len(rates) == 76

    assert sum(
        rate.daily_cap is not None
        for rate in rates
    ) == 8

    assert sum(
        bool(rate.identity_rates_cents)
        for rate in rates
    ) == 6


def test_hospital_2_rule_extraction() -> None:
    rules = load_hospital_2_rules(
        CONTRACT_PATH
    )

    assert len(
        rules.threshold_premiums
    ) == 9

    assert len(
        rules.weekend_uplifts
    ) == 8

    assert len(
        rules.volume_discounts
    ) == 8

    assert len(
        rules.bundles
    ) == 3

    assert len(
        rules.exclusions
    ) == 6


def test_bundle_rate_resolves_ambiguous_service() -> None:
    rates = parse_hospital_2_rates(
        CONTRACT_PATH
    )

    rates_frame = pd.DataFrame(
        asdict(rate)
        for rate in rates
    )

    matcher = ServiceMatcher(
        rates_frame
    )

    (
        matched_service,
        _,
        _,
    ) = matcher.match(
        "STD ISOL RM OCC",
        "per_day",
        27275,
    )

    assert matched_service == (
        "Standard Orthopaedic "
        "Isolation Room Occupancy"
    )