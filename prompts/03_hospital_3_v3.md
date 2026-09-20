# Prompt Version 3 — Hospital 3 Generalisation

## Goal

Apply the approach to an unlabelled hospital whose contract is split across a
base agreement, rate appendix, and amendment.

## Prompt

> Implement Hospital 3 without using Hospital 1 labels as hidden truth. Parse
> the base agreement, Appendix B, and Amendment No. 1 together. Preserve the
> amendment effective date, amended rates, and newly available services so a
> service billed before availability is detected separately. Extract and
> validate base rates, unit bases, caps, threshold premiums, weekend uplifts,
> volume discounts, bundles, and exclusion windows. Reuse the common matcher,
> but manually review low-confidence and price-mismatch lines before changing
> its thresholds. Generate one prediction for every unique invoice, retain
> integer cents, and lower confidence when service identity or corrected total
> is uncertain.

## Iterations

- Parsed 120 services, including seven amended services and two newly added
  services.
- Added effective-date checks and contract-specific rule ordering.
- Reviewed the rate-mismatch report rather than treating every difference as a
  true error automatically.
- Tightened semantic matching after the initial unknown-service count was too
  broad, then regression-tested Hospital 1.

## Result and limitation

The final Hospital 3 output contains 932 invoices, with 86 flagged (9.227%).
Thirteen invoices are classified as unknown-service cases. Because Hospital 3
is unlabelled, these are audit predictions, not measured accuracy claims.
