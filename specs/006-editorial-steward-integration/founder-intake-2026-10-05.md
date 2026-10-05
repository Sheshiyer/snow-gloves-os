# Founder intake: Axtech portfolio, 2026-10-05

Source: the founder, in a planning session on 2026-10-05. The founder drew the portfolio by hand and then
answered questions about each box in writing. This file records those answers so that `tenants/*/context/`
can cite a path instead of a chat. It replaces nothing in `portfolio-map-proposal.json` by itself; that file
was updated from this one on the same day.

Legal entities, domains and ownership links are still not recorded. A position in this map is an operating
scope, not a cap table.

## The sketch

Axtech at the top, every box below it joined to Axtech. Readings marked `?` are uncertain handwriting.

| Box on the sketch | Child boxes | Notes on the sketch |
|---|---|---|
| "C…lia?", OEM content | | number 2 above it |
| Sunfeed (written "Sanfeed"): renovation installation; electrical, plumber, heat pump | | number 6 above it |
| Ecoled, B2B / B2C | | number 25 above it; a word below it is unreadable |
| Axtech Heat pump | | |
| CEE Management | iVerif | "500R" beside it |
| Mobile Accessories Wave | | |
| China Sourcing Import | | |
| HeyZack, home automation | "Symphonie Électricité?" | |
| Metagration (sketch reads "…gration AXIA") | Web App, B2B Spec | |
| SAFVR services (sketch reads "SAP E UR") | | |

## What the founder said about each box

- **Wave.** Under Axtech; sells mobile accessories B2B.
- **CEE Management.** Under Axtech. Works with companies to understand which CEE (Certificats d'Économies
  d'Énergie) apply to them, and works with the obligé to process them. iVerif is the system used to process
  the documents, but CEE Management is more than iVerif: iVerif is one part of it.
- **Sunfeed.** Renovation, construction, and installation of heat pumps, plumbing and electrical.
- **Axtech Heat pump / Axtech Shop.** Part of Sunfeed and Axtech, but Sunfeed only installs and does not sell
  products. The Axtech shop lists all the products sold under the group's different brand names.
- **China Sourcing.** An ingestion system into the group's ERP and business. The group has worked in the
  Chinese market for more than 15 years and has contracted hundreds of vendors, manufacturers and clients.
  This is a curation and routing effort: even when the group does not procure the products, it can redirect
  purchase intent to sales for a percentage margin, using its connections, licensing and experience.
- **Metagration.** An app and AI integration for restaurants, hotels, parlours and similar places: an
  automated website, an inbound calling agent and an answering system, with a knowledge base synced with
  skills for managing the business.
- **AXIO.** The AI wing of Metagration, a separate B2B product with on-site training so companies get their
  specific skills and flows set up.
- **SAFVR services.** A trickle-down from another project, safvr.com, which does safety management, video
  intelligence and reporting. Companies that need this at B2B scale, and pilots, are what Axtech can pitch.
- **Kartezzi, Izzimo.** Under Axtech (not on the sketch).
- **SaveWatt.** Dropped.

## Decisions taken in the session

1. Tenant or project. A unit gets its own tenant when it has its own customers or holds data that must be
   walled off; otherwise it is a project inside a tenant.
   - Tenants under Axtech: `heyzack`, `ecoled`, `kartezzi`, `izzimo`, `wave-concept`, `sunfeed`,
     `cee-management`, `china-sourcing`, `metagration`.
   - Tenant under Metagration: `axio`.
   - Projects: `axtech-shop` and `safvr-channel` under `axtech`; `iverif` under `cee-management`.
2. `tenants/savewatt/` and `tenants/iverif/` are removed. Neither held anything beyond FILL placeholders.
3. The slug `china-sourcing` is confirmed. China Sourcing is its own tenant because its vendor, manufacturer
   and client network and its margins are the most sensitive data in the group.

## Still open

- The "C…lia?, OEM content" box: its name and where it belongs.
- "Symphonie Électricité?" under HeyZack: the reading and the relationship.
- The numbers 2, 6 and 25 and the note "500R".
- Whether the trading name is "Wave" or "Wave Concept" (the tenant folder uses `wave-concept`).
- The cross-brand flows in `portfolio-map-proposal.json` (`cross_brand_flows`) are proposals, not approved
  sharing rules.
