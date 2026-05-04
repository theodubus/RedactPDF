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
3. **Cross-column multiline regex**
   - The geometric engine deliberately refuses to fuse lines across
     columns. The text-based audit, however, runs on a flattened page text
     and may match across columns. Multiline regex on multi-column PDFs
     can therefore produce a 400 audit-fail even when nothing was
     legitimately to redact.

## Operational Recommendations

For sensitive usage, prefer strict settings:

- choose image mode `remove` or `pixels` (never `none`) for any document
  containing images or vector graphics that overlap your redaction zones,
- sanitize metadata, remove annotations, remove attachments, these are
  ON by default in the UI but can be turned off via the API,
- verify audit output before sharing exported files.

When in doubt about a particular page, "Censurer la page" guarantees a
full strict wipe of that page (see "Full-page rule overrides image mode"
above), even if the global image mode is `Aucune`.

## Production / Multi-user Deployment

RedactPDF is designed for **local, single-user usage**. The HTTP API has no
authentication, no rate limiting, no upload size cap, and no regex execution
timeout. Exposing it to untrusted networks or multiple users without
hardening is **not safe**.

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

### ReDoS (regex denial of service)

The `/redact/apply` endpoint accepts user-supplied regex patterns and
compiles them with Python's `re` module **without timeout**. A malicious
pattern (catastrophic backtracking, e.g. `(a+)+$`) can hang a worker
indefinitely.

Mitigations:

- Set a strict `proxy_read_timeout` on the reverse proxy (e.g. 30s) so the
  client connection drops, but the worker can still be wedged. Combine with
  a process supervisor that recycles stuck workers.
- Or run the backend in a sandboxed container with strict CPU/memory
  limits and an external watchdog.
- Or switch the regex engine to one that supports timeouts (e.g.
  `regex` package with `re.TIMEOUT`, or `re2`).

### Authentication

There is none. Any request to the backend is processed. Add auth at the
proxy layer (basic auth, OAuth2 proxy, Cloudflare Access, Tailscale, …).

### Container isolation

If running in production, containerize and apply quotas:

- CPU: e.g. `--cpus=2`
- Memory: e.g. `--memory=2g`
- No host filesystem access (PDFs are processed in-memory).

### Scope of these recommendations

These items are **not** implemented in the application and will not be.
RedactPDF stays small and focused on its redaction job; operating it safely
in a multi-user setting is the responsibility of the deployer.

## Reporting Security Issues

Please open a security issue with:

- minimal reproduction document (if shareable),
- exact steps,
- expected vs actual behavior,
- platform/runtime info.
