# Your Web App: Product Context (example)

This is the ground truth about your app's layout, paired with `example-webapp.json`. The
capture pipeline feeds this into every Claude call so each bug is filed to the correct
zone. Edit this file (and the zones in the JSON) as your product changes -- everything
downstream reads from it.

## What this app is

Replace this paragraph with a short description of the product being walked through: what
it does, who narrates the sessions, and why (dogfooding, QA pass, onboarding a new
teammate, pre-release review).

## The layout: three zones

### Frontend (`zone: frontend`)
The client-side application: UI, layout, client-side state, rendering. Replace with your
own regions -- a two-panel app might use `left` / `right` instead of `frontend` / `backend`.

### Backend (`zone: backend`)
The API, business logic, and data layer.

### Infra (`zone: infra`)
Deployment, environment configuration, data pipelines, and anything cross-cutting that
isn't bound to one region -- auth, performance, third-party integrations.

## How to classify a bug into a zone

1. If the narrator names the region ("on the frontend", "in the API", "the deploy step"),
   use it.
2. If the bug is about getting one region to talk to another, pick whichever zone owns the
   fix and say so in the bug's notes.
3. When genuinely ambiguous, pick the zone where the fix most likely lands.

Allowed zones: `frontend`, `backend`, `infra`. A bug the model files under anything else
lands in the built-in `unclassified` catch-all (see `context/schema.md`) rather than being
dropped.

## Severity scale

- `blocker`: cannot ship with this; it breaks a core flow.
- `high`: visibly broken or wrong, needs fixing before release.
- `medium`: real bug, not release-blocking.
- `low`: polish, copy, minor visual.
