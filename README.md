# EdPEx-SEv1

Django foundation for the bilingual Thai–English EdPEx system (F01–F06), based on
System Blueprint 1.2 and Instruments 1.1. F06 is a self-assessment and evidence
attachments are optional.

See [คู่มือการตั้งค่าและตรวจสอบ](docs/setup-th.md) for the PostgreSQL/Supabase
safety model and Thai verification instructions.

See [คู่มือเตรียมติดตั้ง migrations บน Supabase development](docs/supabase-development-migrations-th.md)
for the manual plan/apply workflow, existing secret names, backup/restore preparation,
and checks that preserve existing Django accounts. The workflow defaults to read-only
planning; this preparation does not apply migrations to Supabase or deploy the app.

M0 source documents and offline catalogs are available in `docs/source/` and
`catalog/`. See [ทะเบียน M0 และวิธีตรวจโดยไม่เชื่อมฐานข้อมูล](docs/m0-catalog.md)
for all 63 indicator bindings, F01–F06 questions, formula/group registries,
Blueprint 1–33 traceability, and the Thai–English translation inventory.

```text
python scripts/build_m0_catalog.py
python -m unittest discover -s tests -p "test_m0*.py" -v
```

These commands do not load Django settings, contact Supabase, or seed a database.
The English content remains pending translation and semantic review. F06 has no
evidence upload or reviewer workflow; examples and development plans are optional.

M1 adds Django models, migrations, scoped permissions, version history, reviewed
translation bundles, calendars, populations, provenance, and audit events.
See [โครงสร้าง M1 และวิธีทดสอบ PostgreSQL ชั่วคราว](docs/m1-schema-th.md)
for table descriptions, the decision to preserve Django auth.User, and empty/legacy
migration tests. M1 has not been migrated to Supabase or deployed.

PR #3 review fixes and their PostgreSQL regression coverage are described in
[ข้อค้นพบ → วิธีแก้ → ไฟล์ → tests](docs/pr3-fixes-th.md).

M2 now has an offline, server-side calculation core for the 20 formula templates
in version 1.1. It includes CAL-01–18 fixtures, typed answer/status validation,
frozen population inputs, latest submitted revision selection, F05 deduplication,
and safe pooling of disjoint groups. The catalog adapter checks all 63 indicator
bindings, including their group and dimension variants.

```text
python -m unittest tests.test_m0_catalog tests.test_m0_bindings tests.test_m0_source_semantics tests.test_m2_golden tests.test_m2_validation
```

See [แกนคำนวณ M2: ผลทดสอบและขอบเขตการใช้งาน](docs/m2-calculation-core-th.md).
The next increment adds internal persisted calculation runs, source/definition
snapshots, checksums, replay, scoped source/run/validation permissions, and
transactional idempotency. See [รอบคำนวณและการตรวจผลย้อนหลัง](docs/m2-snapshots-th.md).
It includes additive migrations but does not apply them to Supabase automatically.
The F06 increment adds owner-only draft/submitted revisions, frozen duties and expected
levels, a stored-response calculation adapter, and independent aggregate approval/return
with retained correction history. See [F06 intake and result review](docs/f06-stored-collection-th.md).
Anonymous F01–F04 collection, verified F05 intake, historical imports, publication and annual
aggregation remain pending before the full M2/M4 milestones are complete.
