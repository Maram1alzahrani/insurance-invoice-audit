# Prompt Version 2 — Contract Parsing and Rule Engine

## Goal

Improve recall using explicit Hospital 1 contract logic while avoiding
invoice-specific label leakage.

## Prompt

> Parse the Hospital 1 Markdown contract into structured rate rules containing
> service name, normalized unit basis, integer rate in cents, and daily cap.
> Build a service matcher for free-text billing descriptions by normalizing
> punctuation, reference suffixes, and common abbreviations, then use fuzzy
> text score and match margin. Price and unit basis may support a match but must
> not override clearly poor semantics. Add separate deterministic rules for
> daily caps, bundles, exclusion windows, threshold and weekend premiums,
> cumulative volume discounts, cross-invoice duplicates, unit-basis mismatch,
> and unit-price mismatch. Apply percentage calculations using Decimal with
> half-up rounding. Evaluate each change by category on Hospital 1 and retain
> conservative uncertainty for unknown services. Never hard-code labelled
> invoice IDs or their expected totals.

## Iterations

- Added rate-table extraction and abbreviation-aware service matching.
- Added contract rules one family at a time and reran category evaluation.
- Replaced naïve duplicated-line aggregation with canonical-line selection.
- Kept daily-cap total disagreements visible instead of adding invoice-specific
  corrections.

## Result and next iteration

The final Hospital 1 development result reached 58 true positives, 0 false
positives, and 0 false negatives at invoice level. Category evaluation still
showed one missed unknown service and two overlapping date-category false
positives. Exact corrected totals matched 93.1% of erroneous invoices, so these
limitations were recorded rather than hidden.
