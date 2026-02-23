# Contributing to RedactPDF

Merci pour ta contribution ❤️

## Objectif du projet

RedactPDF vise un caviardage PDF **réellement destructif** (sur l’export), avec audit post-traitement.

## Principes de contribution

1. **Priorité sécurité**
   - Toute modif qui peut impacter la suppression réelle des données doit être testée.
2. **Ne pas casser l’audit**
   - Si l’audit échoue, l’export ne doit pas être livré comme succès.
3. **Reproductibilité**
   - Favoriser des fixtures déterministes et des tests automatisés.

## Setup local

### Backend
```bash
pip install -e "backend[dev]"
cd backend
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Tests

Voir [docs/TESTING.md](docs/TESTING.md).

En bref:
```bash
cd backend
pytest
ruff check .
```

Frontend:
```bash
cd frontend
npm run build
```

## Pull requests

Merci d’inclure dans la PR:

- **Contexte**: problème observé / besoin métier
- **Solution**: ce qui change techniquement
- **Impact sécurité**: texte/images/graphics/metadata/annotations/attachments
- **Validation**: commandes et résultats
- **Limites** éventuelles

## Zones sensibles (à relire attentivement)

- `backend/app/redaction.py`
- `backend/app/audit.py` et pipeline associé
- `frontend/src/components/PdfViewer.tsx`
- `frontend/src/api.ts`

## Bonnes pratiques produit

- Préférer des comportements explicitement “strict” pour les usages sensibles
- Documenter clairement les limites (PDF aplatis, scans, OCR, etc.)
- Éviter les promesses de sécurité non vérifiées
