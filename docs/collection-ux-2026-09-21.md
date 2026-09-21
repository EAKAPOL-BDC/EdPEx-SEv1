# Collection management and automatic survey questions

Implemented on the isolated public preview at `http://127.0.0.1:8768/`.

## Operator workflow

- Collection cards use instrument icons, group tags, year, creation date and a short reference. Counts, pagination and filters include parent batches and earlier collections consistently. Existing same-title records remain separate; none were merged or deleted.
- Status includes draft, not public, scheduled, open, closed and mixed. Closed dates are reflected even before a separate administrative close action. Text and symbols accompany colour.
- A parent batch has one **Open and publish all groups** action. It still has one final review through the existing confirmation system. Opening permits collection; publication makes the form available in public entry. Both conditions and the response window must hold. A future start remains scheduled.
- Bulk launch is atomic. If one group fails readiness or publication checks, all changes roll back. Withdraw and close remain secondary controls; closing requires a reason and retains submitted responses.
- Context/programme rows show short names, state, reference counts and submissions. Search filters rows immediately.
- F04 appears as a prominent card in the creation chooser. Annual generation explains that it prepares every leadership position for both ST1 and ST2. Sections separate form selection, counts, dates, privacy and proof settings.
- The annual register has one launch operation for all public F04 collections and both staff groups, with the same final review and atomic rollback. Earlier roster collections are excluded from the public control summary. Existing readiness, scope and permission checks remain active.

## Respondent experience

Generic public forms share the purple/pink/gold visual language, mascot header, question cards, selected-answer feedback and progress navigation. The existing specialised F01 C1 renderer remains in use.

Relevant conditional questions are included in the initial schema for the respondent's group and actual leadership role. JavaScript updates visibility immediately. F04 information selection opens the relevant leadership section; changing to no information hides and disables unrelated controls. Values stay in the current page when toggled back. They are not persisted in browser storage.

The server remains authoritative for allowed questions, required answers and normalization. Hidden inputs are excluded from submission; hidden answers normalize to `not_shown`. Schema output contains no option scores. Language changes preserve the current submitted form values. The manual update button is only a no-JavaScript fallback.

Collection management and generic respondent pages use natural document scrolling, so the footer does not reserve most of a short mobile screen. The annual table no longer uses the clipping sticky heading. No changes were made to underlying questionnaire wording or scoring formulas.

## Verification and boundaries

The three regression suites cover 37 cases (`test_assessment_batches`, `test_public_assessments`, `test_participation_ui`). The initial run had one stale test expecting the former setup route; it was updated to verify the new redirect and multi-group form. The focused 11-case rerun passed. Additional enhanced submission checks cover F04, F02 and F03.

Browser checks used real Django-rendered isolated test fixtures, desktop 1280 and mobile 390 widths: closed badges, creation/F04 layout, immediate filtering, F04 conditional appearance, hiding/disabling, preserved choices and progress recalculation. No browser submissions were made into user data. Fifteen current staff pages also rendered successfully inside a read-only database transaction. Home, login, public entry and changed static assets returned HTTP 200.

Before/after fingerprints matched for all 77 existing models. No migration, user data deletion, automatic round opening or publication was performed. A local backup is stored at `outputs/ux-launch-20260921/before-ux-launch.dump`; it is sensitive, must not be committed/uploaded, and was not restore-tested in this task.

This is still the isolated TEST preview; live participation remains disabled. This update is not a production deployment. Production hosting, live configuration and the decision about which existing data to migrate require a separate deployment step.
