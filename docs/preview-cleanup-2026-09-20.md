# Approved preview cleanup — 20 September 2026

The owner explicitly approved deletion of the five previously inventoried test
collections, their answers and participation proofs. This authorization does not
cover future/new data or master records.

Completed in `edpex_m1_public_ui` only (local PostgreSQL 55469, app 8768):

| Collection | UUID |
|---|---|
| PUBLIC-PREVIEW-F01-PRIMARY | 03dcc5b3-57e5-41a3-ae1a-0b6bca8f9e70 |
| ทดสอบตัวช่วยสร้างรอบ 18-09-2569 | 30e55147-0313-45fc-ab92-8b7efd6cf13f |
| Synthetic F01 unassigned invitations | 75e950ef-3499-470b-b4d4-be172d866171 |
| ทดลอง F01 นิสิตปริญญาตรี ครั้งที่ 2/2568 | 8cc60a1f-7315-451f-9736-a07f0d84a0df |
| Synthetic F01 | eed4ddb4-844f-4080-8b3c-7dd917da0088 |

Deleted 5 rounds, 6 responses, 6 receipts, and only their dependent invitations,
access slots/pools, profiles, instrument bindings and population snapshots/members.
All three requested headline counts are now zero. Removed proof codes and links
no longer refer to active records. No replacement rounds were seeded.

Retained F04 persons10, programmes7, positions11, targets11, plans2; all users,
memberships, roles/permissions, calendars/periods, data sources, form catalogs,
questions, translations, formulas and existing audit history. In-transaction
fingerprints checked 75 retained tables; a completed cleanup record and one audit
event were added. No changes to production or the original8767 database.

## Controls and validation

`governance.0006_preview_cleanup_guards` extends the controlled retention path with
an exact-row DELETE permit: preview database, synthetic parent round, scope,
actor permissions, current transaction, and manifest membership are all checked.
Ordinary DELETE guards, INSERT/UPDATE rules and foreign keys remain active.
`preview_cleanup.py` rejects stale fingerprints, cross-scope/non-synthetic rounds,
registered F04 collections and additional linked calculation/redemption records.
It does not reset a scope, truncate tables, disable triggers, or seed replacements.

A full PostgreSQL custom-format backup was restored into the separate
`edpex_m1_cleanup_rehearsal_20260920` database. Eight checks passed: restored rows
match the plan; normal receipt deletion blocked; stale plan rejected; cross-scope
plan rejected; unauthorized actor rejected; incomplete permit rejected; injected
late failure rolls everything back; committed exact cleanup preserves other rows.

Applied run: `ecd057a1-e6ed-40c7-a45d-66d8fbc18390`.
After application, fresh inventory confirms the counts; home, login, public
assessments and proof lookup each return HTTP200. No authenticated browser visual
verification claimed. Code diff whitespace check passed.

Backup and review artifacts are under workspace `outputs/preview-cleanup-20260920`.
The backup still contains the removed historical data and credentials/hashes;
keep it locally protected, never publish it or commit it. The retained backup
is for recovery, not a migration source to import test responses into production.
Future deletion requires a new explicit authorization and fresh inventory.
