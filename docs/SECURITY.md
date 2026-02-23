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

## Reporting Security Issues

Please open a security issue with:

- minimal reproduction document (if shareable),
- exact steps,
- expected vs actual behavior,
- platform/runtime info.
