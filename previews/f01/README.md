# F01 respondent design preview

Standalone Thai/English C1 undergraduate prototype. Build with Python standard library:

```powershell
python -B scripts/build_f01_preview.py --output path/to/Nexora-F01-preview.html
```

Open the generated HTML in a browser, or serve its folder with a loopback-only
static file server. No Django setup, database credentials or migrations needed.
The template is a build input; open the generated HTML, not `index.html` directly.

The builder reads the repository catalog and applies stock text replacements
from `indicator_wording.json`, matching the source equality guard in the current
wording preparation service. It does not export custom live catalog edits or
claim that this preview is a published/approved instrument. Only public question
IDs, text, option labels/codes, visibility rules, and illustrative fixed context
are embedded. No scoring keys or formula bindings are included.

Eight sections, 37 definitions: 2 fixed context fields, 27 initially answerable
items, and up to 8 dependent items. C1 study options are years 1–5+.

Latest user policy: only section O (suggestions) is optional. Every other
visible, answerable item must have a valid response, including conditional
cause/text items when shown. Existing explicit no-experience/do-not-know options
remain valid choices. The preview checks again at final confirmation; there is
no override for missing mandatory responses. Hidden follow-ups and fixed context
are excluded. This is enforced in the standalone preview, not yet in Django's
production intake validation. Do not represent the live server as updated.

Revision 02 uses the repository's original logo PNG embedded byte-for-byte,
with purple/pink/gold styling, structured instructions, collapsible review groups,
answer-status cards, an unanswered-item filter, links back to individual items,
and accessible native confirmation dialogs. No image generation or logo edits.

Answers stay in a page-local Map only. No network, cookies or storage APIs are
used; CSP blocks connections and form submissions. Review and finish are local
interactions only. Reloading clears answers. This is not wired into live intake.

Manual verification, 18 September 2026:

- A selected satisfaction rating survives section navigation and appears in review.
- A dissatisfaction answer reveals cause/description fields. Switching to “ไม่มี”
  clears dependent values and excludes them from review and progress.
- Review shows unanswered items; finishing displays an explicit no-save notice.
- Reload restores an empty response state.
- Inspected desktop and 390px mobile viewport; no horizontal overflow on mobile.
- JavaScript syntax check passes. No production database or live template changes.

Revision 02 verification:

- All blank: 26 mandatory missing, 1 optional; final button disabled, no override.
- 26 mandatory items answered with suggestions blank: confirmation allowed.
- Changing a completed dissatisfaction item to Y adds 2 required follow-ups and
  blocks final confirmation again. No hidden stale follow-up values are retained.
- Five automated validation tests pass (required/optional, visibility, whitespace,
  valid non-assessment, invalid values, multiselect and final rechecking).
- Original logo loads; desktop and 390px mobile layouts inspected, including
  review and warning dialog. Mobile document width equals scroll width (375px).

To integrate later, retain server-side branching, validation and anonymous intake;
replace only the agreed presentation after design review. This prototype is not
a substitute for end-to-end checks against an isolated development database.

## Revision 03

Current output: `outputs/Nexora-F01-preview-v3.html` (workspace output, outside
this repo). The preview is now bilingual th/en, using checked-in English drafts
and source-matched indicator wording. The builder fails if any public question
or option lacks English. English is explicitly not publication-approved.
Original logo and mascot bytes are embedded. Native controls, language changes
without losing answers, collapsible navigation, required-only progress, scale
icons, and developer attribution are included.

Completing all required questions opens a DEMO receipt with a real QR matrix and
PNG download. The receipt is intentionally a fixed reusable sample, not issued,
registered or redeemable. It contains no answer values or scores. `demo-qr.svg`
is a checked-in build input; optional regeneration uses ReportLab via
`build_demo_qr.py`. The ordinary HTML builder remains Python stdlib-only.

See workspace `outputs/Nexora-F01-preview-v3-notes.md` for verified UI cases and
`outputs/Nexora-participation-design.md` for the proposed invitation/receipt/API
architecture and the current live model's limitations. No production service,
database migration, recipient messaging or deployment occurred.
