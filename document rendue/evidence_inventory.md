# Project Report Evidence Inventory Template

Status: reusable working template. Replace every angle-bracket placeholder before submission.

## Purpose and Instructions

Use this inventory to map verifiable project evidence to report sections. It is
an evidence-planning document, not final report prose. Replace all placeholders
with facts from the target project and remove rows that do not apply.

Academic rules that remain mandatory:

- Base implementation claims on inspectable project artifacts or dated results.
- Distinguish confirmed, planned, and unavailable evidence.
- Never present an unexecuted check as passed.
- Redact secrets, personal data, private URLs, internal hostnames, and credentials.
- Keep every figure, table, result, and technical claim traceable to a source.

## Evidence Rules

- Treat `<REPOSITORY_PATH>` and approved project documentation as the primary
  sources of implementation truth.
- Record the source revision or evidence date when a project can change during
  report preparation.
- Mark missing screenshots, logs, diagrams, and approvals as `TODO`, not as
  completed evidence.
- Use a previous report only as a structural depth benchmark. Do not copy its
  prose, claims, figures, screenshots, bibliography, or project data.
- Prefer summarized, redacted outputs over raw logs.
- Record limitations and contradictory evidence instead of silently resolving
  them in favor of the desired narrative.

## Architecture Evidence

Add, remove, or rename rows to match the actual system.

| Report use | Evidence source | Confirmed finding | Status |
| --- | --- | --- | --- |
| System context | `<PATH_OR_DOCUMENT>` | `<SYSTEM_BOUNDARY_AND_EXTERNAL_ACTORS>` | `<CONFIRMED_OR_TODO>` |
| User interface or client boundary | `<PATH_OR_DOCUMENT>` | `<CLIENT_RESPONSIBILITIES_AND_INTERFACES>` | `<CONFIRMED_OR_TODO>` |
| Service or backend boundary | `<PATH_OR_DOCUMENT>` | `<SERVICE_RESPONSIBILITIES_AND_INTERFACES>` | `<CONFIRMED_OR_TODO>` |
| Data persistence | `<PATH_OR_DOCUMENT>` | `<AUTHORITATIVE_AND_SUPPORTING_DATA_STORES>` | `<CONFIRMED_OR_TODO>` |
| Authentication and authorization | `<PATH_OR_DOCUMENT>` | `<IDENTITY_AND_ACCESS_CONTROL_MODEL>` | `<CONFIRMED_OR_TODO>` |
| Runtime or orchestration | `<PATH_OR_DOCUMENT>` | `<EXECUTION_OR_ORCHESTRATION_MODEL>` | `<CONFIRMED_OR_TODO>` |
| Deployment | `<PATH_OR_DOCUMENT>` | `<DEPLOYMENT_MODEL>` | `<CONFIRMED_OR_TODO>` |
| Observability | `<PATH_OR_DOCUMENT>` | `<METRICS_LOGS_TRACES_AND_ALERTING_MODEL>` | `<CONFIRMED_OR_TODO>` |
| Security controls | `<PATH_OR_DOCUMENT>` | `<SECURITY_CONTROLS_AND_TRUST_BOUNDARIES>` | `<CONFIRMED_OR_TODO>` |
| Delivery workflow | `<PATH_OR_DOCUMENT>` | `<BUILD_RELEASE_AND_PROMOTION_MODEL>` | `<CONFIRMED_OR_TODO>` |

## Diagram Evidence

Use identifiers meaningful in the target project; do not retain workspace IDs
or links from another environment.

| Diagram | Editable source | Rendered asset | Report placement | Status |
| --- | --- | --- | --- | --- |
| System context | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Architecture chapter | `<STATUS>` |
| Logical or component architecture | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Architecture chapter | `<STATUS>` |
| Deployment view | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Architecture or operations chapter | `<STATUS>` |
| Principal sequence | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Design chapter | `<STATUS>` |
| Data or domain model | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Design chapter | `<STATUS>` |
| Delivery and validation flow | `<DIAGRAM_SOURCE>` | `<RENDERED_ASSET>` | Validation chapter | `<STATUS>` |

Recommended status values are `planned`, `source confirmed`, `exported`, and
`included and referenced`.

## Screenshot Evidence

