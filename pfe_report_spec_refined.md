# Refined Reusable PFE Report Specification

Status: governing reusable specification for future report generation.

## Purpose and Instructions

This specification defines how a final-year engineering report should be
organized, evidenced, written, and generated. Replace every angle-bracket
placeholder with confirmed facts from `<PROJECT_NAME>`. Delete optional sections
only after confirming they do not apply.

This file governs report structure, methodology, diagrams, citations,
validation evidence, confidentiality, and reproducibility. An institution's
official submission rules override recommendations here. Missing facts must
remain visible as `TODO:` items and must never be invented.

## 1. Purpose and Scope

Use this specification when producing:

- A LaTeX report scaffold.
- Chapter outlines and prose.
- Evidence, diagram, figure, and table inventories.
- Bibliography and citation rules.
- Validation summaries and traceability matrices.
- Compilation and submission quality checks.

Do not use it as a source of project facts, technical decisions, test results,
screenshots, or bibliography entries. Those must come from the target project.

## 2. Governance Levels

### Mandatory Institutional or Template Constraints

- Use the required document class, template, language, cover, signatures,
  abstract languages, page style, front matter, and bibliography style.
- Respect submission format, page limits, confidentiality, accessibility, and
  archiving requirements.
- Produce a reproducible build and resolve compilation errors before delivery.
- Do not disclose secrets, personal data, restricted project information, or
  unverifiable technical claims.
- Cite external ideas and distinguish them from original project contributions.

### Mandatory Academic Integrity and Evidence Rules

- Every project claim must be supported by inspectable implementation evidence,
  dated validation evidence, approved stakeholder information, or a citation.
- Never copy or lightly paraphrase project content from another report.
- Never classify a skipped or unexecuted validation as passed.
- Distinguish implemented mechanisms, captured results, planned work, and known
  limitations.
- Keep figures, tables, requirements, decisions, and results traceable.

### Recommended Engineering Report Conventions

- Keep sources modular and reviewable.
- Use stable ASCII filenames and descriptive labels.
- Separate context, requirements, design, implementation, validation, and
  conclusion concerns.
- Justify significant design, technology, cloud, DevOps, and security choices
  using alternatives and criteria.
- Prefer precise, measurable language over promotional claims.

### Optional Methodology Patterns

Use these only if they match the real project:

- Scrum or Agile sprint reporting.
- Context, container, component, deployment, dynamic, data, and security views.
- Dedicated cloud, DevOps, security, observability, or evaluation chapters.
- Appendices for large tables, configurations, evidence, and diagrams.

### Project-Specific TODO Placeholders

- `TODO: official project title`
- `TODO: institution and template requirements`
- `TODO: report language and abstract languages`
- `TODO: host organization and disclosure limits`
- `TODO: problem statement and motivation`
- `TODO: objectives, contributions, and scope`
- `TODO: stakeholders, actors, and requirements`
- `TODO: architecture and technology decisions`
- `TODO: delivery, deployment, and operational model`
- `TODO: security and privacy controls`
- `TODO: validation evidence and limitations`
- `TODO: bibliography sources`

## 3. Reuse Boundaries

### What Can Be Reused

- Academic lifecycle and chapter-order concepts.
- Modular LaTeX assembly and metadata separation.
- Figure, table, label, bibliography, and compilation patterns.
- Requirements, architecture-decision, risk, traceability, and test-matrix
  structures.
- The discipline of chapter introductions, conclusions, and transitions.
- Redaction, evidence-state, and reproducibility rules.

### What Must Not Be Reused

- Names, organizations, people, supervisors, dates, academic metadata, or logos.
- Problems, objectives, requirements, backlogs, sprints, use cases, architecture,
  source paths, commands, results, metrics, conclusions, or limitations.
- Screenshots, diagrams, code excerpts, dashboards, PDFs, or cover assets.
- A technology stack or deployment environment as a default.
- Bibliography entries that were not independently consulted and revalidated.
- Claims about performance, availability, scalability, security, compliance,
  delivery, observability, or test success.

### Adaptation Rules

- A modular source layout is preferred, but the mandated template controls.
- Chapter count is adaptable; concern coverage is more important than an exact
  count.
- Sprint-based chapters require evidence that iterative delivery was actually used.
- Caption language and terminology follow the report language and template.
- Listing and diagram tools are choices, not inherited requirements.
- Tool names may be included only when they describe the target project's
  verified implementation or a deliberately selected authoring workflow.

## 4. Recommended Project Structure

```text
report/
  main.tex
  latexmkrc or .latexmkrc
  bibliography.bib
  config/
    metadata.tex
    packages.tex
    commands.tex
  frontmatter/
    dedication.tex
    acknowledgements.tex
    acronyms.tex
    abstract.tex
  chapters/
    chap_01_context.tex
    chap_02_requirements.tex
    chap_03_architecture.tex
    chap_04_implementation.tex
    chap_05_validation_operations.tex
    conclusion.tex
  appendices/
    appendix_a_<TOPIC>.tex
  assets/
    figures/
    screenshots/
    diagrams/
    logos/
  diagrams/
    <EDITABLE_SOURCE_FORMATS>/
  template/
    <INSTITUTIONAL_TEMPLATE_FILES>
```

