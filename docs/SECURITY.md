# Security Model

## Scope

RedactPDF is a local PDF redaction tool intended to produce a **new exported PDF** where targeted sensitive content is no longer recoverable through standard extraction paths.

## Security Invariants (Non-negotiable)

1. **Never modify the original file**
   - Input PDF must remain untouched.
2. **No fake success**
   - If post-export audit fails, export must be blocked.
3. **Prefer real removal over visual masking**
   - Visual black overlays alone are not sufficient for sensitive workflows.
4. **Operator preview before apply**
   - UI preview is required to reduce human targeting mistakes.

## Current Guarantees (high level)

- Export is done as a new file.
- Redaction is followed by automated audit checks.
- **The audit reads the output with two independent engines**, PyMuPDF and
  `pypdf`, and one match from either is enough to refuse the export. Reading
  back with only the library that performed the redaction would correlate the
  engine's blind spots with the check's: whatever it failed to match, it would
  also fail to find. The report carries an `extractors` map naming each engine
  and whether it ran, on success as well as on failure, because a pass validated
  by one reader is not a pass validated by two.
- Backend supports three image-redaction modes (`none`, `remove`, `pixels`)
  + vector-graphics removal + sanitation of everything that carries text outside
  the page content stream: metadata and XMP, links, annotations, form widgets,
  embedded attachments, **bookmark titles, document JavaScript, `/OpenAction`,
  `/AA` and the XFA packet**. Redaction cleans what is drawn; those objects carry
  text nobody looks at and no geometric rule reaches. Measured before the last
  four were added: a rule for `Dupont` cleaned the page, returned 200, and left
  "Dossier Dupont - confidentiel" sitting in the navigation pane.
- The carrier is dropped whole rather than searched for the target. That is
  blunter and safer: you cannot leak through an object that no longer exists,
  and it does not require sanitation to know the rules.
- The `pixels` image mode rewrites the bitmap of the targeted region (and
  saves with `garbage=4`, removing the orphaned original stream), so it
  works on **flattened / scanned PDFs** where the whole page is one image.

## Image redaction modes

The UI exposes three modes (FR labels in parentheses):

| Mode             | Bitmap images                                                       | Vector graphics              | When to use                                                              |
|------------------|---------------------------------------------------------------------|-------------------------------|---------------------------------------------------------------------------|
| `none` (UI : Aucune / None)  | Untouched. A vector black overlay is drawn on top, visually hidden but the underlying pixels remain in the PDF. | Untouched (same caveat).      | Text-only redaction; you don't care about images.                         |
| `remove` (UI : Totale / Full)| Whole image is dropped from the PDF.                                | All touched paths removed.    | Strict policy: anything touched is gone.                                  |
| `pixels` (UI : Précise / Precise) - **default** | Intersected pixels blackened in the bitmap. The rest of the image stays visible. | All touched paths removed.    | Default. The only mode that makes flattened / scanned PDFs redactable.    |

The image mode also controls vector graphics: `none` keeps them, `pixels`
and `remove` both delete any path touching a redaction rectangle (per-path,
not pixel-perfect, see Limitations below).

Caveat for `pixels`: the modified image is decoded and re-encoded. For
JPEG-based images this re-encoding is **lossy**, pixels outside the
redacted region are not byte-identical to the original (visually
indistinguishable). If your threat model cares about cryptographic hashes
of image bytes, this is worth knowing.

### Defaults are the safe end, not the permissive one

`pixels` (with vector-graphics removal on) is the default **everywhere**, not
just in the UI: a request that omits `options` entirely gets it too. A default
that does not redact is a default that leaks. Better to over-redact and make
the operator run a second pass than to hand back a file that looks redacted
and is not.

