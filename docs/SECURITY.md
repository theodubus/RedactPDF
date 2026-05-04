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
- Backend supports strict options for images/graphics + sanitation.

## Important Limitations

1. **Flattened / scanned PDFs**
   - Fine-grained redaction can be constrained.
2. **Partial irrecoverable image/vector editing**
   - Not a fully general “pixel/segment-only rewrite” pipeline at this stage.
3. **OCR completeness**
   - Not guaranteed for all scan/layout conditions.

## Operational Recommendations

For sensitive usage, prefer strict settings:

- remove touched images/graphics,
- sanitize metadata,
- remove annotations,
- remove attachments,
- verify audit output before sharing exported files.

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
PyMuPDF — streaming is not possible).

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
