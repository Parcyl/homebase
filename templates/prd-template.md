# PRD — [Feature Name]

> Auto-generated from session [session-id] on [YYYY-MM-DD]. Source recording: `recordings/[session-id]/raw.mp4`. Workflow map: `recordings/[session-id]/workflow-map.md`. This PRD specs buildable components, not an automation of the operator's visual judgment.

## Summary
One paragraph. The workflow this captures, who it serves, and what the components together let the user do. Anchored to the observed operator behavior.

## Problem
What the operator does manually today, in operator terms. The friction the components remove.

## Target context (grounding)
- Target repo: [named + read, or "not provided; existence claims are to investigate"].
- Assumed stack until confirmed: [minimal assumptions, marked as assumptions].

## Components
Each component is a buildable unit. Carry the full contract through.

### C1 — [Component name]
- Category: [ui_ux | data_integration | codifiable_logic | ai_intelligence | open_question]
- Does: [one sentence]
- Encoded logic: [the rule with concrete thresholds/fields]
- Rationale: [WHY, in operator reasoning]
- Data contract: source, fields, access/auth, integration status [integrated | new | to investigate]
- Example I/O:
  ```json
  // in  { ... }
  // out { ... }
  ```
- Acceptance criteria:
  - [ ] [behavior] — validation: [method] — threshold: [pass bar]
- Scope: [v1 | Phase 2]

### C2 ... (repeat for every component)

## Operator-assisted judgment (not auto-automated in v1)
Visual or experiential calls the operator makes. Each: what it is, v1 operator-assisted fallback (one click), Phase 2 automation path. Never specced as a trivial v1 classifier.

## Data sources observed
Every external system, dataset, or document touched, with its integration status.

## Scope and phasing
v1 boundary vs Phase 2. Hard items flagged with their v1 fallback.

## Out of scope
Explicit non-goals.

## Open questions
Anything the recording did not resolve. Flag before build.

## Related patterns
Cross-references into workflows/library/. Populated by the compare step.

## Source artifacts
- Recording: `recordings/[session-id]/raw.mp4`
- Transcript: `recordings/[session-id]/transcript.json`
- Keyframes: `recordings/[session-id]/keyframes/`
- Workflow map: `recordings/[session-id]/workflow-map.md`
