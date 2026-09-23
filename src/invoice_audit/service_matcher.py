from __future__ import annotations

import argparse
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
from rapidfuzz import fuzz, process


ABBREVIATIONS = {
    "adv": "advanced",
    "ambul": "ambulatory",
    "amb": "ambulatory",
    "asst": "assisted",
    "beds": "bedside",
    "comp": "comprehensive",
    "compr": "comprehensive",
    "cont": "continuous",
    "elect": "elective",
    "emerg": "emergency",
    "emer": "emergency",
    "ext": "extended",
    "foc": "focused",
    "inpt": "inpatient",
    "intens": "intensive",
    "interm": "intermittent",
    "outpt": "outpatient",
    "postop": "postoperative",
    "preop": "preoperative",
    "rtn": "routine",
    "spclst": "specialist",
    "std": "standard",
    "sup": "supervised",
    "supv": "supervised",
    "card": "cardiac",
    "derm": "dermatologic",
    "endo": "endocrine",
    "ent": "otolaryngologic",
    "gi": "gastrointestinal",
    "ger": "geriatric",
    "geri": "geriatric",
    "haem": "haematology",
    "hep": "hepatic",
    "immun": "immunologic",
    "infect": "infectious",
    "metab": "metabolic",
    "msk": "musculoskeletal",
    "musc": "musculoskeletal",
    "neuro": "neurological",
    "obst": "obstetric",
    "onc": "oncology",
    "oncol": "oncology",
    "ophth": "ophthalmic",
    "ortho": "orthopaedic",
    "paed": "paediatric",
    "pall": "palliative",
    "psych": "psychiatric",
    "pulm": "pulmonary",
    "ren": "renal",
    "rheum": "rheumatologic",
    "urol": "urologic",
    "vasc": "vascular",
    "anaes": "anaesthesia",
    "anaesth": "anaesthesia",
    "admin": "administration",
    "anly": "analysis",
    "biop": "biopsy",
    "conf": "conference",
    "consult": "consultation",
    "cr": "care",
    "crit": "critical",
    "cs": "case",
    "diag": "diagnostic",
    "dial": "dialysis",
    "disch": "discharge",
    "endosc": "endoscopic",
    "fract": "fraction",
    "hm": "home",
    "img": "imaging",
    "inf": "infusion",
    "interp": "interpretation",
    "isol": "isolation",
    "lab": "laboratory",
    "monit": "monitoring",
    "nurs": "nursing",
    "nutr": "nutritional",
    "obs": "observation",
    "occ": "occupancy",
    "pharm": "pharmaceutical",
    "physio": "physiotherapy",
    "plng": "planning",
    "pnl": "panel",
    "proc": "procedure",
    "prog": "programme",
    "radiother": "radiotherapy",
    "recov": "recovery",
    "rehab": "rehabilitation",
    "rm": "room",
    "sess": "session",
    "spcm": "specimen",
    "steril": "sterilisation",
    "supp": "support",
    "svc": "service",
    "telem": "telemetry",
    "thtr": "theatre",
    "tm": "time",
    "transf": "transfusion",
    "transp": "transport",
    "vent": "ventilation",
    "vst": "visit",
    "wd": "ward",
    "wnd": "wound",
}


def normalize_description(
    text: str,
) -> str:
    text = re.sub(
        r"/[A-Za-z]{2}-\d+",
        " ",
        str(text),
    )

    text = re.sub(
        r"[^a-z0-9]+",
        " ",
        text.lower(),
    )

    return " ".join(
        ABBREVIATIONS.get(
            token,
            token,
        )
        for token in text.split()
    )


