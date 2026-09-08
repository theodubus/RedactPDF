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
- Backend supports three image-redaction modes (`none`, `remove`, `pixels`)
  + vector-graphics removal + metadata/annotation/attachment sanitation.
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

### Rule defaults: the API is not the UI

The image-mode default above is the same everywhere. The per-rule matching
options are not: the UI picks its own and always sends them explicitly, so a
direct API caller who omits `options` gets the model defaults, which differ.

| Rule | Option | API default | UI default | Removes more |
|---|---|---|---|---|
| search | `case_sensitive` | `False` | `False` | equal |
| search | `whole_word` | `False` | `True` (**Subword** off) | API |
| search | `ignore_accents` | `False` | `True` (**Respect accents** off) | UI |
| regex | `case_sensitive` | `False` | `False` | equal |
| regex | `multiline` | `False` | `False` | equal |
| regex | `ignore_accents` | `False` | `True` | UI |

Exact search has no `multiline` field either: it always crosses line breaks,
under the same geometric constraints as the regex engine (see limitation 3
below). A multi-word query hyphenated at the end of a line would otherwise be
unfindable by the engine while remaining visible to the audit.

Regex rules have no `whole_word` field: the UI implements that option by
wrapping the pattern in `(?<!\w)…(?!\w)` before sending it, so a direct API
caller who wants word boundaries writes them into the pattern. Presets take no
matching options at all, only a page scope.

`whole_word=False` is the safe end: matching inside words removes a superset of
what whole-word matching removes.

`ignore_accents=False` is **not** the safe end, and is a known inconsistency
rather than a considered choice. Accent-insensitive matching is a strict
superset (a rule for `Leo` also removes `Léo`), so the API default currently
removes less than the UI's for the same rule text. Until this is aligned, an
API caller who cares about accented variants must pass `ignore_accents: true`
explicitly; the audit uses the same option, so it will not flag the miss.

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

1. **OCR completeness**
   - Not guaranteed for all scan/layout conditions. Text inside an image is
     not seen by the search/regex/preset rules; only manual rectangles or
     full-page redaction will reliably hide it. Use the `pixels` image mode
     (or `remove`) so the bitmap actually loses the targeted content.
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
