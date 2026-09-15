# EdPEx-SEv1

Django foundation for the bilingual Thai–English EdPEx system (F01–F06), based on
System Blueprint 1.2 and Instruments 1.1. F06 is a self-assessment and evidence
attachments are optional.

See [คู่มือการตั้งค่าและตรวจสอบ](docs/setup-th.md) for the PostgreSQL/Supabase
safety model and Thai verification instructions.

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
