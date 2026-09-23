import pandas as pd

from src.invoice_audit.hospital_3_contract_rules import (
    Hospital3Rules,
)
from src.invoice_audit.hospital_3_engine import (
    apply_volume_discounts,
)


SERVICE = "Test Contracted Service"


def make_rules() -> Hospital3Rules:
    return Hospital3Rules(
        threshold_premiums={},
        weekend_uplifts={},
        volume_discounts={
            SERVICE: [(100, 10)],
        },
        bundles=[],
        exclusions=[],
    )


def make_target_data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "line_id": "CURRENT-LINE",
                "matched_service": SERVICE,
                "reliable_match": True,
                "expected_rate_cents": 10000,
                "discount_percentage": 0,
            }
        ]
    )


def test_volume_discount_uses_full_term_utilisation() -> None:
    data = make_target_data()

    full_report = pd.DataFrame(
        [
            {
                "line_id": "PRIOR-NON-CANONICAL-LINE",
                "service_date": "2024-01-01",
                "quantity": 101,
                "matched_service": SERVICE,
                "suspected_unknown_service": False,
                "base_rate_cents": 10000,
            },
            {
                "line_id": "CURRENT-LINE",
                "service_date": "2024-01-02",
                "quantity": 1,
                "matched_service": SERVICE,
                "suspected_unknown_service": False,
                "base_rate_cents": 10000,
            },
        ]
    )

    apply_volume_discounts(
        data,
        make_rules(),
        full_report,
    )

    assert data.loc[
        0,
        "discount_percentage",
    ] == 10

    assert data.loc[
        0,
        "expected_rate_cents",
    ] == 9000


def test_current_line_quantity_is_excluded() -> None:
    data = make_target_data()

    full_report = pd.DataFrame(
        [
            {
                "line_id": "CURRENT-LINE",
                "service_date": "2024-01-01",
                "quantity": 500,
                "matched_service": SERVICE,
                "suspected_unknown_service": False,
                "base_rate_cents": 10000,
            }
        ]
    )

    apply_volume_discounts(
        data,
        make_rules(),
        full_report,
    )

    assert data.loc[
        0,
        "discount_percentage",
    ] == 0

    assert data.loc[
        0,
        "expected_rate_cents",
    ] == 10000