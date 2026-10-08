# Reusable PFE LaTeX Conventions

Status: reusable methodology and formatting guide.

## Purpose and Instructions

Use this file when organizing a final-year engineering project report in
LaTeX. Replace angle-bracket placeholders and reconcile every recommendation
with the institution's official template and submission rules.

The academic rules in this guide remain mandatory unless an official rule
overrides them: modular source organization, evidence-backed claims, traceable
figures and tables, authoritative citations, reproducible compilation, and
protection of confidential information. No project-specific prose, result,
asset, or technical choice may be inherited from another report.

## Source Project Shape

Prefer a modular layout such as:

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
  assets/
    figures/
    screenshots/
    diagrams/
    logos/
  diagrams/
    <EDITABLE_DIAGRAM_SOURCES>/
  template/
    <INSTITUTIONAL_TEMPLATE_FILES>
```

If the institution supplies a different structure, preserve that structure and
apply the organizational principles within it.

Roles of the main files:

- `main.tex` orchestrates the document; it should not contain chapter prose.
- The metadata file contains title, author, degree, institution, supervisors,
  host organization, academic year, abstracts, and keywords.
- Package and command files centralize LaTeX configuration.
- Each chapter file contains one chapter with its introduction and conclusion.
- The bibliography file is the authoritative citation database.
- Editable diagram sources are retained alongside rendered report assets.

Generated files are not source conventions. Exclude or clean `.aux`, `.bbl`,
`.bcf`, `.blg`, `.fdb_latexmk`, `.fls`, `.lof`, `.log`, `.lot`, `.mtc*`, `.out`,
`.run.xml`, `.synctex.gz`, `.toc`, and temporary build logs.

## Document Assembly

Select the institution-approved class:

```tex
\documentclass[<CLASS_OPTIONS>]{<INSTITUTIONAL_OR_STANDARD_CLASS>}
```

Recommended assembly order, subject to institutional rules:

1. Load metadata, packages, and custom commands.
2. Enter front matter.
3. Include the required cover, dedication, acknowledgements, abstracts, table
   of contents, lists of figures and tables, and acronym list.
4. Enter main matter.
5. Include the general introduction, numbered chapters, and conclusion.
6. Print the bibliography.
7. Include appendices and any required final abstract or back-cover page.

Use `\input{...}` for modular source composition. Use `\include{...}` only when
its page-breaking and selective-compilation behavior is deliberately desired.

## Formatting Style

- Follow the institution's page size, margins, typeface, line spacing, heading,
  and pagination requirements.
- Keep heading levels semantically consistent; do not skip levels for visual
  effect.
- Each chapter should open with its objective and close with a synthesis or
  transition.
- Define repeated formatting once in configuration rather than locally.
- Use non-breaking spaces or appropriate references for figure, table, section,
  listing, and appendix references.
- Keep terminology, capitalization, abbreviations, and report language
  consistent.
- Avoid manual spacing that compensates for a layout problem elsewhere.

## Recommended Report Methodology

### Front Matter

Include only the items required or academically appropriate:

- Official cover and title page.
- Dedication and acknowledgements.
- Abstracts in `<REQUIRED_LANGUAGES>` with keywords.
- Table of contents.
- Lists of figures and tables.
- Acronyms and glossary where useful.

### General Introduction

Establish the context, problem, motivation, objectives, adopted approach,
principal contribution, report organization, and scope. Do not announce results
that are not later demonstrated.

### Chapter 1 — General Project Context

Cover the host or project environment, existing situation, problem statement,
proposed contribution, objectives, constraints, scope, management method, plan,
and initial risks. All organization and project facts require confirmation.

### Chapter 2 — Requirements Analysis and Specification

Define stakeholders, actors, functional requirements, measurable non-functional
requirements, use cases or user stories, acceptance criteria, scope boundaries,
and traceability to implementation and validation.

### Chapter 3 — Design and Technology Choices

Explain context, logical, component, data, dynamic, security, and deployment
views. Justify significant technology and architecture decisions using criteria,
alternatives, evidence, and citations.

### Implementation Chapters

Organize implementation by actual feature, subsystem, work package, sprint, or
increment. For each unit describe the goal, relevant requirements, design and
implementation, important decisions, difficulties, evidence, and limitations.
Do not force sprint terminology if the project did not use it.

### Validation and Operations

Present test strategy, executed results, CI/CD gates, deployment workflow,
configuration management, security validation, performance or resilience work,
observability, limitations, and reproducibility information. Clearly distinguish
implemented mechanisms from captured successful executions.

### General Conclusion

Assess objectives, summarize contributions and validated outcomes, disclose
limitations, and present realistic future work. Introduce no new technical
claim.

### Annexes

Use appendices for supporting material that is referenced from the main report
but would interrupt its flow: extended tables, selected configuration, API
inventories, test matrices, supplemental diagrams, or redacted evidence.

## Naming Conventions

Use lowercase ASCII names with underscores for new source and asset files.

- Chapters: `chap_01_context.tex`
- Appendices: `appendix_a_test_matrix.tex`
- Diagrams: `deployment_view.<SOURCE_EXTENSION>`
- Rendered figures: `deployment_view.pdf`
- Screenshots: `dashboard_overview.png`

Use stable descriptive labels:

- `chap:context`
- `sec:security_architecture`
- `fig:deployment_view`
- `tab:requirements_traceability`
- `lst:deployment_configuration`
- `eq:availability`
- `app:test_matrix`

Labels describe the artifact, not its position. Avoid names such as
`fig:figure1` and `tab:table2`.

Bibliography keys should also be stable and descriptive, for example
`<TECHNOLOGY>_official_docs`, `<STANDARD>_<TOPIC>`, or `<AUTHOR>_<WORK>`.

## Packages and Configuration

Choose the smallest package set that satisfies the approved template and report
content. Typical capability categories include:

- Language, encoding, and typography.
- Page geometry, headers, footers, and chapter style.
- Mathematics and units.
- Graphics, captions, and floating objects.
- Tables, multi-page tables, and custom columns.
- Hyperlinks and PDF metadata.
- Bibliography and citation processing.
- Acronyms, glossary, and indexes.
- Code listings.
- Native diagrams where justified.

Document package choices and resolve conflicts centrally. Do not copy a package
list from another report without verifying that each package is needed and
compatible.

If using `biblatex`, choose a backend and citation style that satisfy the
institutional rules. If the template mandates another bibliography system, its
rules take precedence.

## Figures and Screenshots

A generic figure pattern is:

```tex
\begin{figure}[<PLACEMENT>]
    \centering
    \includegraphics[width=<WIDTH>,keepaspectratio]{assets/figures/<ASSET>}
    \caption{<DESCRIPTIVE_CAPTION>}
    \label{fig:<DESCRIPTIVE_LABEL>}
