# Project-Adapted PFE Report Specification Template

Status: reusable project-adaptation template. Replace every placeholder with
confirmed target-project information.

## Purpose and Instructions

Use this file after the general report conventions are approved and enough
project evidence exists to create a project-adapted writing specification. It
bridges generic academic rules and the verified facts of `<PROJECT_NAME>`.

Complete it by inspecting `<REPOSITORY_PATH>`, approved project documentation,
stakeholder-provided context, and dated validation evidence. Remove sections
that are genuinely inapplicable, but preserve the academic separation of
context, requirements, architecture, implementation, validation, limitations,
and conclusion.

Rules that remain mandatory:

- Never invent missing project facts; retain `TODO:` placeholders.
- Keep implemented mechanisms separate from captured runtime results.
- Never describe unexecuted checks as passed.
- Make technical and academic claims traceable to evidence or citations.
- Remove secrets, private data, environment identifiers, and unnecessary
  personal information from shared material.

## Purpose and Scope

- Working title: `<PROJECT_WORKING_TITLE>`.
- Official title: `<OFFICIAL_PROJECT_TITLE>`.
- Institution and program: `<INSTITUTION_AND_PROGRAM>`.
- Host organization or project setting: `<HOST_ORGANIZATION_OR_SETTING>`.
- Report language: `<REPORT_LANGUAGE>`.
- Required abstract languages: `<ABSTRACT_LANGUAGES>`.
- Academic period: `<ACADEMIC_PERIOD>`.
- Confidentiality constraints: `<DISCLOSURE_RULES>`.

The report should present `<PROJECT_NAME>` as `<ONE_SENTENCE_PROJECT_TYPE_AND_CONTRIBUTION>`.
Its scope includes `<IN_SCOPE_SUMMARY>` and excludes `<OUT_OF_SCOPE_SUMMARY>`.

## Evidence Sources Read

List only sources actually inspected.

| Source | Revision or date | Intended report use | Reliability notes |
| --- | --- | --- | --- |
| `<SOURCE_PATH_OR_DOCUMENT>` | `<REVISION_OR_DATE>` | `<CHAPTER_OR_CLAIM>` | `<AUTHORITATIVE_CURRENT_OR_LEGACY>` |
| `<SOURCE_PATH_OR_DOCUMENT>` | `<REVISION_OR_DATE>` | `<CHAPTER_OR_CLAIM>` | `<AUTHORITATIVE_CURRENT_OR_LEGACY>` |
| `<STAKEHOLDER_APPROVAL_OR_INTERVIEW>` | `<DATE>` | `<CONTEXT_OR_REQUIREMENT>` | `<APPROVAL_SCOPE>` |
| `<VALIDATION_SUMMARY>` | `<DATE>` | Validation chapter | `<CAPTURED_SCOPE_AND_LIMITS>` |

Record conflicts between documentation and implementation. Prefer the approved
source of truth and disclose unresolved discrepancies.

## Project Evidence Findings

### Product and Problem

- Project name: `<PROJECT_NAME>`.
- Product or system category: `<PROJECT_CATEGORY>`.
- Target users or beneficiaries: `<TARGET_USERS>`.
- Existing situation: `<EXISTING_SITUATION>`.
- Problem statement: `<PROBLEM_STATEMENT>`.
- Proposed contribution: `<PROPOSED_CONTRIBUTION>`.
- Expected value: `<EXPECTED_VALUE>`.
- Main constraints: `<CONSTRAINTS>`.
- Known exclusions: `<OUT_OF_SCOPE_ITEMS>`.

Avoid promotional language. State the problem and contribution in measurable or
observable terms where possible.

### Functional Scope

| Functional area | Confirmed behavior | Primary actors | Evidence source |
| --- | --- | --- | --- |
| `<FUNCTIONAL_AREA>` | `<CONFIRMED_BEHAVIOR>` | `<ACTORS>` | `<SOURCE>` |
| `<FUNCTIONAL_AREA>` | `<CONFIRMED_BEHAVIOR>` | `<ACTORS>` | `<SOURCE>` |

For each area, identify relevant requirements, error behavior, authorization,
data effects, and acceptance criteria. Do not infer features merely from UI
labels or planned tickets.

### Architecture and Stack

Describe capabilities first and verified technologies second.

| Capability | Responsibility | Verified implementation | Evidence |
| --- | --- | --- | --- |
| User-facing client | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_TODO>` | `<SOURCE>` |
| Application or API service | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_TODO>` | `<SOURCE>` |
| Authoritative data store | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_TODO>` | `<SOURCE>` |
| Supporting data or messaging service | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_NOT_APPLICABLE>` | `<SOURCE>` |
| Identity and access service | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_TODO>` | `<SOURCE>` |
| Runtime or orchestration layer | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_NOT_APPLICABLE>` | `<SOURCE>` |
| Observability capability | `<RESPONSIBILITY>` | `<TECHNOLOGY_AND_VERSION_OR_TODO>` | `<SOURCE>` |