Adapt paths to the official template. Keep source files, bibliography, diagram
sources, and approved assets under version control. Exclude generated build
artifacts and temporary logs.

## 5. Recommended LaTeX Organization

### Main Entry Point

`main.tex` should select the approved class, load configuration, set graphics
paths, load metadata, and assemble front matter, chapters, bibliography,
appendices, and final pages. Avoid chapter prose and project logic in this file.

### Configuration Files

Centralize:

- Metadata and multilingual abstracts.
- Package imports and compatible options.
- Reusable commands, table columns, captions, and listing styles.
- PDF metadata, hyperlinks, and language configuration.

### Chapter Files

Each file contains one chapter with a brief introduction, coherent numbered
sections, and a conclusion or transition. Introduce a concept once and use
cross-references instead of duplicating it across chapters.

### Template Compatibility

If the official template supplies a class, commands, or fixed layout, treat
them as inherited infrastructure. Change them only when allowed and necessary.
Document any compatibility workaround that affects reproducibility.

## 6. Naming Conventions

### Files and Directories

- Use lowercase ASCII and underscores.
- Chapters: `chap_01_context.tex`.
- Appendices: `appendix_a_<TOPIC>.tex`.
- Diagram sources: `<DESCRIPTIVE_NAME>.<SOURCE_EXTENSION>`.
- Rendered diagrams: `<DESCRIPTIVE_NAME>.pdf`.
- Screenshots: `<FEATURE>_<STATE>.png`.
- Avoid spaces, accents, apostrophes, temporary suffixes, and ambiguous acronyms.

### Labels

- Chapters: `chap:<DESCRIPTIVE_NAME>`
- Sections: `sec:<DESCRIPTIVE_NAME>`
- Figures: `fig:<DESCRIPTIVE_NAME>`
- Tables: `tab:<DESCRIPTIVE_NAME>`
- Listings: `lst:<DESCRIPTIVE_NAME>`
- Equations: `eq:<DESCRIPTIVE_NAME>`
- Appendices: `app:<DESCRIPTIVE_NAME>`

Labels must describe the artifact rather than its position.

### Bibliography Keys

Use stable descriptive keys such as `<TECHNOLOGY>_official_docs`,
`<STANDARD>_<TOPIC>`, or `<AUTHOR>_<SHORT_TITLE>`. Reuse a key only after
independently validating the source.

## 7. Engineering Report Methodology

### Recommended Chapter 1: Context and Project Framing

Purpose: explain why the project exists.

- Host organization or project environment, within disclosure limits.
- Existing situation and stakeholder needs.
- Precise problem statement.
- Proposed contribution and expected value.
- Objectives and deliverables.
- In-scope and out-of-scope boundaries.
- Project method, plan, constraints, and risks.

### Recommended Chapter 2: Requirements Engineering

Purpose: define what the solution must satisfy.

- Stakeholders, actors, and roles.
- Functional requirements grouped by domain.
- Measurable non-functional requirements for relevant quality attributes.
- Use cases, user stories, or workflows.
- Acceptance criteria and prioritization.
- Traceability from requirements to implementation and validation.

Use stable identifiers such as `FR-<AREA>-<NUMBER>` and
`NFR-<QUALITY>-<NUMBER>`.

### Recommended Chapter 3: Architecture and Design

Purpose: explain how and why the system is designed.

- System context and external dependencies.
- Logical, component, and deployment architecture.
- Data model, storage, and principal flows.
- APIs, events, interfaces, and compatibility boundaries.
- Security, privacy, and trust boundaries.
- Configuration, secrets, networking, and environment strategy where relevant.
- Technology and architecture decisions with alternatives and criteria.

Include cloud-native concerns only when they apply: containerization,
orchestration, service discovery, ingress, persistence, scaling, network policy,
backup, recovery, or multi-environment promotion.

### Recommended Chapter 4: Implementation

Purpose: document what was built.

- Modules, packages, or subsystem boundaries.
- Data or schema evolution.
- User-interface implementation where applicable.
- Integration points and contracts.
- Infrastructure or deployment configuration.
- Delivery automation and implemented security controls.
- Significant decisions, challenges, tradeoffs, and lessons.
- Screenshots and excerpts that prove completed work.

Organize by actual sprint/increment only when that method was followed;
otherwise use features, subsystems, or work packages.

### Recommended Chapter 5: Validation and Operations

Purpose: demonstrate what works and how the solution can be operated.

