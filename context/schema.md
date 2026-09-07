# context_config schema

`pipeline/doc_generator.py` never hardcodes a product's zones, severities, or triage
prompt. All of that lives in one JSON file, pointed to by the `CONTEXT_CONFIG` env var
(default `context/example-webapp.json`). Swap the file to point `doc_generator` at a
completely different product with no code change.

## Fields

| Field | Type | Meaning |
|---|---|---|
| `product_name` | string | The product being walked through. Interpolated into `system_prompt` via `{product_name}`. |
| `zones` | array of `{code, key, label}` | The regions/areas bugs get classified into. `key` is the machine value the model returns and every bug is filed under; `code` is a short uppercase prefix used for bug ids (`NB-01`) and filenames; `label` is the human-readable heading shown in the rendered docs. |
| `severities` | array of strings | Ordered most-severe first (rank 0 = worst). Bugs within a zone are sorted by this order. |
| `system_prompt` | string | The triage system prompt template. Must contain the literal placeholders `{product_name}` and `{context}` -- `doc_generator` fills `{context}` with the contents of `context_md` at call time via `str.format`. |
| `context_md` | string | Repo-relative path to a markdown file: the ground-truth description of the product's layout, fed into every Claude call so bugs land in the right zone. |

## The catch-all zone

If the model returns a `zone` value that isn't one of the configured `zones[*].key`,
`doc_generator` files the bug under a built-in `unclassified` zone (code `UNC`) rather than
dropping it. This is NOT part of the config -- it always exists, on top of whatever zones
you configure, so a config never needs to plan for its own failure mode.

## Example

See `context/example-webapp.json` (generic 3-zone example: frontend / backend / infra) and
`context/example-webapp.md` (the paired layout doc it points to). Copy both, rename, and
edit to fit your product; point `CONTEXT_CONFIG` at your copy.