Principal interaction:

```text
<ACTOR_OR_CLIENT>
  -> <ENTRYPOINT_OR_INTERFACE>
  -> <APPLICATION_COMPONENT>
  -> <DATA_OR_EXTERNAL_DEPENDENCIES>
  -> <ASYNC_OR_RUNTIME_COMPONENT_IF_APPLICABLE>
  -> <STATUS_OR_RESULT_PATH>
```

Record exact versions only from manifests, lock files, runtime metadata, or
another authoritative source, with a revision or evidence date.

### Infrastructure and Deployment

- Hosting or deployment model: `<DEPLOYMENT_MODEL>`.
- Environments: `<ENVIRONMENT_STRATEGY>`.
- Packaging or containerization: `<PACKAGING_MODEL>`.
- Orchestration or runtime platform: `<ORCHESTRATION_MODEL_OR_NOT_APPLICABLE>`.
- Networking and ingress: `<NETWORKING_MODEL>`.
- Configuration management: `<CONFIGURATION_MODEL>`.
- Secret management: `<SECRET_MANAGEMENT_MODEL>`.
- Persistent storage: `<PERSISTENCE_MODEL>`.
- Scaling and resilience: `<IMPLEMENTED_BEHAVIOR_AND_UNTESTED_LIMITS>`.
- Backup and recovery: `<IMPLEMENTED_BEHAVIOR_OR_TODO>`.

Do not treat a development environment as production-grade without evidence.

### Delivery and DevOps Evidence

- Source-control workflow: `<SOURCE_CONTROL_WORKFLOW>`.
- Continuous-integration platform: `<CI_CAPABILITY_AND_IMPLEMENTATION>`.
- Build and artifact flow: `<BUILD_AND_ARTIFACT_FLOW>`.
- Deployment or promotion flow: `<DEPLOYMENT_PROMOTION_FLOW>`.
- Rollback strategy: `<ROLLBACK_IMPLEMENTATION_OR_TODO>`.
- Quality gates: `<EXECUTED_OR_IMPLEMENTED_GATES>`.
- Reproducible commands: `<VALIDATION_COMMANDS_OR_PROCEDURES>`.

For every gate, state whether it is configured, executed, mandatory, and backed
by dated evidence.

### Security Findings

- Authentication: `<AUTHENTICATION_MODEL>`.
- Authorization: `<AUTHORIZATION_MODEL>`.
- Trust boundaries: `<TRUST_BOUNDARIES>`.
- Data protection: `<DATA_PROTECTION_CONTROLS>`.
- Secret handling: `<SECRET_HANDLING>`.
- Dependency or source scanning: `<SCANNING_CONTROLS_OR_TODO>`.
- Runtime or infrastructure security: `<RUNTIME_CONTROLS_OR_TODO>`.
- Auditability: `<AUDIT_LOGGING_OR_TODO>`.
- Known limitations: `<SECURITY_LIMITATIONS>`.

A control's presence does not prove complete security. State exactly what was
tested and what remains outside the assessment.

### Observability Findings

- Metrics: `<METRICS_IMPLEMENTATION_OR_TODO>`.
- Logs: `<LOGGING_IMPLEMENTATION_OR_TODO>`.
- Traces: `<TRACING_IMPLEMENTATION_OR_TODO>`.
- Dashboards: `<DASHBOARD_IMPLEMENTATION_OR_TODO>`.
- Alerts and notifications: `<ALERTING_IMPLEMENTATION_OR_TODO>`.
- Health checks: `<HEALTH_CHECK_IMPLEMENTATION_OR_TODO>`.
- Operational ownership: `<RESPONSIBILITY_MODEL_OR_TODO>`.

Do not claim end-to-end observability when only one signal type or component is
covered.

### Testing and Validation Findings

| Validation area | Method | Evidence state | Result and limitation |
| --- | --- | --- | --- |
| Build | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Static analysis | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Unit tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Integration tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| End-to-end tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Security tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Performance tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Resilience tests | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |
| Deployment readiness | `<METHOD>` | `<STATE>` | `<RESULT_AND_LIMITATION>` |

Allowed evidence states are `Captured pass`, `Captured failure`,
`Implementation confirmed; execution not captured`, `Planned`, and
`Not applicable with justification`.

### UI and Design Evidence

