# Synthetic F01 collection setup

The invitation centre now links to **Create a new test collection from this form**.
Route: `/workspace/<scope>/surveys/<source-binding>/new-test-collection/`.
This is a test collection setup screen, not a production launch wizard.

The source must be a synthetic F01 C1 collection with a test receipt policy and
published pinned instrument/translation bundle. Its reporting period and study
stage options are inherited explicitly; choosing another year, group or instrument
is separate work. Required scoped permissions: round.manage, population.manage,
source.manage. Feature flags and normal staff login/CSRF protections apply.

## Workflow

1. Enter a unique collection name and Thai/English context.
2. Set opening, due and closing dates in the scope's displayed time zone. Specify
   total capacity and an aggregate evidence title/reference, without a name list.
3. Write the collection data-use notice and bilingual receipt labels. Choose at
   least one purpose (workload/reward verification) and receipt expiry after close.
   These choices do not credit hours, select winners or connect external systems.
4. Confirm that this is synthetic data, review entries in the existing confirmation
   screen and submit. The collection is saved as **ready**, not open. No invitation
   or response is created. The invitation centre links to the existing collection
   settings for the separate open action.

The creation transaction includes the round/profile, frozen aggregate population,
test receipt policy, fixed capacity and readiness transition. A failure rolls the
whole operation back. No PopulationMember is created. A signed actor/source/UUID
stamp expires after one hour; creation is serialized on the source round and a
completed stamp cannot create another collection, even if the submitted name is
changed. The existing single-use confirmation middleware remains in place.
Opening a fresh form intentionally creates a new request. Unique scope-level
collection names are enforced by the existing model/database constraint.

## Validation

Six setup tests passed: creation and replay, invalid fields/atomic rollback,
permissions/CSRF/scope/feature gates, forged stamps and duplicate names, existing
review/confirm flow, language/navigation. See workspace output
`outputs/participation-setup-tests.log`. Django checks and migration drift passed;
this increment requires no schema migration.

A real browser trial in the dedicated demo database created:
`ทดสอบตัวช่วยสร้างรอบ 18-09-2569`, binding
`d2b0827e-606b-4bb1-817b-72ee4ce493f1`, capacity 5, status ready, 0 issued codes and
0 submissions at creation. Preserve this trial and all older user records.
Desktop/mobile390px were inspected; no horizontal overflow. The existing test
account was used, without changing roles or creating edpexadmin.

## Guided field help

The setup page now contains bilingual inline hints and labelled test examples for
all 15 visible configuration fields. Native details/summary disclosures explain
why each item matters without requiring JavaScript. Section anchors and a naming
comparison distinguish the staff collection name, respondent context and receipt
activity label. The final panel explains review → ready → separate opening.

Eight text fields have an explicit Use example button, revealed only when JS is
available. It fills empty fields only; existing values disable the button. It does
not select receipt purposes, confirm the form, submit, make API calls or persist
draft values. Samples remain synthetic and must be adapted, including references
to capacity. The participation-only receipt purpose is still not implemented and
the UI explicitly explains the current at-least-one-purpose requirement.

The schedule helper formats wall-clock inputs in the displayed scope timezone and
uses the current page locale (Thai Buddhist/English Gregorian display). It checks
date ordering and receipt expiry with native custom validity. Authoritative server
validation still applies, including future closing. The helper is initialized again
on portal:updated, retaining entered values through the shared language switch.

Verified guidance for both locales, Django template/system checks, JS syntax and
browser interactions: sample insertion, disabled overwrite, details expansion,
reversed dates, invalid receipt expiry, corrected dates, Thai/English switch with
entered text preserved, and mobile390px without overflow. No browser submission
or new collection was made for this UI-only increment. Existing user tabs were not
reloaded. No database schema or permission changes.
## Review before confirming (19 September 2026)

The shared governance confirmation page now uses a purple/pink/gold overview,
structured data cards, section links, readable Thai/English dates, impact notes,
and a separate acknowledgement/action panel. Setup gets three semantic groups;
other management actions retain the generic full-entry review. Submitted values
are escaped and never translated or reformatted in the POST payload.

Language switching preserves the entire review DOM and its existing ticket rather
than replacing it with the GET setup form. The countdown uses the original server
expiry; browser checks complement the authoritative server checks. Confirmation
still requires explicit acknowledgement, matching payload/context, and an unused,
unexpired user/route-bound ticket.

For setup only, Back to edit posts the exact payload and ticket with operation_edit.
The middleware checks owner, route and payload, consumes the old ticket and calls
setup in a read-only edit mode. It renders the bound form with a fresh setup stamp;
it never calls create_collection or issues a processing notification. An expired
review may return to editing, but cannot execute a creation. Reviewing the edited
form produces a separate confirmation. Scope/source permission checks still run.
No answers or drafts are stored in browser persistent storage.
