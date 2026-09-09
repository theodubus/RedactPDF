# Composants tiers redistribués

RedactPDF est sous AGPL-3.0 (voir `LICENSE.md` à la racine). Les éléments
ci-dessous sont redistribués avec l'application sous leur propre licence.

## Données de langue Tesseract

`backend/redactpdf/_tessdata/*.traineddata`, variante `tessdata_fast` du projet
Tesseract OCR.

- Licence : Apache License 2.0, texte complet dans `Apache-2.0.txt`
- Copyright 1988-1995 Hewlett-Packard Company
- Copyright 2006-2022 Google Inc.
- Source : <https://github.com/tesseract-ocr/tessdata_fast>

L'Apache-2.0 est compatible avec l'AGPL-3.0 dans ce sens : du code sous
Apache-2.0 peut être inclus dans une œuvre sous GPLv3 ou AGPLv3, l'inverse
n'étant pas vrai. Détail de provenance et empreintes dans
`backend/redactpdf/_tessdata/PROVENANCE.md`.