| User goal | View or workflow | Evidence asset | Redaction status | Chapter use |
| --- | --- | --- | --- | --- |
| `<USER_GOAL>` | `<VIEW_OR_WORKFLOW>` | `<ASSET_OR_TODO>` | `<STATUS>` | `<PLACEMENT>` |

Screenshots must demonstrate behavior described in the text. Record accessibility
or responsive-design evidence only when it was evaluated.

## What Must Not Be Included

- Facts, prose, assets, results, bibliography, or technical decisions inherited
  from another project report.
- Secrets, credentials, tokens, private keys, session data, or unredacted
  configuration.
- Private repository coordinates, internal hostnames, personal identifiers, or
  organization information beyond the approved disclosure scope.
- Exact versions, metrics, performance claims, availability claims, or security
  assurances that lack evidence.
- Planned or unexecuted work presented as completed or passed.
- Debug output, unstable screenshots, or code extracts without academic value.
- Generated claims that cannot be traced to a source or citation.

## Recommended Report Structure for This Project

### Front Matter

- Institution-required cover and metadata.
- Dedication and acknowledgements if allowed.
- Abstracts in `<ABSTRACT_LANGUAGES>` and keywords.
- Contents, figures, tables, acronyms, and glossary as required.

### Chapter 1: General Context and Project Framing

Purpose: establish why `<PROJECT_NAME>` exists.

- Host or project context.
- Existing situation and limitations.
- Problem statement.
- Proposed contribution.
- Objectives and deliverables.
- Scope and exclusions.
- Management method, plan, risks, and constraints.

Required evidence: `<APPROVED_CONTEXT_SOURCES_AND_PLANNING_EVIDENCE>`.

### Chapter 2: Requirements Analysis

Purpose: define what the solution must satisfy.

- Stakeholders, actors, and role boundaries.
- Functional requirements.
- Measurable non-functional requirements.
- Use cases, user stories, or workflow descriptions.
- Acceptance criteria and prioritization.
- Requirements-to-implementation-and-test traceability.

Required evidence: `<REQUIREMENT_SOURCES_AND_APPROVALS>`.

### Chapter 3: Architecture and Design

Purpose: explain how and why the system is designed.

- Context and external dependencies.
- Logical/component architecture.
- Data model and flows.
- Principal dynamic sequences.
- Interfaces and contracts.
- Deployment architecture.
- Security and trust boundaries.
- Technology and architecture decisions with alternatives.

Required evidence: `<ARCHITECTURE_SOURCES_DIAGRAMS_AND_DECISIONS>`.

### Chapter 4: Implementation

Purpose: document what was built and the important engineering work.

- Organization by `<FEATURE_SUBSYSTEM_WORK_PACKAGE_OR_CONFIRMED_INCREMENT_MODEL>`.
- Implemented requirements and module boundaries.
- Important algorithms, contracts, schemas, or user flows.
- Infrastructure and delivery implementation where relevant.
- Security controls and integration points.
- Challenges, decisions, evidence, and limitations.

Required evidence: `<SOURCE_MODULES_CHANGE_HISTORY_ISSUES_AND_SCREENSHOTS>`.

### Chapter 5: Validation, Delivery, and Operations

Purpose: demonstrate validated behavior and operational readiness.

- Test strategy, environments, and reproducibility.
- Build, static analysis, and test results.
- Artifact, delivery, deployment, and rollback evidence.
- Security, performance, resilience, and recovery validation where executed.
- Metrics, logs, traces, dashboards, alerts, and operational procedures.
- Captured failures, gaps, limitations, and future validation.

Required evidence: `<DATED_VALIDATION_SUMMARIES_AND_REDACTED_ASSETS>`.

### General Conclusion

- Evaluate each principal objective.
- Summarize demonstrated contributions and results.
- State limitations and lessons.
- Present feasible future work.
- Introduce no new claim or evidence.

## Report Generation Guidance for This Project

- Use the refined reusable specification for academic rules and this file for
  confirmed project adaptation.
- Prefer direct evidence from the current source revision over stale planning docs.
- Resolve conflicts explicitly and record the chosen source of truth.
- Write responsibilities and decisions before listing tools.
- Introduce and analyze every significant figure, table, screenshot, and listing.
- Keep TODOs visible until evidence or approval closes them.
- Separate design intent, implemented state, executed validation, and future work.
- Use consistent terminology from the approved glossary.

## Recommended LaTeX Organization

Use the official template when mandated. Otherwise prefer:

```text
report/
  main.tex
  bibliography.bib
  config/
  frontmatter/
  chapters/
  appendices/
  assets/
  diagrams/
  template/
```

Keep metadata, packages, commands, chapter prose, appendices, assets, and
editable diagram sources separated. Keep generated build artifacts out of the
source package.

## Naming Conventions

