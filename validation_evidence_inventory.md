# Project Validation Evidence Inventory Template

Status: reusable working inventory for the validation and operations chapter.

## Purpose and Instructions

Use this file to track validation mechanisms and the evidence actually captured
for `<PROJECT_NAME>`. Replace placeholders, remove irrelevant rows, and add
project-specific categories as needed. This inventory is not final evidence.

A captured result requires a dated execution record. Source code, workflow
configuration, or deployment manifests can prove that a mechanism exists, but
cannot prove that it passed. Unexecuted checks must be marked `Planned` or
`Implementation confirmed; execution not captured`.

## Build and Continuous Integration

| Area | Evidence source | Purpose | Evidence state and result |
| --- | --- | --- | --- |
| `<COMPONENT>` build | `<WORKFLOW_PATH_OR_COMMAND>` | Compile or package the component. | `<STATE>: <RESULT_SUMMARY>` |
| `<COMPONENT>` static analysis | `<WORKFLOW_PATH_OR_COMMAND>` | Check style, types, or defects. | `<STATE>: <RESULT_SUMMARY>` |
| `<COMPONENT>` unit tests | `<WORKFLOW_PATH_OR_COMMAND>` | Validate isolated behavior. | `<STATE>: <RESULT_SUMMARY>` |
| Artifact or image check | `<WORKFLOW_PATH_OR_COMMAND>` | Produce and inspect a deployable artifact. | `<STATE>: <RESULT_SUMMARY>` |

Record the source revision, runtime/tool versions when relevant, date, counts,
and any warnings or exclusions.

## Deployment

| Area | Evidence source or procedure | Purpose | Evidence state and result |
| --- | --- | --- | --- |
| Base infrastructure | `<MANIFEST_PATH_OR_PROCEDURE>` | Provision required infrastructure. | `<STATE>: <RESULT_SUMMARY>` |
| Application deployment | `<DEPLOYMENT_COMMAND_OR_PIPELINE>` | Deploy application components. | `<STATE>: <RESULT_SUMMARY>` |
| Data services | `<DEPLOYMENT_COMMAND_OR_SOURCE>` | Provide persistence or messaging dependencies. | `<STATE>: <RESULT_SUMMARY>` |
| Observability services | `<DEPLOYMENT_COMMAND_OR_SOURCE>` | Provide metrics, logs, traces, dashboards, or alerts. | `<STATE>: <RESULT_SUMMARY>` |
| Security services | `<DEPLOYMENT_COMMAND_OR_SOURCE>` | Provide runtime or infrastructure security controls. | `<STATE>: <RESULT_SUMMARY>` |

Describe the target environment generically in report prose, then state the
specific environment used for each test where reproducibility requires it.

## Functional and Runtime Validation

| Validation | Coverage | Evidence state and result |
| --- | --- | --- |
| `<API_OR_SERVICE_TEST>` | `<ENDPOINTS_AND_BEHAVIORS>` | `<STATE>: <RESULT_SUMMARY>` |
| `<USER_WORKFLOW_TEST>` | `<ACTOR_FLOW_AND_ACCEPTANCE_CRITERIA>` | `<STATE>: <RESULT_SUMMARY>` |
| `<INTEGRATION_TEST>` | `<COMPONENT_INTERACTIONS>` | `<STATE>: <RESULT_SUMMARY>` |
| `<END_TO_END_TEST>` | `<SYSTEM_BOUNDARY_AND_OUTCOME>` | `<STATE>: <RESULT_SUMMARY>` |
| `<FAILURE_OR_RESILIENCE_TEST>` | `<FAILURE_MODE_AND_EXPECTED_RECOVERY>` | `<STATE>: <RESULT_SUMMARY>` |

## Security, Performance, and Operational Validation

| Area | Method | Evidence state and result | Limitation |
| --- | --- | --- | --- |
| Authentication and authorization | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NONE>` |
| Dependency or source scanning | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NONE>` |
| Dynamic or runtime security | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NONE>` |
| Performance or capacity | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NOT_TESTED>` |
| Resilience and recovery | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NOT_TESTED>` |
| Metrics, logs, traces, and alerts | `<METHOD>` | `<STATE>: <RESULT_SUMMARY>` | `<LIMITATION_OR_NONE>` |

Avoid broad assurance claims. A particular scan or successful scenario does not
prove the complete security, scalability, or reliability of the system.

## Curated Visual Evidence

| Area | Included evidence | Report placement | Evidence value |
| --- | --- | --- | --- |
| Core workflow | `<SCREENSHOT_OR_DIAGRAM>` | `<CHAPTER_SECTION>` | `<WHAT_IT_DEMONSTRATES>` |
| Delivery | `<SCREENSHOT_OR_DIAGRAM>` | `<CHAPTER_SECTION>` | `<WHAT_IT_DEMONSTRATES>` |
| Security | `<SCREENSHOT_OR_DIAGRAM>` | `<CHAPTER_SECTION>` | `<WHAT_IT_DEMONSTRATES>` |
| Observability | `<SCREENSHOT_OR_DIAGRAM>` | `<CHAPTER_SECTION>` | `<WHAT_IT_DEMONSTRATES>` |

Visual evidence supports the narrative but does not replace dated command or
procedure results.

## Evidence-State Vocabulary

- `Captured pass`: executed and passed; dated summarized evidence is retained.
- `Captured failure`: executed and failed; impact and follow-up are recorded.
- `Implementation confirmed; execution not captured`: configuration or code was
  inspected, but no runtime outcome is claimed.
- `Planned`: not yet performed.
- `Not applicable`: excluded with a documented scope justification.

## Redaction and Evidence-Handling Rules

- Never include credentials, tokens, session data, private keys, secret values,
  private URLs, internal hostnames, or unnecessary personal identifiers.
- Prefer pass/fail counts and selected redacted excerpts over full terminal logs.
- Preserve enough metadata for reproducibility: `<EVIDENCE_DATE>`, source
  revision, environment description, procedure, and relevant versions.
- Redact configuration and manifest examples before publication.
- Review screenshots for browser history, usernames, paths, notifications,
  repository coordinates, and raw identifiers.
- Store restricted raw evidence outside the shareable report package according
  to the project's data-handling rules.

