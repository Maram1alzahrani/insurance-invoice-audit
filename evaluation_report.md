# Hospital 1 Development-Set Evaluation

## Scope

Hospital 1 was used as the labelled development set. The audit pipeline combines
deterministic integrity checks, contract-rule evaluation, and fuzzy service-name
matching. Evaluation is performed on the 913 unique invoice IDs represented in
the labels. Hospital 1 is not included in the final submission.

Hospitals 2–5 are unlabelled and are included in the final submission. Their
outputs are validated through contract-rule checks, manual review of uncertain
matches, aggregate-rule audits, and automated tests, but their predictive
accuracy cannot be measured directly.

## Invoice-level performance

| Metric | Value |
|---|---:|
| True positives | 58 |
| False positives | 0 |
| False negatives | 0 |
| True negatives | 855 |
| Precision | 1.000 |
| Recall | 1.000 |
| F1 | 1.000 |

This result is a development-set result, not an unbiased estimate of performance
on unseen hospitals. Hospital 1 labels were used while iterating on rules and
matching thresholds, so the invoice-level score is expected to be optimistic.

## Per-category performance

An invoice may contain more than one error category. Category-level false
positives therefore do not necessarily create invoice-level false positives.

| Error category | Detected / actual | Recall | Category false positives |
|---|---:|---:|---:|
| `bundle_not_applied` | 5 / 5 | 1.000 | 0 |
| `contract_number_mismatch` | 5 / 5 | 1.000 | 0 |
| `cross_invoice_duplicate` | 4 / 4 | 1.000 | 0 |
| `daily_cap_exceeded` | 4 / 4 | 1.000 | 0 |
| `duplicate_invoice_id` | 5 / 5 | 1.000 | 0 |
| `exclusion_window_violation` | 4 / 4 | 1.000 | 0 |
| `invoice_total_mismatch` | 6 / 6 | 1.000 | 0 |
| `line_total_arithmetic` | 6 / 6 | 1.000 | 0 |
| `malformed_service_date` | 6 / 6 | 1.000 | 0 |
| `premium_incorrectly_applied` | 6 / 6 | 1.000 | 0 |
| `premium_omitted` | 3 / 3 | 1.000 | 0 |
| `service_date_after_invoice_date` | 5 / 5 | 1.000 | 2 |
| `service_date_out_of_window` | 5 / 5 | 1.000 | 0 |
| `unit_price_mismatch` | 10 / 10 | 1.000 | 0 |
| `unknown_service` | 11 / 12 | 0.917 | 0 |
| `volume_discount_incorrectly_applied` | 4 / 4 | 1.000 | 0 |
| `volume_discount_omitted` | 4 / 4 | 1.000 | 0 |
| `wrong_unit_basis` | 11 / 11 | 1.000 | 0 |

## Expected-total accuracy

| Measure | Value |
|---|---:|
| Exact total agreement across all invoices | 99.6% |
| Exact total agreement on erroneous invoices | 93.1% |
| MAE on erroneous invoices | 5,249.57 cents |

The four remaining total disagreements all involve daily-cap corrections:

| Invoice | Prediction minus labelled total (cents) |
|---|---:|
| `INV-H1-000015` | +14,775 |
| `INV-H1-000049` | +25,425 |
| `INV-H1-000227` | +76,275 |
| `INV-H1-000725` | +188,000 |

The invoices are correctly flagged, but their corrected totals remain too high.
This indicates that detecting a cap violation is easier than reconstructing the
label's exact interpretation of how excess units and interacting adjustments
should be removed.

## Unlabelled-hospital validation

The final submission includes every unique invoice from Hospitals 2–5:

| Hospital | Invoices | Flagged | Flag rate |
|---|---:|---:|---:|
| Hospital 2 | 1,125 | 76 | 6.756% |
| Hospital 3 | 932 | 70 | 7.511% |
| Hospital 4 | 835 | 64 | 7.665% |
| Hospital 5 | 1,050 | 76 | 7.238% |
| **Total** | **3,942** | **286** | **7.255%** |

These rates are descriptive outputs, not estimates of accuracy. Validation on
the unlabelled hospitals included:

- Manual inspection of unknown-service and low-confidence rate-mismatch cases.
- Verification of service identity using description, unit basis, valid base
  rates, amendment rates, bundle rates, and contextual rates where applicable.
- Independent comparison of aggregate rules against all line items.
- Submission validation for coverage, uniqueness, schema, integer cents,
  categories, flags, confidence ranges, and ordering.
- A regression suite containing 17 passing tests.

The independent aggregate-rule audits for Hospitals 2, 3, and 5 produced zero
differences for threshold premiums, bundled services, daily caps, exclusion
windows, and cumulative volume discounts.

Hospital 3 initially produced 86 flagged invoices. Correcting cumulative
utilisation to include all prior service lines across the contract term removed
16 flags whose recalculated expected totals matched their billed totals. The
revised output contains 70 flagged invoices.

## Error analysis by failure type

### 1. Partial-description matches can look falsely exact

Token-set similarity is robust to abbreviations and word order, but it can give
an overconfident match when a short description is a subset of a longer service
name. For example, line `H1-L00236-03` on `INV-H1-000236` has the description
`Fract Outpatient Radiotherapy`. It received a perfect text score against a
more specific contracted radiotherapy service even though its billed unit and
price did not agree. As a result, one `unknown_service` category was missed.

Mitigation: combine text similarity with price, unit-basis, and match-margin
signals, and lower confidence when the description omits clinically meaningful
specialty terms.

### 2. Logically overlapping date errors may not match the label taxonomy

A service outside the contract term can also occur after the invoice date. The
engine reports both facts, while the labels may record only the primary error.
For example, `INV-H1-000852` contains a service dated `2026-07-01`, after both
the invoice date and the contract end. This creates a category-level false
positive for `service_date_after_invoice_date`, although the invoice itself is
correctly flagged. The same overlap occurs for `INV-H1-000179`.

Mitigation: preserve all factual reasons internally, but define a documented
category-precedence policy when a single reporting label is required.

### 3. Daily-cap detection and total reconstruction are separate problems

The pipeline detects every labelled daily-cap violation, but exact total
reconstruction fails on four invoices. `INV-H1-000725`, for example, is flagged
correctly while its predicted corrected total is 188,000 cents above the
labelled value.

Mitigation: represent caps as explicit allocation rules at the patient,
service, and service-date level, then test their interaction with premiums,
discounts, bundles, and duplicated lines independently.

### 4. Development-set reuse makes the headline score optimistic

The same labelled hospital was used to refine parsing logic, rule ordering, and
matching thresholds. A perfect invoice-level F1 therefore demonstrates internal
consistency on Hospital 1 rather than proven generalisation. For example, the
unknown-service thresholds were selected after observing Hospital 1 behaviour;
Hospitals 2–5 have different description styles and no labels.

Mitigation: retain conservative confidence values for unseen hospitals, review
low-confidence matches, and validate against another labelled hospital before
production use.

## Conclusion

The pipeline identifies all erroneous Hospital 1 invoices, with one remaining
category miss and four imperfect corrected totals. The strongest components are
deterministic integrity checks, explicit contract rules, and reproducible
aggregate-rule validation.

The final submission covers all 3,942 unique invoices from Hospitals 2–5. Their
true accuracy remains unknown because labels are unavailable. The main residual
risks are semantic service matching, overlapping category definitions, exact
daily-cap reconstruction, and development-set overfitting.