# Prompt Version 1 — Baseline and Data Quality

## Goal

Create a reproducible Python baseline for the invoice-auditing exercise, using
Hospital 1 only as the labelled development set.

## Prompt

> Help me build this project step by step in VS Code using Python 3.11 and a
> virtual environment. Start by inspecting the invoice and line-item schemas
> and validating data quality. Implement only high-confidence checks first:
> duplicate invoice IDs, wrong contract number, malformed or invalid dates,
> service dates outside the contract term, service dates after the invoice
> date, line arithmetic, and invoice-total arithmetic. Keep all money as integer
> cents. Produce predictions in the provided submission columns and report
> precision, recall, F1, and per-category results against Hospital 1 labels.
> Do not use invoice-specific exceptions, and explain each file and command
> clearly before moving to the next step.

## Result and next iteration

The first baseline reached 31 true positives, 0 false positives, and 27 false
negatives (`F1 = 0.697`). The result showed that structural checks were precise
but missed contract-dependent errors. The next prompt therefore focused on
extracting contractual services and adjustments instead of weakening the
baseline thresholds.