- Test strategy and environment.
- Unit, integration, API, UI, and end-to-end results as applicable.
- CI/CD gates and artifact validation.
- Deployment and promotion workflow.
- Security testing and secret-handling verification.
- Performance, capacity, resilience, rollback, and recovery where tested.
- Metrics, logs, traces, dashboards, and alerts where implemented.
- Dated results, limitations, exclusions, and reproducibility notes.

This chapter may be split if the project has substantial operational scope.

### General Conclusion

Assess achieved objectives, validated results, engineering contributions,
limitations, and future work. Do not introduce new evidence or claims.

## 8. Diagram Strategy

### Recommended Diagram Set

Create only diagrams that clarify a significant relationship:

- Context and system boundary.
- Logical/component architecture.
- Deployment and environment topology.
- Domain or data model.
- Important sequence or state behavior.
- Delivery and rollback workflow.
- Observability data flow.
- Security trust boundaries and access flow.

### Tool Selection

Choose a maintainable, accessible tool appropriate to the diagram type. Keep
editable sources, document required renderers, and prefer vector exports for
architecture diagrams. Use raster images for screenshots. Do not require an
external workspace unless the project deliberately adopts one.

## 9. Figure, Table, Listing, and Screenshot Standards

### Figures

- Give every figure an explanatory purpose, caption, label, and text reference.
- Prefer readable vector diagrams and preserve aspect ratio.
- Avoid decorative or redundant visuals.

### Tables

- Use tables for structured comparisons, requirements, risks, decisions,
  interfaces, tests, deployments, and traceability.
- Use repeated headers for multi-page tables and keep columns within margins.
- Explain important results in prose.

### Code Listings

- Use inline code for short identifiers.
- Use a consistent listing environment for multi-line excerpts.
- Include only material necessary to support the explanation.
- Document special build requirements and redact sensitive values.

### Screenshots

- Use only screenshots from `<PROJECT_NAME>` that add evidence.
- Capture stable states and explain their evidentiary value.
- Redact secrets, private data, internal addresses, usernames, and identifiers.
- Keep originals organized under the selected asset structure.

## 10. Bibliography and Citation Standards

- Prefer official documentation, standards, RFCs, peer-reviewed research, and
  recognized books.
- Cite external definitions, architecture patterns, technology decisions,
  methodology claims, and security guidance.
- Do not cite implementation facts that can be directly evidenced from the project.
- Consult every source independently; do not inherit another report's bibliography.
- Record access dates if required and verify all keys before submission.
- Avoid unsupported vendor marketing as the sole basis of an engineering choice.

## 11. Compilation and Reproducibility Workflow

Document one primary clean-build command using `<LATEX_BUILD_COMMAND>`. Record:

- TeX distribution and relevant version.
- Document class or template revision.
- Bibliography processor and style.
- Diagram renderers, external commands, fonts, and shell-escape requirements.
- Expected generated artifacts and cleanup behavior.

Before delivery, perform a clean build and check for errors, undefined
references, missing citations, missing assets, broken hyperlinks, unreadable
figures, and unacceptable overflow warnings.

## 12. Quality Checklist Before Report Generation

### Scope and Facts

- Official title, institution, organization, supervisors, and dates are confirmed.
- Problem, objectives, contributions, scope, and confidentiality limits are confirmed.
- Project-management claims reflect actual practice.

### Engineering Content

- Requirements and acceptance criteria are defined.
- Architecture and important decisions are evidenced.
- Interfaces, data, deployment, security, and operations are accurately scoped.
- Validation results are dated and distinguish execution from implementation.
- Limitations and untested quality attributes are explicit.

### LaTeX and Assets

- Template, language, front matter, and bibliography rules are confirmed.
- Source and asset names are stable and portable.
- Diagram sources and exports are organized.
- All figures, tables, listings, and appendices are referenced.

### Academic Quality

- Claims are supported by project evidence or citations.
- No content or assets were copied from another project report.
- Confidential and personal data are absent or approved and redacted.
- Terminology, tense, captions, citations, and chapter flow are consistent.
- TODO placeholders remain visible for unresolved facts.

## 13. Open TODOs Before Generating the Actual Report

- `TODO: What official template and languages are required?`
- `TODO: What metadata and approvals may be disclosed?`
- `TODO: What problem, objectives, scope, and contributions are confirmed?`
- `TODO: What requirements and acceptance criteria are approved?`
- `TODO: What architecture and technology stack were actually implemented?`
- `TODO: What delivery and deployment environments were actually used?`
- `TODO: What security, privacy, and operational controls exist?`
- `TODO: What diagrams and screenshots can be safely included?`
- `TODO: What validations ran, when, where, and with what results?`
- `TODO: What limitations and future work must be disclosed?`
- `TODO: What citation style and source-language rules apply?`

## 14. Final Reuse Rule

Generate the report only from confirmed target-project facts, approved evidence,
independently consulted sources, and required institutional rules. Reusable
templates may influence organization and rigor, but never the project's content,
claims, technology decisions, assets, results, or conclusions.