- Use lowercase ASCII filenames with underscores.
- Use stable labels prefixed by `chap:`, `sec:`, `fig:`, `tab:`, `lst:`,
  `eq:`, and `app:`.
- Name evidence files by subject and, for validation campaigns, an unambiguous
  date in the chosen project convention.
- Do not embed usernames, workstation paths, environment-specific identifiers,
  or private repository names in shareable asset names.
- Use verified, descriptive bibliography keys.

## Diagram Strategy for `<PROJECT_NAME>`

| Diagram | Purpose | Evidence source | Status |
| --- | --- | --- | --- |
| System context | Show boundary, actors, and external systems. | `<SOURCE>` | `<STATUS>` |
| Logical/component view | Show responsibilities and interfaces. | `<SOURCE>` | `<STATUS>` |
| Deployment view | Show environments, runtime units, networking, and data services. | `<SOURCE>` | `<STATUS>` |
| Domain or data model | Show important entities and relationships. | `<SOURCE>` | `<STATUS>` |
| Principal sequence | Explain `<IMPORTANT_FLOW>`. | `<SOURCE>` | `<STATUS>` |
| Security view | Show identity, authorization, secrets, and trust boundaries. | `<SOURCE>` | `<STATUS>` |
| Delivery flow | Show build, validation, release, deployment, and rollback. | `<SOURCE>` | `<STATUS>` |
| Observability view | Show telemetry sources, processing, storage, and consumers. | `<SOURCE>` | `<STATUS>` |

Retain editable sources, export readable vector diagrams where possible, and
remove diagrams that do not add explanatory value.

## Figure, Table, Listing, and Screenshot Standards

- Every artifact has a descriptive caption, stable label, source or provenance,
  report reference, and explanatory text.
- Tables are preferred for requirements, risks, decisions, comparisons,
  interfaces, tests, and traceability.
- Code or configuration excerpts remain short, relevant, and redacted.
- Screenshots come only from the target project and show stable states.
- No artifact may expose confidential data, credentials, private addresses,
  personal data, or unnecessary raw identifiers.
- Visuals must remain readable at final PDF size and in print.

## Bibliography and Citation Standards

- Follow `<REQUIRED_CITATION_STYLE>`.
- Prefer primary documentation, standards, RFCs, peer-reviewed work, and
  recognized engineering books.
- Cite technology decisions, security controls, architectural patterns, and
  external definitions.
- Independently consult and verify each source.
- Record access dates when required.
- Confirm every citation key resolves and every bibliography entry is used or
  intentionally retained.

## Compilation and Reproducibility Workflow

- Primary build command: `<LATEX_BUILD_COMMAND>`.
- TeX distribution/version: `<TEX_DISTRIBUTION_AND_VERSION>`.
- Bibliography processor: `<BIBLIOGRAPHY_PROCESSOR>`.
- External diagram or conversion requirements: `<EXTERNAL_TOOLS_OR_NONE>`.
- Template revision: `<TEMPLATE_REVISION>`.
- Special security-relevant flags: `<FLAGS_AND_JUSTIFICATION_OR_NONE>`.

Perform a clean build and resolve compilation errors, undefined references,
missing citations, broken assets, unreadable visuals, and unacceptable overflow
warnings before submission.

## Remaining Missing Inputs

- `TODO: confirm official metadata and disclosure permissions`
- `TODO: confirm problem statement, objectives, scope, and contributions`
- `TODO: approve requirements and acceptance criteria`
- `TODO: verify architecture and technology versions from authoritative sources`
- `TODO: complete decision records and diagram inventory`
- `TODO: collect approved screenshots and redact them`
- `TODO: capture dated validation results and limitations`
- `TODO: confirm operational, security, and future-work claims`
- `TODO: confirm template, language, bibliography, and submission requirements`

## Quality Checklist Before Chapter Generation

- All project facts are confirmed or visibly marked TODO.
- Evidence sources record their revision or date.
- Requirements trace to implementation and validation.
- Architecture decisions include alternatives and criteria.
- Implemented mechanisms are not confused with successful executions.
- Validation statuses use the approved evidence vocabulary.
- Quantitative results include environment, procedure, date, and limitations.
- Figures, tables, screenshots, and listings add evidence and are referenced.
- Secrets, private data, internal identifiers, and personal data are absent.
- Citations are authoritative and independently verified.
- Chapter introductions, conclusions, terminology, and transitions are coherent.
- Known gaps and untested claims appear in limitations or future work.

## Final Rule

This project-adapted specification governs the report only after every retained
project statement has been verified for `<PROJECT_NAME>`. The reusable academic
conventions govern structure and quality; institutional rules take precedence;
and no other project's facts, environment, examples, assets, results, or
technical decisions may be carried into the report.
