# {product_name} — Session Digest — {session_id}

> Single hand-off doc. Each zone is a self-contained worklist so one developer can take it
> end to end. Read top to bottom, or jump to your zone. Per-item detail lives in `bugs/`.
> Zones come from your `context_config` (see `context/example-webapp.json`) -- this shows
> the generic shape, not a fixed set of names.

- **Captured:** {captured}
- **Recording:** `{recording}`
- **Totals:** {total} items — {severity_counts}

## How to dispatch this

- **[Zone 1 label]** -> one developer.
- **[Zone 2 label]** -> one developer.
- **[Zone N label]** -> one developer.

Hand this file to Claude and it can fan out an agent per zone.

---

## [Zone 1 label]
{zone_1_section}

## [Zone 2 label]
{zone_2_section}

## [Zone N label]
{zone_n_section}

---

## Workflow-connection map
{workflow_map}
