# Decision Log

## What I implemented

I used Hospital 1 as the labelled development and calibration set, then built
the final audit coverage for Hospitals 3 and 4. I selected these two because
they represent different contract structures: Hospital 3 combines a base
agreement, rate appendix, and dated amendment, while Hospital 4 contains
conditional reimbursement rules in one agreement. This provided meaningful
coverage within the exercise time limit instead of thin coverage across every
hospital.

The pipeline parses contract rate tables, normalizes abbreviated service
descriptions, matches invoice lines to contracted services, applies contract
and data-integrity rules, calculates expected totals, assigns error categories,
and generates the required `submission.csv`. It checks contract numbers,
invoice and line arithmetic, dates, duplicate IDs and services, unit basis,
rates, daily caps, bundles, premiums, exclusions, and volume discounts.

## Tools and methods used

- Python 3.11 with `pandas` for loading, joining, validating, and aggregating
  invoice data.
- `RapidFuzz` plus deterministic text normalization for service matching.
- `Decimal` with round-half-up for percentage adjustments while keeping all
  money as integer cents.
- Rule-based contract engines for transparent, auditable decisions rather than
  a trained classifier.
- `pytest` for automated validation of submission structure, coverage, data
  types, confidence values, categories, uniqueness, and ordering.
- AI assistance for iterative implementation, debugging, and documentation, as
  permitted by the exercise. The main prompt iterations are retained in
  `prompts/`; generated suggestions were reviewed and tested before use.

## Key decisions and assumptions

- Duplicate invoice IDs are flagged, and the last invoice row is treated as
  the canonical record required by the one-row-per-ID submission format.
- Free-text matches require semantic similarity, with price and unit basis used
  only as supporting signals. Unreliable matches are classified as
  `unknown_service` instead of forcing a contract rate.
- Multiple supported errors are preserved as sorted, pipe-separated categories.
- Cross-invoice duplicates require the same patient and exact line signature;
  only the copied occurrence outside the genuine stay is removed.
- Contract rules are applied in their stated order, including amendment
  effective dates and interactions between bundles, premiums, and discounts.
- Confidence values are rule-based judgments, not trained probabilities.

## Validation and limitations

Hospital 1 achieved invoice-level precision, recall, and F1 of 1.000 on the
provided development labels. This is an optimistic development-set result, not
an estimate of unseen performance. Category-level evaluation still shows one
missed unknown-service case, two additional factual date-category flags, and
four daily-cap invoices whose corrected totals do not exactly match the labels.
I did not hard-code those invoice-specific answers because that would overfit
the labelled data.

Hospitals 3 and 4 are unlabelled, so their true accuracy cannot be claimed. The
final submission contains every unique invoice from both hospitals: 1,767 rows,
with 150 flagged. Low-confidence and rate-mismatch cases were exported for
manual review, and eight automated submission tests pass.

## What I would do with one additional week

1. Implement Hospitals 2 and 5 using the same staged parsing, matching, review,
   and validation workflow.
2. Add contract-rule unit tests with small synthetic examples for every bundle,
   premium, discount, cap, exclusion, and amendment boundary.
3. Improve service matching with contract-specific aliases and a manually
   reviewed validation set, then calibrate thresholds without invoice-specific
   exceptions.
4. Perform a second independent review of flagged and borderline Hospital 3
   and 4 cases and measure reviewer agreement.
5. Add continuous integration so tests and submission validation run
   automatically on every change.
