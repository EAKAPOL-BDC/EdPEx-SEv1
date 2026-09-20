# NEXORA manual center: verification record

Date: 2026-09-17. Documentation baseline: `482d36479dbc6c9d96f3941d70620c6a9ca03ccf`.

## Content and artifacts

- 26 manuals: all 17 catalog respondent groups, 8 operational responsibilities, 1 developer guide.
- 233 PDF pages in total; developer guide: 20 pages, 21 sections.
- Document workflows follow current services and templates. Invitation-based F01–F04, account-based F06 and officer-managed F05 are described separately.
- PDF and web contents share resolved JSON and section templates. Manifest checks cover all PDF byte hashes and content hashes.
- PDF inspection: every page rendered, all 26 documents inspected in page overviews, representative Thai/English text, developer contents, architecture and tables checked at larger size. No empty pages or text outside page bounds; no sparse trailing pages flagged by the final inspection.
- Embedded Sarabun Regular/Bold and a monospaced font support selectable Thai/English text. Sarabun's OFL license is included.
- PDFs are prebuilt; the deployed application needs no WeasyPrint or network font fetch.

## Automated checks

17 tests passed in an isolated PostgreSQL-compatible test database; no production database was modified:

```
tests.test_manuals
tests.test_backoffice.BackofficeTests.test_navigation_stays_inside_sidebar
tests.test_assessment_presentation
tests.test_survey_http_guards
```

Coverage includes catalog/form/group completeness; every manual's HTML and PDF endpoint; anonymous access and authentication gates; absence of answer or grant writes; organization-scoped work links and revocation; unknown paths, traversal, unsupported methods, missing/stale/tampered PDFs; HEAD/cache/nosniff headers; menu placement; draft section restoration; F06 controls; and invitation request guards.

Django system checks, all application template syntax checks, and new CSS parsing passed.

## Boundaries

Tests verify server-rendered responses and PDF artifacts. A live browser review and installation on the user's Windows computer were not performed. These checks do not replace organization UAT or validate real operational data. Outstanding product work remains recorded in `docs/system-readiness-th.md`.