| Screenshot group | Report use | Planned or included assets | Status |
| --- | --- | --- | --- |
| Primary user workflow | `<CHAPTER_OR_SECTION>` | `<ASSET_NAMES>` | `<STATUS>` |
| Administrative workflow | `<CHAPTER_OR_SECTION>` | `<ASSET_NAMES>` | `<STATUS_OR_NOT_APPLICABLE>` |
| Deployment or delivery | `<CHAPTER_OR_SECTION>` | `<ASSET_NAMES>` | `<STATUS>` |
| Runtime behavior | `<CHAPTER_OR_SECTION>` | `<ASSET_NAMES>` | `<STATUS>` |
| Monitoring or security | `<CHAPTER_OR_SECTION>` | `<ASSET_NAMES>` | `<STATUS>` |

Screenshots support an explanation; they do not independently prove a test pass.

## Validation Evidence Status

| Evidence | Command or source | Evidence state | Report use |
| --- | --- | --- | --- |
| Build verification | `<VALIDATION_COMMAND>` | `<CAPTURED_RESULT_OR_TODO>` | Build quality |
| Static analysis | `<VALIDATION_COMMAND>` | `<CAPTURED_RESULT_OR_TODO>` | Code quality |
| Unit tests | `<VALIDATION_COMMAND>` | `<CAPTURED_RESULT_OR_TODO>` | Functional correctness |
| Integration tests | `<VALIDATION_COMMAND>` | `<CAPTURED_RESULT_OR_TODO>` | Component integration |
| End-to-end tests | `<VALIDATION_COMMAND>` | `<CAPTURED_RESULT_OR_TODO>` | User workflow validation |
| Deployment readiness | `<VALIDATION_COMMAND_OR_SOURCE>` | `<CAPTURED_RESULT_OR_TODO>` | Operability |
| Security validation | `<VALIDATION_COMMAND_OR_SOURCE>` | `<CAPTURED_RESULT_OR_TODO>` | Security assurance |
| Observability validation | `<VALIDATION_COMMAND_OR_SOURCE>` | `<CAPTURED_RESULT_OR_TODO>` | Operational visibility |

Use only these evidence states:

- `Captured pass`: executed, dated, and summarized evidence exists.
- `Captured failure`: executed evidence exists and the failure is disclosed.
- `Implementation confirmed; execution not captured`: mechanism exists, but no
  runtime result is claimed.
- `Planned`: evidence collection has not occurred.
- `Not applicable`: justified outside the project scope.

Do not use “assumed pass.” Unexecuted or unavailable validation must remain
unverified.

## Requirements and Implementation Traceability

| Requirement or increment | Implementation evidence | Validation evidence | Gaps |
| --- | --- | --- | --- |
| `<REQUIREMENT_ID_AND_SUMMARY>` | `<MODULES_OR_ARTIFACTS>` | `<TEST_OR_CAPTURE>` | `<NONE_OR_TODO>` |
| `<REQUIREMENT_ID_AND_SUMMARY>` | `<MODULES_OR_ARTIFACTS>` | `<TEST_OR_CAPTURE>` | `<NONE_OR_TODO>` |

If an iterative method was used, requirement rows may be grouped by sprint or
increment. Otherwise group them by feature, work package, or subsystem.

## Architecture Writing Notes

- Describe responsibilities and interfaces before listing technologies.
- Identify authoritative data stores, supporting infrastructure, and external
  dependencies accurately.
- Separate request-time application behavior from asynchronous or runtime
  orchestration when applicable.
- State important compatibility boundaries, contracts, and trust boundaries.
- Record exact stack versions only after verifying them from manifests or lock
  files, and attach an evidence date or source revision.
- Do not claim performance, scalability, availability, or security outcomes
  without corresponding evidence.

## Implementation Writing Notes

- Link report increments or features to source modules, requirements, and tests.
- Explain significant design decisions and implementation challenges.
- Distinguish implemented behavior from planned, partial, or deprecated behavior.
- Use screenshots and code excerpts selectively and explain what they prove.

## Validation Writing Notes

- Separate build, functional, integration, security, performance, resilience,
  deployment, and observability evidence.
- Report dates, environment description, command or procedure, result summary,
  and limitations for each captured validation.
- Never copy logs containing credentials, tokens, private repository addresses,
  public tunnel values, or identifiable user data.
- Record known gaps honestly and carry them into the limitations section.

