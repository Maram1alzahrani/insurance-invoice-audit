# Insurance Invoice Audit

This repository contains a reproducible, contract-aware audit pipeline for the
Meridian Health Assurance Group invoice-auditing exercise. It reads hospital
contracts and invoice data, normalizes free-text service descriptions, applies
contract and integrity rules, estimates corrected totals, and produces the
required submission file.

## Scope

- **Hospital 1** is used only as the labelled development and calibration set.
- **Hospitals 3 and 4** are the two unlabelled hospitals included in the final
  submission.
- Hospitals 2 and 5 were intentionally left out to prioritise two complete,
  reviewed implementations over a shallow pass across all four unlabelled
  hospitals.

Hospital 3 was selected because its contract is split across a base agreement,
rate appendix, and amendment with effective-date changes. Hospital 4 was
selected because its single agreement contains a different set of conditional
reimbursement rules. This combination tests both document reconciliation and
rule interaction.

## Approach

The solution is a rule-based audit engine rather than a trained predictive
model. Its main stages are:

1. Validate invoice IDs, contract numbers, dates, arithmetic, and totals.
2. Parse contract rate tables and adjustment clauses into structured rules.
3. Normalize billing descriptions and match them to contracted services using
   abbreviation expansion and fuzzy similarity.
4. Use unit basis and price as supporting identity signals.
5. Apply contract-specific rules for rates, units, caps, bundles, exclusions,
   premiums, discounts, and duplicate billing.
6. Retain uncertainty when a contractual service or exact corrected amount
   cannot be justified confidently.
7. Validate coverage, schema, cents, flags, categories, and confidence before
   writing `submission.csv`.

All monetary calculations use integer cents. Percentage adjustments use
`Decimal` with half-up rounding.

## Repository structure

```text
.
├── config/                         # Parsed contract rate tables
├── contracts/                      # Source contracts supplied with the task
├── invoices/                       # Source invoice and line-item data
├── labels/                         # Hospital 1 development labels
├── prompts/                        # Versioned AI prompt history
├── reports/                        # Generated predictions and review reports
├── src/invoice_audit/              # Parsers, matchers, rules, and engines
├── tests/                          # Automated tests
├── decision_log.md                 # Assumptions and unresolved ambiguities
├── evaluation_report.md            # Hospital 1 evaluation and error analysis
├── requirements.txt                # Pinned Python dependencies
└── submission.csv                  # Final Hospitals 3 and 4 predictions
```

## Setup

Python 3.11 is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Reproduce the outputs

Run the following commands from the repository root.

### 1. Parse the selected contracts

```bash
python -m src.invoice_audit.contract_parser
python -m src.invoice_audit.hospital_3_parser
python -m src.invoice_audit.hospital_4_parser
```

### 2. Run Hospital 1 development evaluation

```bash
python -m src.invoice_audit.audit_engine
```

### 3. Generate Hospital 3 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 3
python -m src.invoice_audit.hospital_3_engine
```

### 4. Generate Hospital 4 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 4
python -m src.invoice_audit.hospital_4_engine
```

### 5. Build and validate the final submission

```bash
python -m src.invoice_audit.build_submission
```

The last command writes `submission.csv` and fails with a descriptive error if
coverage, schema, ID uniqueness, monetary types, flags, categories, or
confidence values are invalid.

## Results

### Hospital 1 development set

| Metric | Value |
|---|---:|
| True positives | 58 |
| False positives | 0 |
| False negatives | 0 |
| True negatives | 855 |
| Precision | 1.000 |
| Recall | 1.000 |
| F1 | 1.000 |

This is a development-set result, not an unbiased estimate of unseen-hospital
performance. Hospital 1 labels were used while refining the rules and matching
thresholds. Category-level evaluation is not perfect: unknown-service recall is
11/12, two additional overlapping date categories are reported, and exact
corrected totals match 93.1% of erroneous invoices. See
[`evaluation_report.md`](evaluation_report.md) for the full evaluation and
failure analysis.

### Unlabelled hospitals

| Hospital | Unique invoices | Flagged | Flag rate |
|---|---:|---:|---:|
| Hospital 3 | 932 | 86 | 9.227% |
| Hospital 4 | 835 | 64 | 7.665% |
| **Combined** | **1,767** | **150** | **8.489%** |

Hospitals 3 and 4 do not have ground-truth labels. These counts are audit
predictions and should not be interpreted as measured accuracy.

## Key limitations

- Short descriptions can be lexical subsets of longer contracted service names
  and receive misleadingly high fuzzy scores.
- Multiple factual date violations may overlap while a reference taxonomy uses
  only one primary category.
- Daily-cap violations can be detected even when interaction with other rules
  leaves the exact corrected total ambiguous.
- Confidence scores are conservative rule-based judgments, not calibrated
  probabilities from an independent validation set.
- Hospitals 2 and 5 are not included in the current submission.

Assumptions, rule interpretations, and next steps are documented in
[`decision_log.md`](decision_log.md).

## AI assistance disclosure

AI assistance was used for planning, code drafting, debugging, rule iteration,
and documentation, as explicitly permitted by the exercise. Generated code was
executed locally, compared with Hospital 1 labels, reviewed on uncertain cases,
and regression-tested before acceptance. The main prompt iterations are stored
as versioned files in [`prompts/`](prompts/).
