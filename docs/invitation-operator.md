# Unassigned invitation operator centre

This increment manages already configured F01 C1 **test** pools. It does not
activate live collection or provision new populations/receipt policies.

## Staff workflow

Open the collection page and choose **Unassigned invitation centre**. The route is
`/workspace/<scope>/surveys/<binding>/invitations/`. Staff need both `round.manage`
and `population.manage` in that scope. Login and Django CSRF protection apply.
The existing review/confirmation middleware remains enabled in the normal app.

1. Review capacity, codes issued, completed submissions and unissued capacity.
   Counts concern unassigned passes; legacy invitations, if present, are separately
   disclosed as capacity already reserved. No answer records, scores, receipt
   tokens, recipient names or individual usage histories appear.
2. Enter a batch size (1–100, bounded by remaining capacity), acknowledge random
   distribution without a recipient map, then review and confirm the operation.
3. The issued codes and locally generated QR cards appear once. The print button
   invokes the browser print dialogue, where supported browsers offer Save as PDF.
   Keep the resulting cards private; no email is sent. This is not a claim that a
   physical printer or a downloaded PDF file was tested in the in-app browser.
4. Pause/resume the invitation channel with confirmation. Pausing terminates its
   transient sessions. Existing receipts stay valid; unused pass holders must
   reopen their original link after resuming. This does not close the underlying
   collection or affect another legacy invitation path. Collection schedule/state
   settings remain in the existing collection screen.

## Concurrency and failure boundaries

The batch form has a signed, 15-minute actor/binding/issued-count stamp. `mint`
compares the expected count under the existing round row lock. Replaying a
successful POST, concurrent tabs at the same count, or another batch issued in the
meantime produces a conflict and cannot mint another batch. Reload explicitly to
review new totals. Raw codes are not retained to recover a lost response; a lost
batch still consumes quota and is not silently replaced. Quota counts do not
decrease for lost or revoked codes.

QR rendering and template rendering occur inside the issuance transaction so a
rendering failure rolls back the batch. A network failure after commit cannot be
rolled back and does not make the same request safe to repeat.

The portal's shared JS owns submit locking; the new JS only triggers printing.
Pages containing codes are private/no-store, same-origin referrer, same-origin CSP,
and cannot be framed. The review page omits the internal stamp from visible fields.

## Development preview and validation

`/demo/invitations/` exists only in `edpex.participation_demo`, accepts loopback
GETs only, and renders aggregate totals from the synthetic `f01-unlinked-demo`
policy. It is **read-only**, grants no staff session and does not mint codes.
The normal URLconf does not expose this preview. The user-facing localhost QR
continues to work only on the computer serving Nexora.

Tests: `tests.test_participation_operator` (8 cases), including scoped permissions,
CSRF, quota, replay/stale stamps, rollback on QR failure, confirmed pause/resume,
TH/EN output, and the existing two-stage review/confirmation middleware. Existing
unlinked admission tests were also exercised. Desktop and 390px responsive preview
were checked in the browser, without reloading the user's respondent form.

Still separate work: a setup wizard for a new aggregate-only round and receipt
policy, a chosen test-staff sign-in workflow, approved real wording/distribution,
retention/erasure, additional forms/groups and external workload/reward consumers.
No live database migration, deployment, production flag change or data refresh
is part of this increment.
## Guided collection readiness and lifecycle (19 September 2026)

The invitation centre now contains a seven-item readiness checklist and separate
collection open/close controls for synthetic F01 C1 test collections. It clearly
distinguishes collection status from whether the invitation channel is enabled.
Checks cover test scope, published pinned wording/translations, frozen aggregate
capacity, enabled unexpired participation proof policy and its purposes, current
collection window, invitation access, and the existing authoritative round rules.
The timestamp is a point-in-time read; Check again performs a GET only.

Opening and closing go through the existing review/confirmation page. A separate
15-minute signed control stamp binds actor, binding and expected collection state.
The reviewed collection name is checked against the actual round. Under the round
lock the service repeats permission, feature, scope/type and readiness checks,
then delegates to the existing audited transition_round service. A stale/replayed
form cannot repeat an action. Opening never issues invitations automatically.

Closing requires a reason. It stops new submissions, including from respondents
already filling the form, while retaining answers, issued proofs and invitation
capacity. Closed collections cannot be reopened through this control. Use the
separate Pause invitation access action for a temporary interruption. Closing
leads to the guided result-workflow screen for synthetic F01 C1 test pools; it does not calculate or approve
results automatically. No schema change, live activation or permissions grant.

The browser preview remains read-only. No operator GET or readiness check changes
business data. The lifecycle is tested against the isolated test database, not by
opening or closing the user's demo or production collections.

## Result workflow hub (19 September 2026)

Use Track calculation, review and reports from the invitation centre. The new
GET-only participation-results page scopes its binding to the workspace and
supports synthetic F01 C1 test pools only. It shows four steps, a timestamped
refresh, bilingual expandable explanations, aggregate participation for collection
managers, and a paginated history of calculation sets for authorized result staff.
Review-only staff do not receive participation totals. There are no individual
answers, comments, invitation/session/receipt tokens or result scores in the hub.

Close a collection after collecting responses. Prepare calculation opens the
existing cutoff-pinned dry run and confirmation workflow; merely visiting the hub
does not calculate anything. Submit a saved set for review, then have an authorized
independent reviewer approve it. Only approved, non-superseded sets expose internal
report/CSV links to staff with both result.review and calculation.validate. Existing
source validation, small-group suppression and scoped authorization remain decisive
at those endpoints. Returned/unapproved sets cannot be exported as approved reports.
Empty closed collections show a clear no-responses state; no responses are generated.

Calculation and result approval do not redeem participation proofs or grant hours
or prizes. All lifecycle and calculation integration tests use the isolated test
database. No browser lifecycle/calculation POST is needed to verify the new hub.
No schema change, production flag change, live database operation or deployment.

Remaining release work includes real operational wording/distribution, retention
and erasure, production configuration/security review, other forms/groups, and
external workload/reward consumers. This increment prepares the F01 test workflow;
it is not a claim that the complete platform is ready for production.

## Guided calculation and review actions (19 September 2026)

The survey calculation page now checks closed collection state and frozen
population before displaying its form. For the enabled synthetic F01 C1 test
participation workflow, it additionally requires at least one submitted response.
POST repeats this guard, so a direct URL or manually crafted form cannot create
an empty result set through this page. The calculation service still performs its
own existing locked validation; numeric formula behavior was not changed.

The preview shows its exact source cutoff, time zone and result-series count
(explicitly not a respondent count/score). It asks for a reason with a safe example
and acknowledgement, then uses the existing confirmation before saving. An expired
or invalid signed preview returns a localized error and retains the typed reason.
The operator must preview again. Preview signatures still bind actor, collection,
cutoff, source hash and idempotency key and expire after 30 minutes.

Switching TH/EN on a POST calculation preview preserves its original main DOM,
signed token, acknowledgement and save action. Switchable copy changes via CSS;
header/footer are refreshed. This extends the existing confirmation-page handling,
without persisting answers or explanations in browser storage.

The shared result review screen adds status-specific next steps: submit a saved
set, await an independent review, inspect return reasons before preparing a new
set, or view/export an approved set. Superseded results remain history. Permission
checks, source validation, independent review and small-group suppression are
unchanged. New report links are only shown when an approved non-superseded packet
is available to an authorized reviewer. Destination endpoints remain authoritative.

No schema, production connection, privilege grant, live deployment or browser
collection/calculation mutation was part of this increment.