\end{figure}
```

- Introduce or immediately explain every important figure.
- Reference each figure in the surrounding text.
- Prefer vector output for diagrams and suitable raster formats for screenshots.
- Keep labels readable at the report's final printed size.
- Use forced placement only when the institutional layout or explanation needs it.
- Screenshots must show stable, relevant states and be redacted before inclusion.
- Captions describe what the reader should observe, not merely the application
  or screen name.

## Tables

Use tables for requirements, backlogs, risks, decisions, interfaces, tests,
deployment configuration, and traceability. Use a multi-page table mechanism
when the content crosses pages.

```tex
\begin{longtable}{<COLUMN_SPECIFICATION>}
    \caption{<DESCRIPTIVE_CAPTION>}
    \label{tab:<DESCRIPTIVE_LABEL>}\\
    <HEADER_ROW> \\
    \endfirsthead
    <REPEATED_HEADER_ROW> \\
    \endhead
    <TABLE_ROWS>
\end{longtable}
```

- Size paragraph columns explicitly and keep the total width within the text area.
- Repeat headings on subsequent pages.
- Split tables that combine unrelated evidence.
- Explain the interpretation of significant tables in the prose.
- Follow the report language and institutional caption style.

## Code, Commands, and Listings

- Use `\texttt{...}` for short identifiers, filenames, endpoints, and commands.
- Use a plain verbatim environment for short, unhighlighted examples.
- Select one deliberate listing system for substantial code excerpts.
- Include only the minimal excerpt needed to explain an engineering decision.
- Put long extracts in appendices only when academically necessary.
- Redact secrets, internal addresses, credentials, user data, and private paths.
- If a listing tool requires shell escape or an external executable, document
  and secure that build requirement.

## Diagrams

Maintain editable sources whenever possible. Choose a diagram notation or tool
based on the intended view rather than the source project's environment:

- Text-based diagram sources for version-controlled flow, sequence, component,
  or deployment views.
- UML tooling for formal use-case, class, state, or sequence models.
- Collaborative architecture tools for polished cloud or system views.
- Native LaTeX graphics for compact diagrams that remain maintainable in source.

Prefer vector exports for architecture and UML-style diagrams. Use raster
formats for UI and dashboard captures. Record the diagram source, export, label,
caption, chapter placement, and evidence status in an inventory.

## Bibliography

- Use one authoritative bibliography database unless a deliberate structure
  requires several.
- Prefer official documentation, standards, RFCs, peer-reviewed work, and
  recognized engineering books.
- Cite architecture patterns, technology decisions, security controls,
  methodology claims, and externally sourced definitions.
- Do not cite obvious facts observed directly in the project implementation.
- Do not reuse another report's bibliography by default; independently consult
  and validate every retained source.
- Record access dates when required.
- Check that every citation key exists and every retained entry is used or
  intentionally preserved.

## Compilation Workflow

Define one documented primary command, for example:

```bash
latexmk -pdf main.tex
```

Enable shell escape only when a trusted package or diagram conversion requires
it and the build environment permits it. If the bibliography backend requires a
manual fallback, document the exact sequence using placeholders:

```bash
<LATEX_ENGINE> main.tex
<BIBLIOGRAPHY_PROCESSOR> main
<LATEX_ENGINE> main.tex
<LATEX_ENGINE> main.tex
```

Record the TeX distribution, relevant versions, bibliography processor,
external diagram tools, fonts, and special build requirements. Before delivery,
perform a clean build and resolve errors, missing assets, undefined references,
missing citations, and unacceptable layout warnings.

## Reuse Rules for Future Report Generation

- Reuse academic structure, formatting principles, evidence discipline, and
  reproducibility practices.
- Replace all project metadata, claims, diagrams, screenshots, results,
  references, examples, paths, and commands.
- Treat institutional rules as the governing source for template-specific details.
- Adapt chapter count and implementation organization to the actual project.
- Preserve visible TODO placeholders wherever facts are unavailable.
- Do not create or claim project evidence until it has been inspected or captured.
