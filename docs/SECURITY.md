# Security Model (Draft)

## Scope
This project provides a local PDF redaction tool intended to permanently remove sensitive content from PDF files while preserving normal selection/search for non-redacted text.

## Security Invariants (Non-negotiable)
1. **Never modify the original file**  
   The tool must always export a new PDF and must not overwrite the input.

2. **No visual-only masking**  
   Overlays/black rectangles that merely cover content are not acceptable. Redaction must remove underlying data.

3. **Post-export verification is required**  
   The tool must run an automated audit after redaction (at minimum, text extraction + pattern checking).  
   If a forbidden pattern is still found, the tool must fail clearly and must not produce a “successful” output.

4. **Preview before apply (UI requirement)**  
   The UI must provide a preview of the redaction areas before applying changes (to reduce operator errors).

## Out of Scope / Limitations (for now)
- Perfect detection of sensitive data in all PDFs is not guaranteed.
- OCR on scanned PDFs is not in scope initially.
- Multi-line / complex-layout matching will be improved iteratively and must be covered by tests.

## Reporting
If you believe you found a redaction bypass or data leakage issue, please open a security issue with:
- a minimal reproduction PDF (if shareable),
- steps to reproduce,
- expected vs actual behavior.
