# Tesseract language data

These files ship with the package so the "suggest areas found inside images"
feature works with nothing to install. The engine itself already travels inside
PyMuPDF (`_mupdf.so`), so there is no native binary or library to add: only this
data was missing.

## Origin

`tessdata_fast` variant, from <https://github.com/tesseract-ocr/tessdata_fast>,
branch `main`, retrieved on 9 September 2026.

Verified when they were added: these files are bit for bit identical to the ones
in the Debian packages `tesseract-ocr-fra` and `tesseract-ocr-eng` shipped by
Ubuntu 24.04.

## Verifying them

Checksums are in `SHA256SUMS` beside the files, and a test asserts them, because
a mangled model does not raise an error, it simply reads badly.

```bash
curl -sSLO https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/fra.traineddata
curl -sSLO https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/eng.traineddata
sha256sum -c SHA256SUMS
```

## Licence

Apache License 2.0. Copyright 1988-1995 Hewlett-Packard Company, copyright
2006-2022 Google Inc. The licence text is in `licenses/Apache-2.0.txt` at the
repository root, and the attribution notice in `licenses/NOTICE.md`.

## Why this variant, and only these two languages

Both were measured rather than assumed, and the reasoning lives with the rest of
the build decisions in
[docs/DEVELOPMENT.md](../../../docs/DEVELOPMENT.md#the-bundled-language-models),
so it cannot drift between two copies. Adding a language is dropping a
`.traineddata` here and appending its hash to `SHA256SUMS`.
