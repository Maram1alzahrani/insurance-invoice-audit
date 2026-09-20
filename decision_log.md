# Decision Log

## Scope and sequencing

I used Hospital 1 as the labelled development set, then implemented full
contract-aware audits for Hospitals 3 and 4. I selected these two because they
exercise different contract structures: Hospital 3 combines a base agreement,
rate appendix, and amendment with effective dates, while Hospital 4 expresses
conditional reimbursement rules in a single agreement. This provided broader
coverage of parsing and rule interactions within the exercise's time budget.
Hospitals 2 and 5 were not implemented. Given more time, I would process them
using the same staged workflow: contract extraction, extraction validation,
service matching, rule evaluation, manual review, and submission validation.

## Assumptions and decisions

| Issue | Decision |
|---|---|
| Duplicate invoice IDs | Flag the invoice ID as erroneous and treat the last invoice row as the canonical claim, matching the one-row-per-ID label and submission format. Canonical line selection prevents duplicated records from inflating corrected totals. |
| Money and rounding | Keep every monetary value as integer cents. Apply contract percentages using `Decimal` and round half up after the applicable step; do not use binary floating-point amounts. |
| Hospital 3 amendment | Apply amended rates and newly added services only from their stated effective date. A service billed before its availability date is flagged separately. |
| Free-text descriptions | Normalize case, punctuation, reference suffixes, and common abbreviations, then fuzzy-match against contracted service names. Price and unit basis are secondary identity signals, not replacements for semantic similarity. |
| Uncertain service identity | If textual confidence is low and the billed price or unit does not support the proposed match, classify the line as `unknown_service` rather than confidently assigning a contractual rate. Keep its arithmetic amount when an expected contractual amount cannot be justified. |
| Multiple errors on one invoice | Preserve all supported categories in a pipe-separated, sorted field. The invoice is flagged once even when several categories apply. |
| Date overlaps | Record malformed dates, dates outside the contract term, and services after the invoice date as separate factual checks. These conditions may overlap even if the development labels record only one primary category. |
| Cross-invoice duplicates | Require the same patient and an exact line signature. Flag the copied occurrence only when another occurrence falls within the patient's genuine admission-to-discharge window. This avoids flagging legitimate repeated services. |
| Daily caps | Evaluate quantity by patient, service, and service date. Flag clear excess quantities. Hospital 1 showed that exact corrected totals can remain ambiguous when caps interact with other adjustments, so confidence is lower where the total cannot be reconstructed exactly. |
| Rule ordering | Follow the ordering stated in each contract. Bundle substitution is evaluated before applicable premiums or cumulative discounts when the contract specifies that sequence. |
| Confidence | Confidence values are conservative rule-based judgments, not trained probabilities. Deterministic arithmetic and contract-number checks receive higher confidence than fuzzy matches or ambiguous total reconstruction. |

## Ambiguities and unresolved limitations

1. A short description can be a lexical subset of a longer contracted service
   and receive a misleadingly high fuzzy score. I require supporting unit or
   price evidence where possible and otherwise flag uncertainty.
2. Development labels sometimes use a primary category where two factual date
   violations are simultaneously true. I retained the factual categories and
   documented the category-level difference rather than tuning it away.
3. Four Hospital 1 daily-cap invoices were detected correctly but did not match
   the labelled corrected total exactly. I did not hard-code invoice-specific
   corrections because that would overfit the development set.
4. Hospitals 3 and 4 have no ground-truth labels. I reviewed low-confidence and
   rate-mismatch cases manually, but their reported accuracy cannot be measured
   directly.

## Final submission decision

The final `submission.csv` contains every unique invoice from Hospitals 3 and
4: 1,767 rows in total, of which 150 are flagged. Hospital 1 is reported only
in the evaluation document and is excluded from the submission. The repository
also retains intermediate review reports so that uncertain decisions can be
audited, while the final submission is generated reproducibly by
`src/invoice_audit/build_submission.py`.
