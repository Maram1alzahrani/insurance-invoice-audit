# Insurance Invoice Audit

This repository contains a reproducible, contract-aware audit pipeline for the
Meridian Health Assurance Group invoice-auditing exercise. It reads hospital
contracts and invoice data, normalizes free-text service descriptions, applies
contract and integrity rules, estimates corrected totals, and produces the
required submission file.

## Scope

- **Hospital 1** is used only as the labelled development and calibration set.
- **Hospitals 2, 3, 4, and 5** are included in the final submission.

The four unlabelled hospitals represent different contract structures:

- Hospital 2 expresses rates and conditional reimbursement rules throughout a
  long prose agreement.
- Hospital 3 combines a base agreement, rate appendix, and amendment with
  effective-date changes.
- Hospital 4 contains conditional reimbursement rules within a single
  agreement.
- Hospital 5 combines base rates with service-specific facility and plan-tier
  multipliers, followed by premiums, uplifts, and cumulative discounts.

## Approach

The solution is a rule-based audit engine rather than a trained predictive
model. Its main stages are:

1. Validate invoice IDs, contract numbers, dates, arithmetic, and totals.
2. Parse contract rates and adjustment clauses into structured rules.
3. Normalize billing descriptions and match them to contracted services using
   abbreviation expansion and fuzzy similarity.
4. Use unit basis and valid contract rates as supporting service-identity
   signals.
5. Apply contract-specific rules for rates, units, caps, bundles, exclusions,
   premiums, discounts, facility multipliers, plan-tier multipliers, and
   duplicate billing.
6. Apply cumulative utilisation rules in service-date and line-ID order while
   excluding the current line from its prior-utilisation count.
7. Retain uncertainty when a contractual service or exact corrected amount
   cannot be justified confidently.
8. Validate coverage, schema, integer cents, flags, categories, and confidence
   before writing `submission.csv`.

All monetary calculations use integer cents. Percentage adjustments and
multipliers use `Decimal` with half-up rounding after each contractually defined
calculation step.

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
├── evaluation_report.md            # Development evaluation and error analysis
├── requirements.txt                # Pinned Python dependencies
└── submission.csv                  # Final Hospitals 2–5 predictions
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

### 1. Parse the contracts

```bash
python -m src.invoice_audit.contract_parser
python -m src.invoice_audit.hospital_2_parser
python -m src.invoice_audit.hospital_3_parser
python -m src.invoice_audit.hospital_4_parser
python -m src.invoice_audit.hospital_5_parser
```

### 2. Run Hospital 1 development evaluation

```bash
python -m src.invoice_audit.audit_engine
```

### 3. Generate Hospital 2 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 2
python -m src.invoice_audit.hospital_2_engine
```

### 4. Generate Hospital 3 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 3
python -m src.invoice_audit.hospital_3_engine
```

### 5. Generate Hospital 4 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 4
python -m src.invoice_audit.hospital_4_engine
```

### 6. Generate Hospital 5 predictions

```bash
python -m src.invoice_audit.service_matcher --hospital 5
python -m src.invoice_audit.hospital_5_engine
```

### 7. Build and validate the final submission

```bash
python -m src.invoice_audit.build_submission
```

The final command writes `submission.csv` and fails with a descriptive error if
coverage, schema, ID uniqueness, monetary types, flags, categories, or
confidence values are invalid.

### 8. Run validation checks

```bash
python -m src.invoice_audit.aggregate_rule_audit --hospital 2
python -m src.invoice_audit.aggregate_rule_audit --hospital 3
python -m src.invoice_audit.hospital_5_aggregate_audit
python -m pytest -q
```

The aggregate-rule consistency checks compare threshold premiums, bundles,
daily caps, exclusion windows, and cumulative volume discounts against all
available line items. Hospitals 2, 3, and 5 completed these checks with zero
differences. The automated test suite contains 17 passing tests.

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
| Hospital 2 | 1,125 | 76 | 6.756% |
| Hospital 3 | 932 | 70 | 7.511% |
| Hospital 4 | 835 | 64 | 7.665% |
| Hospital 5 | 1,050 | 76 | 7.238% |
| **Combined** | **3,942** | **286** | **7.255%** |

Hospitals 2–5 do not have ground-truth labels. These counts are audit
predictions and should not be interpreted as measured accuracy, precision, or
recall.

Hospital 3 originally produced 86 flagged invoices. After correcting cumulative
utilisation to count all prior service lines across the contract term, 16 flags
were removed because their recalculated expected totals matched their billed
totals. The revised Hospital 3 output contains 70 flagged invoices.

## Key limitations

- Hospitals 2–5 do not have labels, so their predictive accuracy cannot be
  measured directly.
- Short descriptions can be lexical subsets of longer contracted service names
  and receive misleadingly high fuzzy scores.
- Unit basis and valid contract prices reduce service-matching ambiguity but do
  not eliminate it in every case.
- Multiple factual date violations may overlap while a reference taxonomy uses
  only one primary category.
- Daily-cap violations can be detected even when interaction with other rules
  leaves the exact corrected total ambiguous.
- Confidence scores are conservative rule-based judgments, not calibrated
  probabilities from an independent validation set.

Assumptions, rule interpretations, and unresolved limitations are documented in
[`decision_log.md`](decision_log.md).

## AI assistance disclosure

AI assistance was used for planning, code drafting, debugging, rule iteration,
and documentation, as explicitly permitted by the exercise. Generated code was
executed locally, compared with Hospital 1 labels, reviewed on uncertain cases,
and regression-tested before acceptance. The main prompt iterations are stored
as versioned files in [`prompts/`](prompts/).