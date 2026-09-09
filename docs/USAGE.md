# Usage

The whole app is one screen: a viewer on the left, a rule pane on the right.
Drop a PDF in, add rules, export. What follows is everything that screen does
not say out loud.

- [Adding rules](#adding-rules)
- [Image redaction modes](#image-redaction-modes)
- [What the matching does that you cannot see](#what-the-matching-does-that-you-cannot-see)
- [When the export is refused](#when-the-export-is-refused)
- [Check the output yourself](#check-the-output-yourself)
- [Phone preset region](#phone-preset-region)

---

## Adding rules

Five kinds, which the API groups into two families: geometric, where a rectangle
is handed to the engine, and textual, where the engine has to find the rectangle
first.

| Rule | How you add it | Family |
| --- | --- | --- |
| **Selection** | select text in the viewer, then "Censurer la sélection" / "Redact selection" | geometric |
| **Manual rectangle** | toggle the draw tool and trace over the page | geometric |
| **Whole page** | "Censurer la page" on the current page | geometric |
| **Exact / regex** | type it, with per-rule options: case sensitivity, **Subword**, **Respect accents**, **Multiline** | textual |
| **Preset** | e-mail, phone (libphonenumber-validated, default region `FR`), credit card (Luhn-filtered) | textual |

The distinction matters when something goes wrong: a geometric rule always has
somewhere to apply, a textual one may find nothing to apply to. See
[When the export is refused](#when-the-export-is-refused).

---

## Image redaction modes

One segmented control in the right pane, applying to the whole request.

| Mode | Bitmap images | Vector graphics |
| --- | --- | --- |
| **Aucune** / None | untouched. A black overlay is drawn on top, but the original pixels stay in the file and come back for anyone who removes the overlay | untouched, same caveat |
| **Totale** / Full | any image a rectangle touches is dropped entirely | any path touched is removed |
| **Précise** / Precise *(default)* | only the pixels inside the rectangle are blackened in the bitmap; the rest of the image stays visible | any path touched is removed |

**Précise is the mode that makes flattened and scanned PDFs redactable.**
Without it, the only options on a scan would be losing the whole page or
drawing a black overlay that hides nothing. Its cost: the modified image is
decoded and re-encoded, which is lossy on JPEG-backed images. Pixels outside the
redacted region stay visually identical but not byte-identical.

Vector paths are removed **per path**, not per pixel: a rectangle clipping the
corner of a path removes the whole path.

**One exception overrides the control.** A "Censurer la page" rule always
processes its page in strict mode (image removal plus graphics removal) even if
you picked **Aucune**. A page-wide rule is meant to wipe the page; the
override stops it from quietly leaving images intact under a black overlay.

---

## What the matching does that you cannot see

The rules are not a literal string comparison, and the differences are exactly
the ones that decide whether something gets missed.

- **Sub-word.** Off by default, so a rule for `CAT` leaves `CATCH` alone. That
  is deliberate: matching inside words looks like caution but takes third
  parties with it, a rule for `Dupont` eating `Dupontel`. Punctuation still
  counts as a boundary, so `Dupont` is found in `jean.dupont@example.com` and in
  `Dupont-Martin`. Turn **Subword** on and `CATCH` becomes `CH`: the match is
  then redacted glyph by glyph, not word by word.
- **Accents.** Insensitive by default, so `Leo` also removes `Léo`, on the
  grounds that the accent is an encoding accident rather than a different name.
  **Respect accents** turns that off. The folding is length-preserving, which is
  what keeps the offsets that map a match back to glyphs on the page valid.
- **Several lines.** Always on for exact search and for the phone preset; a
  toggle, off by default, for regex rules. A match may run across consecutive
  lines, but only where they overlap horizontally. Two columns are never fused,
  and that refusal cuts both ways; see the next section.
- **Rotated text.** Glyphs are ordered along the line's reading direction rather
  than left to right. On a quarter-turned line the two disagree, and sorting by
  x selects the wrong glyphs for a partial match.
- **Presets are validated, not merely matched.** A card candidate must pass the
  Luhn checksum, a phone candidate must be accepted by libphonenumber for the
  default region. A long digit string that fails the checksum stays. For phones
  the viewer runs that same validation before highlighting, so a highlighted
  number is one the backend will actually remove.
- **The document is stripped as well as redacted.** Everything that carries text
  outside the page itself goes by default: metadata (Info dictionary and XMP),
  links, annotations, form fields, embedded attachments, bookmark titles,
  document JavaScript and the XFA packet. A bookmark reading "Dossier Dupont"
  used to survive a rule for `Dupont`. The file is written with `garbage=4`, so
  removed objects are physically absent rather than merely unreferenced.
- **Every rectangle is computed from the original file**, before anything is
  removed. Deriving them from a partly redacted document would let an early rule
  hide the text a later one needed to match.
- **Typed patterns run under a time budget** of 10 seconds per request, set by
  `REDACT_REGEX_TIMEOUT`. A pattern that backtracks catastrophically returns an
  error naming it instead of freezing the app.

The API applies the same defaults, so a direct caller who omits an option gets
what the UI would have sent. The table, and why each one is set the way it is,
are in
[SECURITY.md → Rule defaults](SECURITY.md#rule-defaults-what-the-rule-meant-and-the-ui-agrees).

---

## When the export is refused

You get a report instead of a file. Usually that means the rule needs fixing: it
did not cover everything you thought it did.

One case is not a rule problem and reads identically at first glance: a match
that spans a boundary the engine refuses to cross. Two columns of prose, or two
cells of a `Nom | Prénom` table, sit side by side in the flattened text the
audit reads, but the engine will not fuse them. That refusal is what stops it
from redacting unrelated text that merely *looks* contiguous. So a rule for
`Dupont Jean` on such a table finds nothing to remove, the audit finds the
string anyway, and the export is blocked with nothing you can change about the
rule.

The report marks those matches `spans_line_break`, the UI turns that into an
explanation, and the way out is a manual rectangle over each half.

The full list of limits, including the guarantee a preset carries, which is
weaker than the one a typed rule carries, is in
[SECURITY.md → Important Limitations](SECURITY.md#important-limitations).

---

## Check the output yourself

Nothing here asks you to take the audit's word for it. All three commands come
from `poppler-utils`, which is not this project.

```bash
# Is the text really gone, according to a different library?
pdftotext redacted.pdf - | grep -i "the term you redacted"

# Did the image really change, or is there just a black rectangle on top?
pdfimages -png redacted.pdf /tmp/out && ls /tmp/out*

# Metadata, which is stripped by default
pdfinfo redacted.pdf
```

The audit already applies this principle internally: it re-reads the output with
both PyMuPDF and `pypdf`, and either one finding a target is enough to refuse the
export. These commands extend the idea to a third implementation that the project
does not depend on at all.

The first one is the important one: `pdftotext` is poppler, while the redaction
was done by PyMuPDF. If a different implementation cannot find the text either,
that is worth more than an assurance from the tool that removed it. The test
suite does the same thing for the same reason: it reads results back with
`pypdf`, deliberately not the library that wrote them.

---

## Phone preset region

The `phone` preset uses `phonenumbers` to validate candidates. Numbers without a
leading `+` are parsed against a default region, `FR` unless you change it:

```bash
export REDACT_DEFAULT_REGION=US
redactpdf
```

The viewer reads the same value from `/api/config`, so the highlights follow.
A number that is valid in another region and written without its country code is
not detected, and, because the preset audit re-runs the same detector, not
reported either. That is
[limitation 4](SECURITY.md#important-limitations), and it is the reason to
target such content with a search or a rectangle instead.