That applies here because the intent is not in doubt: someone who puts a
rectangle over an image wants what is under it gone. Where a default has to
guess at intent instead, removing more is not automatically right; see
[Rule defaults](#rule-defaults-what-the-rule-meant-and-the-ui-agrees) below.

### Rule defaults: what the rule meant, and the UI agrees

The UI picks its own matching options and always sends them explicitly, so these
defaults only ever apply to a direct API caller who omits them. That is exactly
what makes them easy to get wrong unnoticed, and the audit cannot catch the
mistake: it replays the same option.

| Rule | Option | API default | UI default |
|---|---|---|---|
| search | `case_sensitive` | `False` | `False` |
| search | `whole_word` | `True` | `True` (**Subword** off) |
| search | `ignore_accents` | `True` | `True` (**Respect accents** off) |
| regex | `case_sensitive` | `False` | `False` |
| regex | `multiline` | `False` | `False` |
| regex | `ignore_accents` | `True` | `True` |

The two entry points now agree on every option, which is one behaviour to learn
instead of two. `backend/tests/test_api_defaults.py` pins them by behaviour
rather than by reading the field, so a flip in either direction fails the suite.

#### The rule is not "remove as much as possible"

That was the first formulation, and it is wrong. The rule is **do what the rule
was asking for**, and only where the intent is genuinely ambiguous fall back on
removing more. The two matching options land on opposite sides of that test,
which is why they do not both point the same way:

- **`ignore_accents=True`.** `Benoit` and `Benoît` are the same name; the accent
  is an encoding accident. Leaving the accented form is a failure to do what was
  asked. Measured before the change: a rule for `Benoit` left `Benoît` in the
  output, returned HTTP 200, and reported nothing, because the audit replayed the
  same accent-sensitive setting. The cost of folding is mild over-redaction, of
  the kind a second pass fixes: a rule for `resume` also removes `résumé`.
- **`whole_word=True`.** `cat` and `catch` are different words. Matching the
  second is not caution, it is damage to a third party: a rule for `Dupont` used
  to take `Dupontel` with it, someone else's name, while the operator believed
  they had targeted one person.

What makes the whole-word default safe rather than a leak is where the
boundaries fall. `build_whole_word_pattern` anchors on `\w`, so `.`, `@`, `-`
and `'` all count as separators. `Dupont` is still found inside
`jean.dupont@example.com`, `Dupont-Martin` and `l'affaire Dupont`. The only shape
it misses is a target glued inside an alphanumeric token, `IDDUPONT123`, which is
rare for the data this tool targets: names, addresses, phone numbers and card
numbers all carry separators. A caller who needs that case turns the option off
explicitly, and the UI exposes it as **Subword**.

#### Fields that do not exist, rather than having a default

Exact search has no `multiline`: it always crosses line breaks, under the same
geometric constraints as the regex engine (see limitation 3 below), because a
multi-word query hyphenated at the end of a line would otherwise be unfindable by
the engine while remaining visible to the audit.

Regex rules have no `whole_word`, deliberately. A regular expression is a precise
instrument and whoever writes one places their own boundaries; the UI implements
its **Subword** toggle for regex rules by wrapping the pattern in
`(?<!\w)…(?!\w)` before sending it. Presets take no matching options at all,
only a page scope.

One default is knowingly left on the permissive side: the optional `audit` block,
where a caller supplies extra patterns that must not appear in the output, is
accent-sensitive. Those patterns are only ever *checked*, never redacted, so a
miss there does not hide a redaction failure; it only declines to raise a flag
the caller asked for.

### Opaque regions: what the rules could not read

An image with no text drawn over it is a region the text rules cannot see. The
detector is geometric: an image is flagged when it covers at least **0.5 %** of
the page and at most **5 %** of its area carries text blocks. The second
threshold is what excludes an image used as a background behind real text, where
the rules read fine.

The size threshold is deliberately low. A false flag costs one thumbnail to look
at; a missing flag costs a leak, which is the same asymmetry that governs every
other default here. Measured: a 40x40 pt logo covers 0.3 % of A4 and is ignored;
the scanned identity block in `docs/demo-invoice.pdf` covers 7.7 % and is
reported, correctly, since it holds a name and an ID number.

Nothing is reported unless a **textual rule** was requested. Without one, the
caller never expected the engine to read anything.

| `options.image_regions` | Behaviour |
|---|---|
| `ignore` | No check. An explicit, named choice, not a silent fallback. |
| `review` *(default)* | Unresolved regions return **HTTP 409** with their coordinates. The caller resends with `acknowledged_regions` to proceed. |
| `block` | Non-interactive. Only a geometric rule covering the region unlocks it; an acknowledgement does not. For scripts, which cannot click. |

#### Fonts whose text cannot be read either

The same failure with a different mechanism. A Type0 font encoded `Identity-H`
maps codes to glyph indices inside that font and to nothing else, so `/ToUnicode`
is the only bridge to Unicode. Without it, extraction returns garbage: measured
on one embedded TrueType, `Jean Dupont 06 12 34 56 78` becomes
`ðĊĆēÆêĚĕĔēęÆÖÜÆ×ØÆÙÚÆÛÜÆÝÞ`. The rule finds nothing, the audit finds nothing,
and the export used to succeed with the name plainly visible on screen.

The criterion is **not** "composite font without `/ToUnicode`". A first version
assumed that and would have fired on every CJK document: registry CMaps such as
`/UniGB-UTF16-H` carry Unicode by themselves and extract correctly with no
`/ToUnicode` at all. Only `Identity-H` / `Identity-V` and Type3 (whose glyphs are
drawing procedures) genuinely need it.

Affected pages are reported alongside opaque regions in the same 409, under
`unreliable_fonts`, and acknowledged by page number rather than by box: the tool
does not know *where* the affected text sits, since it cannot read it. The only
geometric remedy is covering the whole page.

The acknowledgement travels in the request and the server recomputes the regions
to check it against. Left to the client, it would be enough to send nothing.

A region counts as handled only when a **single** rectangle contains it, within
two points on each edge. An earlier version accepted 95 % of the area covered,
which is wrong because area ignores shape: measured on a 320x120 pt scanned
block, a 16 pt strip along one edge stayed under the threshold and silenced the
warning, while a character at 9 pt is about 5x9 pt. Two rectangles meeting in
the middle do not count either, since nothing guarantees they touch and the seam
is exactly where a character survives.

`block` is not a stricter policy than `review`, it is the variant for callers
with no interface. The 409 is distinct from the 400 that means targeted content
survived: a script can tell "unresolved region" from "leak" without parsing the
body.

### Unknown payload keys are rejected

The API refuses any key it does not recognise, with HTTP 422 naming the
offending key. This is deliberate, and stricter than usual REST practice: a
tool whose contract is "we never do less than you asked without saying so"
cannot silently discard an instruction it failed to parse. A request sending
`imageMode` instead of `image_mode` used to return 200 with a black overlay
drawn over a fully intact image; it is now an error.

### Full-page rule overrides image mode

When the user clicks "Censurer la page" (full-page rule), that page is
**always** processed in strict mode (`remove` + graphics removal),
regardless of the global image mode. A page-wide rule is meant to wipe the
page completely; if the user picked `Aucune` on top of it, the strict
override prevents a fake-redaction trap (where images and graphics would
otherwise survive under the black overlay).

Other rules (manual rectangles, selections, search/regex/preset hits)
continue to follow the user's chosen image mode on the same page.

## Important Limitations

1. **Text inside an image is invisible to text rules, and the export says so**
   - Search, regex and preset rules read extracted text. A scan has none, so
     they find nothing, and until 9 September 2026 that produced a successful
     export with the data plainly readable. Measured, not assumed.
   - The export now refuses instead. Before applying anything, each page is
     scanned for **opaque regions**: an image large enough to matter with
     essentially no text drawn over it. The check is purely geometric. It does
     not look inside the image and does not claim to; it answers "is there a
     region here the rules could not read", which stays true whether that region
     holds a scanned table or a photograph.
   - A region already covered by a geometric rule (manual rectangle, whole page)
     is not reported: it is handled. `options.image_regions` decides the rest,
     see [Opaque regions](#opaque-regions-what-the-rules-could-not-read).
   - Only manual rectangles or full-page redaction reliably remove such content.
     Use the `pixels` image mode (or `remove`) so the bitmap actually loses it.
2. **Vector graphics are not pixel-redacted**
   - When a redaction rectangle partially covers a vector path, modes
     `pixels` and `remove` delete the **whole path**, not just the
     intersected portion. Pixel-perfect partial redaction would require
     rasterising the affected vector area, which the project does not do.
3. **Matches split across a boundary the engine will not cross**
   - The geometric engine only merges lines that are vertically adjacent
     and horizontally overlapping. It therefore refuses, on purpose, to
     merge two columns of prose, and it refuses two cells sharing a
     baseline. That refusal is what stops it from redacting unrelated
     text that only *looks* contiguous once flattened.
   - The text-based audit has no geometry: it reads flattened page text,
     where those pieces sit next to each other. A rule whose match spans
     such a boundary therefore fails the audit and blocks the export.
   - This is **not** limited to multiline regex on multi-column PDFs, as
     this document previously claimed. An ordinary whole-word search for
     `Dupont Jean` on a plain two-column `Nom | Prénom` table triggers it,
     with the default UI settings.
   - The export is refused correctly, since the text really is still in the
     output, but no rule of that kind could have removed it. Since the
     failure report is otherwise indistinguishable from a genuine leak,
     it carries `diagnostics: ["line_break_split"]` and a per-match
     `spans_line_break` flag, and the UI turns that into an explanation
     plus the action that unblocks: draw a rectangle over each part.
4. **The preset audit is not independent of the preset detector**
   - Audit strength is not uniform across rule types, and the difference is
     structural rather than a bug.
   - A search or regex rule is audited by re-reading the **flattened text**
     of the output and looking for the pattern again. That text comes from
     the extractor, not from the matching engine, so the audit catches both
     a rectangle that failed to apply *and* a match the engine never found.
   - A preset is audited by re-running `find_redaction_rectangles_for_presets`
     on the output PDF: the **same detector, same settings**. It catches a
     rectangle that failed to apply. It cannot catch a **non-detection**: a
     string the detector did not recognise as a phone number on the way in is
     not recognised on the way out either, so nothing is reported.
   - Concretely, with `REDACT_DEFAULT_REGION=FR`, a US number written without
     its country code (`212 736 5000`) is rejected by `phonenumbers`, is
     therefore not redacted, and the export succeeds with the number intact
     and no failure report.
   - The guarantee a preset carries is *no match this detector recognises
     survives the export*, not *no phone number survives the export*. For
     content that must be gone regardless of the detector's coverage, target
     it with a search, a regex, or a rectangle.

5. **Very tight leading damages the line below**
   - Text extraction reports a line box taller than the glyphs it contains.
     `_tighten_rect_vertical` shrinks it so a redaction rectangle does not
     spill onto the following line. Above roughly 1.1 times the font size of
     leading, the shrunk rectangle stays clear.
   - Below that, it does not. Measured at 9 pt: at 3.5 mm of leading the
     tightening is what saves the next line, and at 2.5 mm the next line loses
     words even with it. Fixture `015_tight_leading.pdf` carries both cases and
     `test_tight_leading.py` pins them.
   - The failure is over-redaction, not a leak: content next to the target is
     removed, never left behind. It is still damage the operator did not ask
     for, on a neighbouring line they may not check, so it is written down here
     rather than left to be discovered.
   - Dense tables and payslips are where this shows up. If a document is set
     that tightly, read the exported file before sending it.

## Operational Recommendations

For sensitive usage, prefer strict settings:

- choose image mode `remove` or `pixels` (never `none`) for any document
  containing images or vector graphics that overlap your redaction zones,
- sanitize metadata, remove annotations, remove attachments, these are
  ON by default (server-side, not only in the UI) but can be turned off
  explicitly via the API,
- verify audit output before sharing exported files.

When in doubt about a particular page, "Censurer la page" guarantees a
full strict wipe of that page (see "Full-page rule overrides image mode"
above), even if the global image mode is `Aucune`.

## Production / Multi-user Deployment

RedactPDF is designed for **local, single-user usage**. The HTTP API has no
authentication, no rate limiting and no upload size cap. Regex execution *is*
bounded (see below). Exposing it to untrusted networks or multiple users
without hardening is **not safe**.

If you deploy it behind a reverse proxy (nginx, Caddy, Traefik...) for
multiple users, address the following at the **infrastructure layer**, not
in the application code:

### Body size

Reject oversized PDFs before they reach the worker, otherwise a single
upload can OOM the process (the entire PDF is loaded in memory by
PyMuPDF, streaming is not possible).

- nginx: `client_max_body_size 50m;`
- Caddy: `request_body { max_size 50MB }`

### Rate limiting

Each redaction request runs PyMuPDF + audit on the full PDF. A trivial loop
can saturate CPU.

- nginx: `limit_req_zone $binary_remote_addr zone=redact:10m rate=2r/s;`
- Caddy: rate-limit plugin or Cloudflare in front.

### ReDoS (regex denial of service), handled in the application

This one **is** implemented, unlike the rest of this section, and for a
reason: the main way to run RedactPDF is a local binary, where there is no
deployer to put a reverse proxy in front. Sending the mitigation downstream
would have meant sending it nowhere.

User-supplied patterns run through
[redactpdf/regex_guard.py](../backend/redactpdf/regex_guard.py) on the
`regex` engine rather than `re`, under a **time budget shared by the whole
request** (`REDACT_REGEX_TIMEOUT`, 10 seconds by default). Exceeding it
returns HTTP 400 naming the pattern, instead of leaving the process
spinning.

Two details that motivate the shape of that guard:

- `re` does not release the GIL while matching, so a single pathological
  pattern freezes the whole process, event loop included. A timeout
  enforced by a watchdog thread could never observe it: the interruption
  has to come from inside the matching engine.
- The engine runs patterns line by line, page by page. A per-call timeout
  would be multiplied by the number of lines; a hundred-page document would
  turn a two-second limit into an hour. Hence one budget per request.

Residual risk: a request can still occupy a worker for the length of the
budget. Under a multi-user deployment, combine the budget with rate
limiting below.

### Authentication

There is none. Any request to the backend is processed. Add auth at the
proxy layer (basic auth, OAuth2 proxy, Cloudflare Access, Tailscale, …).

### Container isolation

If running in production, containerize and apply quotas:

- CPU: e.g. `--cpus=2`
- Memory: e.g. `--memory=2g`
- No host filesystem access (PDFs are processed in-memory).

### Scope of these recommendations

With the exception of the regex budget above, these items are **not**
implemented in the application and will not be. RedactPDF stays small and
focused on its redaction job; operating it safely in a multi-user setting is
the responsibility of the deployer. The regex budget is the exception because
the local binary, the main way this tool is used, has no deployer at all.

## Reporting Security Issues

Please open a security issue with:

- minimal reproduction document (if shareable),
- exact steps,
- expected vs actual behavior,
- platform/runtime info.
