# Parcyl acquisition run: ground truth layout

This session is a real acquisition workup on a live deal, run from the terminal through the
Parcyl `site-analysis` skill, recorded end to end. It is not a bug bash of a web app. Classify
findings against the pieces below.

## skill — the site-analysis workflow
Lives in `~/parcyl/scoutgpt-api/.claude/skills/site-analysis/`. The PDF design is LOCKED and
must not be restyled. Ten fixed sections, in order:
1. Cover (green to charcoal band, wordmark, lede, full-width subject aerial, 4 stat cards)
2. Executive Summary (lede, key-fact table, deep-green HBU callout)
3. Subject Property Detail (identity, legal, owner, acreage, use, zoning, assessed value and
   prior year, taxes, liens, acquisition deed and mortgage)
4. Location & Access (narrative, regional aerial, traffic exhibits)
5. Site Constraints (flood zone, transmission lines, easements, topography, access)
6. GIS & Environmental (aerial, table, note)
7. Surrounding Development (aerial, what is being built nearby and by whom)
8. Market Analysis (assessor $/acre tiers, rural-acreage comps, commercial-corridor comps,
   and the Parcyl Market Value box)
9. Highest & Best Use (narrative, value-creation path, ranked risks)
10. Data Provenance & Next Diligence (always the last page)

Companion skills it loads: `comps`, `hbu`, `market-research`, `property-db-queries`.
Generator: `node generate.js <data.json> <out.pdf>`. Schema: `schema.md`. Reference deal:
`example-seguin.json`.

Output hygiene rules that are part of the product, not preferences: no vendor source names in
the PDF (never ATTOM, Snowflake, HIFLD, MLS, or the words listing/listed/asking). Everything is
attributed to Parcyl. FEMA and published traffic counts stay named. Value is stated as Parcyl's
market opinion, shown separately from the county assessed value.

## data — where the numbers come from
- Snowflake share `ATTOM_PARCYL_SHARE.DELIVERY`, queried with
  `node scripts/corpus/sf.js "<SQL>"` from `~/parcyl/scoutgpt-api`. Views in play:
  `TAX_ASSESSOR`, `RECORDER`, `LOAN_MODEL`, `CLIMATE_CHANGE_RISK`, `PREFORECLOSURE`,
  `BUILDING_PERMIT`, `LISTING_ANALYTICS_COMPLETE`. VERIFIED WORKING this session.
- Neon `ep-shiny-violet` (`DATABASE_URL` in scoutgpt-api) holds ~14.4M TX properties.
  VERIFIED FAILING this session: password authentication failed for neondb_owner.
- Texas is a non-disclosure state. Recorded deeds carry no sale price, so acquisition mortgage
  amounts are the pricing proxy. A comp with no price is not a missing comp.
- A database error and a valid empty result are different outcomes and must never be reported
  the same way.

## map — the feature being specified during this run
Does not exist yet. The target is a shareable live interactive map, the Parcyl equivalent of
what land.id offers, built for the acquisition use case:
- the GIS layers the analyst chose for this deal, rendered
- the comps as pins
- the market research as pins
- popup cards on each pin carrying the detail and its source
- a share link an analyst can send to a client
Parcyl's GIS is three separate pipelines and prod serves PMTiles from S3 and CloudFront, not
Mapbox tiles. A layer painting on the map says nothing about parcel-join integrity or source
coverage. Treat any claim about layer coverage as unverified unless the trace shows it measured.

## pdf — the deliverable
A client-facing PDF generated from a data JSON. Findings here are about content, exhibits,
aerials, section completeness, and anything that made the operator hand-edit the output.

## workflow — how the deal actually got worked
The step-by-step order of operations, the tool switching, the copy-paste, the re-queries, and
the judgment calls. This is the raw material for a repeatable pattern.

## app — Parcyl product surfaces
`~/parcyl/parcyl` is the product (React/Vite, Node, Neon/PostGIS). The deal room route is
`/pipeline/:dealId`, not `/crm`. Anything the operator opened in the browser during the run
belongs here.
