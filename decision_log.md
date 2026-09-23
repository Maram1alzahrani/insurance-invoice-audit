# Decision Log

## Scope

Hospital 1 was used as the labelled development set. Hospitals 3 and 4 were
implemented first, then coverage was extended to Hospitals 2 and 5. The final
submission includes all unique invoices from Hospitals 2–5.

The solution parses contract terms into deterministic rules, matches free-text
descriptions to contracted services, applies reimbursement and integrity
checks, calculates expected totals, and produces `submission.csv`.

## Tools and methods

- Python 3.11, `pandas`, `RapidFuzz`, and `Decimal` with half-up rounding.
- Rule-based contract engines rather than a trained classifier.
- `pytest` and aggregate-rule consistency checks for regression validation.
- AI assistance for iterative implementation, debugging, and documentation, as
  permitted by the exercise. The main prompt iterations are retained in
  `prompts/`; generated suggestions were reviewed and tested before use.

## Decisions and assumptions

| Issue | Decision |
|---|---|
| Duplicate invoice IDs | Flag the ID and use the last invoice row as the canonical record required by the one-row-per-ID submission format. |
| Money and rounding | Keep money as integer cents. Apply percentages and multipliers with `Decimal` and round half up after each contractually defined step. |
| Free-text descriptions | Normalize abbreviations and punctuation, then use fuzzy similarity. Unit basis and valid contract prices are supporting identity signals. |
| Uncertain service identity | Use `unknown_service` instead of forcing a contract rate when text, unit, and price evidence are insufficient. |
| Multiple errors | Preserve supported categories as sorted, pipe-separated values while flagging the invoice once. |
| Hospital 3 amendment | Apply substituted rates and newly added services only from their stated effective date. |
| Cumulative discounts | Count prior utilisation across the contract term in service-date and line-ID order, excluding the current line. |
| Hospital 5 adjustments | Apply bundle substitution, facility multiplier, plan-tier multiplier, premium or uplift, then cumulative discount. |
| Confidence | Treat confidence as a conservative rule-based judgment, not a trained probability. |

## Validation and unresolved limitations

Hospital 1 achieved invoice-level precision, recall, and F1 of 1.000 on the
development labels. This is an optimistic development result because the same
labels were used during iteration. One unknown-service category remains missed,
two additional overlapping date categories are reported, and four daily-cap
invoices have imperfect corrected totals. I did not hard-code invoice-specific
corrections.

Hospitals 2–5 are unlabelled, so their true precision and recall cannot be
claimed. The final submission contains 3,942 rows and 286 flags: 76 for
Hospital 2, 70 for Hospital 3, 64 for Hospital 4, and 76 for Hospital 5.

Hospital 3 initially produced 86 flags. Correcting cumulative utilisation
removed 16 flags whose revised expected totals matched their billed totals.
Aggregate-rule consistency checks for Hospitals 2, 3, and 5 found zero
differences for thresholds, bundles, caps, exclusions, and cumulative
discounts. All 17 automated tests pass.

The main remaining risks are ambiguous short descriptions, overlapping error
categories, exact reconstruction of some capped totals, and the absence of
labels for the scored hospitals.

## With one additional week

1. Independently review samples of flagged, unflagged, and borderline invoices.
2. Build a reviewed alias set and evaluate matching thresholds on held-out
   descriptions.
3. Add synthetic boundary tests for every adjustment and rounding interaction.
4. Add contract-clause provenance to each prediction.
5. Add continuous integration for tests and submission validation.