class ServiceMatcher:
    def __init__(
        self,
        rates: pd.DataFrame,
    ) -> None:
        self.rates = (
            rates.drop_duplicates(
                "service",
                keep="last",
            ).copy()
        )

        self.normalized_to_service = {
            normalize_description(
                service
            ): service
            for service in self.rates[
                "service"
            ]
        }

        if (
            len(self.normalized_to_service)
            != len(self.rates)
        ):
            raise ValueError(
                "Canonical service names collide "
                "after normalization"
            )

        self.service_to_unit_basis = (
            self.rates.set_index(
                "service"
            )["unit_basis"]
            .astype(str)
            .to_dict()
        )

        self.service_to_identity_rates: dict[
            str,
            set[int],
        ] = {}

        for row in self.rates.itertuples(
            index=False
        ):
            service = str(
                row.service
            )

            identity_rates = {
                int(row.rate_cents)
            }

            amended = getattr(
                row,
                "amended_rate_cents",
                None,
            )

            if (
                amended is not None
                and not pd.isna(amended)
            ):
                identity_rates.add(
                    int(amended)
                )

            additional_rates = getattr(
                row,
                "identity_rates_cents",
                None,
            )

            if (
                additional_rates is not None
                and not pd.isna(
                    additional_rates
                )
            ):
                if isinstance(
                    additional_rates,
                    (int, float),
                ):
                    identity_rates.add(
                        int(additional_rates)
                    )
                else:
                    identity_rates.update(
                        int(value)
                        for value in str(
                            additional_rates
                        ).split("|")
                        if value
                    )

            self.service_to_identity_rates[
                service
            ] = identity_rates

        self.choices = list(
            self.normalized_to_service
        )

    @lru_cache(maxsize=None)
    def match(
        self,
        description: str,
        billed_unit_basis: str,
        billed_price_cents: int,
    ) -> tuple[str, float, float]:
        normalized = normalize_description(
            description
        )

        matches = process.extract(
            normalized,
            self.choices,
            scorer=fuzz.token_set_ratio,
            limit=8,
        )

        if not matches:
            raise ValueError(
                "No contracted services available"
            )

        highest_score = float(
            matches[0][1]
        )

        close_matches = [
            match
            for match in matches
            if float(match[1])
            >= highest_score - 3.0
        ]

        price_candidates = []

        for match in close_matches:
            service = (
                self.normalized_to_service[
                    match[0]
                ]
            )

            if (
                int(billed_price_cents)
                in self.service_to_identity_rates[
                    service
                ]
            ):
                price_candidates.append(
                    match
                )

        if len(price_candidates) == 1:
            selected = price_candidates[0]
        else:
            unit_candidates = []

            for match in close_matches:
                service = (
                    self.normalized_to_service[
                        match[0]
                    ]
                )

                if (
                    self.service_to_unit_basis[
                        service
                    ]
                    == str(
                        billed_unit_basis
                    )
                ):
                    unit_candidates.append(
                        match
                    )

            selected = (
                max(
                    unit_candidates,
                    key=lambda item: float(
                        item[1]
                    ),
                )
                if unit_candidates
                else matches[0]
            )

        selected_text = selected[0]
        selected_score = float(
            selected[1]
        )

        service = (
            self.normalized_to_service[
                selected_text
            ]
        )

        other_scores = [
            float(match[1])
            for match in matches
            if match[0] != selected_text
        ]

        margin = (
            selected_score
            - (
                max(other_scores)
                if other_scores
                else 0.0
            )
        )

        return (
            service,
            selected_score,
            margin,
        )


def apply_temporal_rates(
    report: pd.DataFrame,
) -> pd.DataFrame:
    report = report.copy()

    service_dates = pd.to_datetime(
        report["service_date"],
        errors="coerce",
    )

    report["base_rate_cents"] = (
        pd.to_numeric(
            report["base_rate_cents"],
            errors="coerce",
        )
    )

    if {
        "amended_rate_cents",
        "amendment_effective_date",
    }.issubset(report.columns):
        amended_rates = pd.to_numeric(
            report[
                "amended_rate_cents"
            ],
            errors="coerce",
        )

        amendment_dates = pd.to_datetime(
            report[
                "amendment_effective_date"
            ],
            errors="coerce",
        )

        applies = (
            amended_rates.notna()
            & amendment_dates.notna()
            & service_dates.notna()
            & (
                service_dates
                >= amendment_dates
            )
        )

        report.loc[
            applies,
            "base_rate_cents",
        ] = amended_rates.loc[
            applies
        ]

    if "available_from" in report.columns:
        available_from = pd.to_datetime(
            report["available_from"],
            errors="coerce",
        )

        report[
            "service_not_yet_contracted"
        ] = (
            available_from.notna()
            & service_dates.notna()
            & (
                service_dates
                < available_from
            )
        )
    else:
        report[
            "service_not_yet_contracted"
        ] = False

    report["base_rate_cents"] = (
        report["base_rate_cents"]
        .round()
        .astype("Int64")
    )

    return report


