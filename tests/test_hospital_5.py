from pathlib import Path

import pandas as pd

from src.invoice_audit.hospital_5_contract_rules import (
    load_hospital_5_rules,
)
from src.invoice_audit.hospital_5_engine import (
    apply_context_multipliers,
    apply_multiplier,
)
from src.invoice_audit.hospital_5_parser import (
    parse_hospital_5_rates,
)


PROJECT_ROOT = (
    Path(__file__).resolve().parents[1]
)

CONTRACT_PATH = (
    PROJECT_ROOT
    / "contracts"
    / "hospital_5"
    / "network_reimbursement_agreement.md"
)


def test_hospital_5_rate_extraction() -> None:
    rates = parse_hospital_5_rates(
        CONTRACT_PATH
    )

    assert len(rates) == 84

    rates_by_service = {
        rate.service: rate
        for rate in rates
    }

    cardiac = rates_by_service[
        "Advanced Cardiac Ventilation Support"
    ]

    assert cardiac.unit_basis == "per_hour"
    assert cardiac.rate_cents == 3375
    assert cardiac.daily_cap == 24


def test_hospital_5_rule_extraction() -> None:
    rules = load_hospital_5_rules(
        CONTRACT_PATH
    )

    assert len(
        rules.threshold_premiums
    ) == 10

    assert len(
        rules.weekend_uplifts
    ) == 9

    assert len(
        rules.volume_discounts
    ) == 9

    assert len(rules.bundles) == 3
    assert len(rules.exclusions) == 7

    assert len(
        rules.facility_multipliers
    ) == 84

    assert len(
        rules.plan_multipliers
    ) == 84


def test_multiplier_rounding_order() -> None:
    after_facility = apply_multiplier(
        3375,
        "1.1",
    )

    after_plan = apply_multiplier(
        after_facility,
        "0.98",
    )

    assert after_facility == 3713
    assert after_plan == 3639


def test_context_multipliers_are_sequential() -> None:
    rules = load_hospital_5_rules(
        CONTRACT_PATH
    )

    data = pd.DataFrame(
        [
            {
                "reliable_match": True,
                "matched_service": (
                    "Advanced Cardiac "
                    "Ventilation Support"
                ),
                "facility_code": "F-NORTH",
                "plan_tier": "SILVER",
                "expected_rate_cents": 3375,
            }
        ]
    )

    apply_context_multipliers(
        data,
        rules,
    )

    assert int(
        data.loc[
            0,
            "expected_rate_cents",
        ]
    ) == 3639