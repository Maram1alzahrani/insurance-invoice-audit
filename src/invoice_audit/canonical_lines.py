from pathlib import Path

import pandas as pd


def find_canonical_line_ids(
    project_root: Path,
    hospital: int,
) -> set[str]:
    """
    Select the line-item group belonging to the last invoice row
    when the same invoice_id appears more than once.
    """

    invoices_all = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_invoices.csv"
    )

    lines = pd.read_csv(
        project_root
        / "invoices"
        / f"hospital_{hospital}_line_items.csv"
    )

    duplicate_ids = set(
        invoices_all.loc[
            invoices_all.duplicated(
                "invoice_id",
                keep=False,
            ),
            "invoice_id",
        ].astype(str)
    )

    keep_line_ids = set(
        lines.loc[
            ~lines["invoice_id"].astype(str).isin(
                duplicate_ids
            ),
            "line_id",
        ].astype(str)
    )

    canonical_invoices = invoices_all.drop_duplicates(
        "invoice_id",
        keep="last",
    ).set_index("invoice_id")

    lines["service_date_parsed"] = pd.to_datetime(
        lines["service_date"],
        errors="coerce",
    )

    lines["claim_group"] = (
        lines["line_id"]
        .astype(str)
        .str.extract(r"-L(\d+)-")[0]
    )

    for invoice_id in duplicate_ids:
        invoice_lines = lines[
            lines["invoice_id"].astype(str).eq(
                invoice_id
            )
        ].copy()

        canonical_invoice = canonical_invoices.loc[
            invoice_id
        ]

        admission_date = pd.to_datetime(
            canonical_invoice["admission_date"],
            errors="coerce",
        )

        discharge_date = pd.to_datetime(
            canonical_invoice["discharge_date"],
            errors="coerce",
        )

        scored_groups = []

        for claim_group, group in invoice_lines.groupby(
            "claim_group",
            dropna=False,
        ):
            inside_stay = group[
                "service_date_parsed"
            ].between(
                admission_date,
                discharge_date,
            )

            inside_count = int(
                inside_stay.sum()
            )

            valid_dates = group[
                "service_date_parsed"
            ].dropna()

            if valid_dates.empty:
                median_distance = float("inf")
            else:
                median_distance = float(
                    (
                        valid_dates - admission_date
                    )
                    .abs()
                    .dt.days
                    .median()
                )

            scored_groups.append(
                (
                    inside_count,
                    -median_distance,
                    str(claim_group),
                    group,
                )
            )

        if not scored_groups:
            continue

        selected_group = max(
            scored_groups,
            key=lambda item: (
                item[0],
                item[1],
                item[2],
            ),
        )[3]

        keep_line_ids.update(
            selected_group["line_id"].astype(str)
        )

    return keep_line_ids