def build_match_report(
    project_root: Path,
    hospital: int = 1,
) -> pd.DataFrame:
    rates = pd.read_csv(
        project_root
        / "config"
        / f"hospital_{hospital}_rates.csv"
    )

    lines = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_line_items.csv"
    )

    matcher = ServiceMatcher(
        rates
    )

    keys = lines[
        [
            "description",
            "unit_basis_as_billed",
            "unit_price_cents",
        ]
    ].drop_duplicates()

    keys[
        [
            "matched_service",
            "match_score",
            "match_margin",
        ]
    ] = keys.apply(
        lambda row: pd.Series(
            matcher.match(
                str(
                    row["description"]
                ),
                str(
                    row[
                        "unit_basis_as_billed"
                    ]
                ),
                int(
                    row[
                        "unit_price_cents"
                    ]
                ),
            )
        ),
        axis=1,
    )

    report = lines.merge(
        keys,
        on=[
            "description",
            "unit_basis_as_billed",
            "unit_price_cents",
        ],
        how="left",
        validate="many_to_one",
    )

    matched_rules = (
        rates.drop_duplicates(
            "service",
            keep="last",
        ).rename(
            columns={
                "service": "matched_service",
                "unit_basis": (
                    "expected_unit_basis"
                ),
                "rate_cents": (
                    "base_rate_cents"
                ),
            }
        )
    )

    report = report.merge(
        matched_rules,
        on="matched_service",
        how="left",
        validate="many_to_one",
    )

    report = apply_temporal_rates(
        report
    )

    report["unit_basis_matches"] = (
        report["unit_basis_as_billed"]
        == report["expected_unit_basis"]
    )

    billed_prices = pd.to_numeric(
        report["unit_price_cents"],
        errors="coerce",
    )

    report["base_price_matches"] = (
        billed_prices
        == report["base_rate_cents"]
    )

    original_unknown_signal = (
        (report["match_score"] < 90)
        & ~report[
            "unit_basis_matches"
        ]
        & ~report[
            "base_price_matches"
        ]
    )

    low_confidence_price_mismatch = (
        (report["match_score"] < 85)
        & ~report[
            "base_price_matches"
        ]
    )

    report[
        "suspected_unknown_service"
    ] = (
        original_unknown_signal
        | low_confidence_price_mismatch
    )

    return report


def evaluate_unknown_services(
    report: pd.DataFrame,
    labels_path: Path,
) -> None:
    labels = pd.read_csv(
        labels_path
    )

    predicted_ids = set(
        report.loc[
            report[
                "suspected_unknown_service"
            ],
            "invoice_id",
        ].astype(str)
    )

    actual_ids = set(
        labels.loc[
            labels[
                "error_categories"
            ]
            .fillna("")
            .str.contains(
                "unknown_service"
            ),
            "invoice_id",
        ].astype(str)
    )

    tp = len(
        predicted_ids
        & actual_ids
    )

    fp = len(
        predicted_ids
        - actual_ids
    )

    fn = len(
        actual_ids
        - predicted_ids
    )

    print(
        "Unknown-service evaluation: "
        f"TP={tp} FP={fp} FN={fn}"
    )


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--hospital",
        type=int,
        default=1,
        choices=[
            1,
            2,
            3,
            4,
            5,
        ],
    )

    args = parser.parse_args()

    project_root = (
        Path(__file__).resolve().parents[2]
    )

    report = build_match_report(
        project_root,
        hospital=args.hospital,
    )

    output_path = (
        project_root
        / "reports"
        / (
            f"hospital_{args.hospital}"
            "_service_matches.csv"
        )
    )

    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    report.to_csv(
        output_path,
        index=False,
    )

    print(
        f"Matched {len(report)} line items"
    )

    print(
        "Unique descriptions:",
        report[
            "description"
        ].nunique(),
    )

    print(
        "Suspected unknown-service invoices:",
        report.loc[
            report[
                "suspected_unknown_service"
            ],
            "invoice_id",
        ].nunique(),
    )

    if args.hospital == 1:
        evaluate_unknown_services(
            report,
            project_root
            / "labels"
            / "hospital_1_labels.csv",
        )

    print(
        "Services billed before availability:",
        report.loc[
            report[
                "service_not_yet_contracted"
            ],
            "invoice_id",
        ].nunique(),
    )

    print(
        "Saved to "
        f"{output_path.relative_to(project_root)}"
    )


if __name__ == "__main__":
    main()