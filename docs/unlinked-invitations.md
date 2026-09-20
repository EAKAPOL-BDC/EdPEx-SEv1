# Unassigned single-use invitations — F01 C1 test increment

An invitation is a random bearer pass, not an identified person. The new path
stores no recipient name, email, employee/student ID, contact address or assignment
map. A new collection may use a frozen aggregate group count without creating any
PopulationMember records. Existing roster-based rounds and receipts are retained.

## Entry and distribution

An authorized operator prepares one collection per existing supported respondent
group/context, freezes its aggregate eligible count, configures a test receipt
policy and access capacity, then opens the collection. The next operator UI remains
separate work; service entry points already enforce round/population/source scope
permissions. No new public mint endpoint is added to the normal application.

`admission.mint(actor, binding_id, count)` returns up to 100 random `NXA1-` passes
once, shuffled, and stores only SHA-256 hashes. Generate a batch before distribution;
distribute unassigned cards/QRs without recording which person receives which card.
Do not add recipients to exports, encode names in links, or keep a pass-to-person
spreadsheet. The operator must not publish a single bearer link for everyone.
Physical distribution controls, rather than Nexora identity tracking, determine
whether someone receives more than one pass. Raw pass delivery is the operator's
responsibility; no email/SMS sending is implemented or performed.

The link is `/survey/entry/#NXA1-…`. Its fragment is removed from the address bar
before the user explicitly opens the assessment through a CSRF-protected POST.
No signup or recipient identity field is shown. Manual code entry is also available.
The server fixes group, programme/context, instrument and round; users cannot change
these through the POST. Thai/English can be selected on entry and in the form.

Opening a link does not consume its submission right. Reopening the same bearer
code rotates the transient HttpOnly session; any earlier session stops working.
Unsubmitted answers are not stored. On submission, the access pass is spent, the
answer is committed, the independent participation proof is issued, and the
transient session is removed in one transaction. A lost acknowledgement uses the
existing receipt recovery protocol, never a replacement submission.

## Data boundary and limits

- AccessPool: binding, capacity, enabled.
- AccessPass: random UUID, binding, token hash, expiry, spent/revoked flags.
- AccessSession: random UUID, pass FK, session hash, expiry, revision (always zero).
- AnonymousResponse and ParticipationReceipt keep their separate existing stores.
  Neither has a pass/session/person FK; no answer UUID goes into the participation QR.

Capacity is bounded by the frozen aggregate group count. Existing legacy invitations
also consume capacity in a mixed historic collection. Revoked/lost passes do not
automatically replenish capacity. Database guards protect the quota, immutable
bindings/context, terminal pass states and deferred spend/response equality.
The round is locked before quota issuance, entry, submission and administrative
disable, so concurrent submissions/mints cannot overspend the same right/capacity.

The guarantee is **one submission per pass**, not one per person. A bearer can share
or lose a code; Nexora cannot infer who used it. Free text may still identify its
author if the author ignores the notice. Shared DB timing/WAL, browser history,
infrastructure logs and distributions outside this service can correlate events.
Removing a URL fragment is not a promise of deletion from all browser/history/sync
systems. Precise response timestamps remain in the existing answer store. This
increment is not a claim of complete anonymity or legal compliance.

Future workload/reward consumers may identify claimants in their own systems and
apply one-claim-per-person/round policies. They must not send those identities to
Nexora's verify/redeem APIs. Nexora proofs demonstrate participation rights only;
the external systems decide credits, eligibility and awards.

## Service setup

For a new F01 C1 synthetic draft binding:

1. `prepare_population(actor, binding_id, count, source_title=…, source_reference=…)`
   creates/finalizes an aggregate denominator and no member rows. The source must
   refer to aggregate evidence, not a personal roster location.
2. Configure the existing test receipt policy (expiry after collection close).
3. `configure(actor, binding_id, capacity)` pins the capacity. It cannot be expanded
   or moved after creation. Supported only by the feature-gated F01 C1 test path.
4. Transition ready → open through the existing round services.
5. Mint and distribute a batch. `set_enabled(actor, binding_id, False)` stops this
   access path and removes transient access sessions; already issued proofs remain.

`NEXORA_UNLINKED_ACCESS_ENABLED` defaults false and also requires participation to
be enabled. Receipt policy must be test realm; new live intake is not activated.
Other forms and legacy invitation services keep their original behavior.

## Local demonstration

Only `edpex.participation_demo` exposes `/demo/` to loopback clients. It displays a
synthetic invitation card/QR from a dedicated aggregate-only collection, then the
same entry screen actual recipients would use. Its per-click mint is a development
convenience, not a public production distribution scheme. It does not exist in the
normal URLconf. Its invitation link opens a fresh `noopener` tab so an earlier
receipt recovery token in the demo tab is preserved without blocking a new trial.
The general holder page still offers explicit token clearing for reused tabs.
`scripts/prepare_unlinked_demo.py` creates this new synthetic round
once and preserves the earlier demo, responses and receipts. It refuses non-demo
settings through the dedicated database guards and does not refresh or reset data.

Loopback links work only on the serving computer. Real mobile scanning, approved
real question wording, retention/erasure, infrastructure logging review, operator
setup wizard and wider instrument/group support remain rollout work. The scoped
operator centre for existing test pools is now described in
`invitation-operator.md`, including one-time batch QR cards and access pause/resume.
