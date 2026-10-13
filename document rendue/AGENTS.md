# Reusable Report Guidance

These files are environment-agnostic templates for planning, writing, and
validating an academic engineering report. Replace angle-bracket placeholders
with confirmed project facts. Institutional requirements override template
recommendations.

## Core Rules

- Never invent project facts, results, citations, or approvals; leave unresolved
  information as `TODO`.
- Support project claims with inspectable artifacts, approved documentation, or
  dated evidence.
- Never describe an unexecuted validation as passed.
- Keep implemented mechanisms distinct from captured results, planned work, and
  known limitations.
- Redact secrets, private addresses, personal data, credentials, and restricted
  identifiers from prose and assets.
- Do not carry another project's content, stack, paths, commands, examples,
  diagrams, screenshots, or bibliography into a new report.

## File Guide

- `pfe_report_spec_refined.md` — Governing academic specification covering
  report structure, integrity, methodology, diagrams, citations, validation,
  reproducibility, and quality checks. Read first for any substantial report task.
- `pfe_report_spec_project_template.md` — Project-adaptation worksheet for
  confirmed scope, evidence, architecture, implementation, validation, and
  chapter content. Use after inspecting the target project and before drafting.
- `pfe_latex_conventions.md` — LaTeX organization, formatting, naming, figures,
  tables, listings, bibliography, diagrams, and compilation. Read for scaffold,
  authoring, formatting, asset, or build tasks.
- `evidence_inventory.md` — Report-wide mapping from claims and requirements to
  architecture sources, diagrams, screenshots, implementation, and validation.
  Use when collecting evidence or checking traceability.
- `validation_evidence_inventory.md` — Detailed inventory for build, CI,
  deployment, functional, security, performance, resilience, and operational
  evidence. Use when planning or auditing the validation chapter.
- `validation_runs/validation_summary_template.md` — Template for one dated,
  revision-specific validation campaign. Copy and complete it only with observed
  results; record failures and skipped checks honestly.
- `report_depth_gap_analysis.md` — Structural comparison against an approved
  rubric or reference report. Use during review to identify missing academic
  depth without copying reference content.

## Task-Based Reading Order

- New report or chapter plan: read `pfe_report_spec_refined.md`, then
  `pfe_report_spec_project_template.md` and `evidence_inventory.md`.
- LaTeX scaffold, formatting, assets, or compilation: read
  `pfe_report_spec_refined.md` and `pfe_latex_conventions.md`.
- Architecture or implementation prose: read the project template and evidence
  inventory, then verify every retained claim against the target project.
- Validation or operations prose: read `validation_evidence_inventory.md`, the
  applicable dated validation summaries, and `evidence_inventory.md`.
- Completeness or quality review: read `pfe_report_spec_refined.md`,
  `report_depth_gap_analysis.md`, and the evidence inventories.

When templates overlap, the refined specification governs academic rules, the
project template governs confirmed project adaptation, and dated evidence
governs claims about executed results.
