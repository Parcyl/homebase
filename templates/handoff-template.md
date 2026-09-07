# Claude Code Handoff: [Feature Name]

> Auto-generated from `prds/[session-id]/PRD.md`. Paste this into Claude Code in the target project directory. This handoff specs buildable components. It does not prescribe frameworks, files, or function signatures. Design the architecture.

---

## Context
[One paragraph. The workflow this came from, what it is for, and who uses it. Reference the source recording and PRD by path. State that this specs the buildable components of the workflow and does NOT automate the operator's visual judgment.]

## Target context (grounding: honest)
- Target repo: [name it if one was provided and read; otherwise write "NOT PROVIDED for this session. Every 'what exists' claim below is labeled to investigate, not asserted. When a target repo is named, this section is replaced by a real read of that codebase."]
- Assumed stack (until confirmed): [the minimum assumptions needed to scope component boundaries, clearly marked as assumptions. If the real stack differs, the component boundaries hold and only the integration glue changes.]

---

## Components to build
For each component: category, what it does, the operator logic it encodes (with rationale), data contract + integration status, UI/UX behavior, example I/O, acceptance criteria (validation + threshold), and scope.

### C1: [Component name]
- Category: [ui_ux | data_integration | codifiable_logic | ai_intelligence | open_question]
- Does: [one sentence]
- Logic encoded: [the operator rule as an encodable spec, with concrete thresholds/fields]. Rationale: [WHY it holds, in operator reasoning].
- Data contract:
  - Source: [name]. Status: [integrated | new | to investigate].
  - Fields used: [field list].
  - Access / auth: [method, key, or "to investigate"].
- UI/UX: [what the user sees and does, when applicable].
- Example I/O:
  ```json
  // in  { ... }
  // out { ... }
  ```
- Acceptance criteria:
  - [ ] [behavior]. Validation: [fixture/method]. Threshold: [concrete pass bar].
- Scope: [v1 | Phase 2].

### C2 ... (repeat the C1 shape for every component)

## Preserved / operator-assisted judgment (NOT auto-automated in v1)
For each visual or experiential judgment the operator made:
- [Judgment name]: [what the operator infers]. This is genuine [visual/experiential] expertise. v1: [operator-assisted one-click fallback]. Phase 2: [automation approach]. It is a hard error to spec this as a trivial v1 classifier.

## What exists (to investigate: none asserted)
[Bulleted list of every integration/dataset/service the components depend on, each labeled "to investigate" unless a named target repo was read. State how to verify each. Never assert an integration exists without a repo read.]

## What is missing (the build)
[The components above plus any operator-assisted UI, models, scoring, and per-domain data configuration. Describe the gap, not the implementation.]

## End goal (testable)
[One paragraph. The outcome the user sees when this ships, anchored to the acceptance criteria. Every estimate carries a confidence and a source. Visual judgment calls are one-click operator tags in v1.]

## Open engineering questions
[Anything that gates the build: which target product and stack, which data sources are licensed/available, where shared state lives.]

## Source artifacts
- Recording: `recordings/[session-id]/raw.mp4`
- Transcript: `recordings/[session-id]/transcript.json`
- PRD: `prds/[session-id]/PRD.md`
- Workflow map: `recordings/[session-id]/workflow-map.md`

## Rules of engagement
- Design the architecture. Do not ask which framework, library, or pattern to use.
- Break work into stages if a component touches 3+ files. TDD. No em dashes. Conventional commits. Branch as feat/ or fix/.
- Build v1 components only; defer Phase-2 items. When a data source is "to investigate", stub the contract and flag it, do not invent it.
- When uncertain, decide and document in HANDOFF-[repo].md.

---
