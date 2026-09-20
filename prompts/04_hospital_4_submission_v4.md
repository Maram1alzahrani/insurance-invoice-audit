# Prompt Version 4 — Hospital 4 and Final Submission

## Goal

Audit a second unlabelled hospital, review uncertain cases, and build a fully
validated submission covering Hospitals 3 and 4.

## Prompt

> Parse Hospital 4's conditional reimbursement agreement and implement its
> stated calculation order. Validate extraction counts for 98 services, 18
> daily caps, 18 threshold premiums, seven bundle pairs, three volume-discount
> services with four thresholds, and 15 exclusion windows. There are no weekend
> uplifts. Generate service matches and contract-aware predictions for every
> unique Hospital 4 invoice. Export a review file containing reliable rate
> mismatches and suspected unknown services. Inspect semantic mismatches before
> changing thresholds, then regression-test Hospital 1 and Hospital 3. Finally,
> combine Hospital 3 and Hospital 4 outputs into `submission.csv` and validate
> exact columns, complete invoice coverage, unique IDs, binary flags, integer
> cents, non-empty categories for flagged rows, and confidence values between
> zero and one.

## Iterations

- Initial Hospital 4 output contained 30 contract-rate mismatch invoices.
- Manual review found one low-confidence semantic mismatch that should be
  treated as an unknown service rather than a contracted-rate error.
- Updated the shared unknown-service rule and reran Hospitals 1, 3, and 4.
- Hospital 1 and 3 results remained stable; Hospital 4 contract-rate mismatches
  decreased from 30 to 29 without changing total flagged invoices.

## Result and final checks

Hospital 4 contains 835 invoices, with 64 flagged (7.665%). The combined
submission contains 1,767 unique invoices from Hospitals 3 and 4, including
150 flagged invoices. Automated validation passed before writing the final CSV.
