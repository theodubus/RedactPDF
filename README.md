# RedactPDF

Outil de caviardage PDF **local et vérifiable** : l’objectif est de **retirer réellement** les données sensibles d’un PDF exporté, et pas seulement de les masquer visuellement.

---

## Pourquoi ce projet ?

Le mot “censure PDF” peut vouloir dire plusieurs choses très différentes en pratique.

- **Masquage visuel (overlay / rectangle noir dessiné)**
  - On voit du noir à l’écran.
  - Mais le texte, l’image ou l’objet d’origine peut rester récupérable.
- **Aplatissement / rasterisation**
  - On convertit la page en image (ou en forme “figée”).
  - Peut réduire la récupérabilité du texte, mais dégrade souvent la qualité et l’accessibilité.
- **Caviardage réel (redaction)**
  - Le contenu ciblé est supprimé de la structure PDF exportée.
  - C’est le mode visé par RedactPDF.

RedactPDF suit une approche “sécurité d’abord” : appliquer la redaction, puis auditer le résultat avant de livrer le PDF exporté.

---

## Fonctionnalités actuelles

### Censure par requêtes
- Recherche exacte
- Regex
- Options de matching (casse, sous-mot/mot entier, accents, etc.)

### Presets
- Emails
- Téléphones
- Cartes bancaires

### Censure visuelle guidée
- Sélection texte au curseur
- Censure de page complète
- Dessin de rectangles (click-glisser)

### Prévisualisation
- Surcouches de preview avant export
- Numérotation des rectangles dessinés pour faciliter le contrôle opérateur

### Durcissement de l’export
- Audit post-redaction (bloque la sortie si fuite détectée)
- Support options de sanitation (métadonnées, annotations, pièces jointes) selon configuration

---

## Limites connues (importantes)

1. **PDF “aplatis” / scans / pages-image**
   - Si le document est essentiellement une image, les stratégies de redaction fine sont plus limitées.
   - Dans certains scénarios, un rectangle qui chevauche une image peut conduire à retirer un objet image entier (si mode strict), ou à un masquage partiel visuel (si mode non strict).

2. **Censure partielle irréversible d’image/vectoriel (fine-grain)**
   - Pas encore implémentée comme workflow natif robuste.
   - Aujourd’hui, on est plutôt sur des modes “supprimer l’objet touché” vs “ne pas le supprimer”, selon options.

3. **OCR hors périmètre de base**
   - Le pipeline de base ne reconstruit pas automatiquement du texte OCR pour scans complexes.

---

## Démarrage rapide (développeurs)

### Prérequis
- Python 3.10+
- Node.js 20+
- npm

### 1) Cloner
```bash
git clone <URL_DU_REPO>
cd RedactPDF
```

### 2) Backend
```bash
pip install -e "backend[dev]"
cd backend
uvicorn app.main:app --reload
```
Backend dispo sur `http://127.0.0.1:8000` (par défaut).

### 3) Frontend
Dans un second terminal:
```bash
cd frontend
npm install
npm run dev
```
Frontend dispo sur `http://127.0.0.1:5173` (ou port affiché par Vite).

---

## Utilisation (opérateur)

1. Charger un PDF.
2. Ajouter des règles (requêtes/regex/presets), ou utiliser:
   - **Censurer la page**
   - **Dessiner sélection** (rectangle)
   - **Sélection texte**
3. Vérifier la preview.
4. Cliquer **Censurer et télécharger**.
5. Si audit KO: corriger les règles et recommencer.

---

## Installation via Docker (sans build local complexe)

Voir le guide détaillé: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Résumé:
- Construire les images backend+frontend,
- Exposer les ports,
- Lancer les services via `docker compose up -d`.

---

## Installation via installeur / exécutable (utilisateur non technique)

Voir le plan détaillé: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

Résumé:
- Fournir un package “un clic” qui:
  - embarque backend + frontend,
  - démarre les services localement,
  - ouvre automatiquement l’URL locale dans le navigateur.

---

## Médias de documentation (placeholders)

Tu peux déposer ici des captures/gifs/vidéos, puis les référencer dans ce README.

Exemples recommandés:

- `docs/media/01-upload-and-preview.gif`
  - Montrer: chargement d’un PDF + preview.
- `docs/media/02-text-selection-redaction.gif`
  - Montrer: sélection texte au curseur puis ajout de règle.
- `docs/media/03-draw-rectangle.gif`
  - Montrer: bouton “Dessiner sélection”, click-glisser, apparition `Rectangle X (Page Y)`.
- `docs/media/04-full-page-redaction.gif`
  - Montrer: “Censurer la page” + preview pleine page.
- `docs/media/05-audit-fail-example.png`
  - Montrer: modal d’échec audit avec détails.
- `docs/media/06-audit-pass-download.png`
  - Montrer: succès + téléchargement.

Tu pourras ensuite ajouter des sections du type:

```md
![Draw rectangle demo](docs/media/03-draw-rectangle.gif)
```

---

## Roadmap / idées d’amélioration

- Censure partielle **irréversible** d’image et de graphiques (sans supprimer l’objet entier)
- Import/export de listes de requêtes de censure (profils réutilisables)
- OCR avancé pour PDFs scannés
- Plus d’outils visuels (édition de rectangles, regroupement, templates)
- E2E tests de bout en bout sur workflows UI complets

---

## Documentation complémentaire

- Sécurité: [docs/SECURITY.md](docs/SECURITY.md)
- Tests: [docs/TESTING.md](docs/TESTING.md)
- Contribution: [CONTRIBUTING.md](CONTRIBUTING.md)
- Déploiement / packaging: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)
- Fixtures PDF de test: [backend/tests/fixtures/README.md](backend/tests/fixtures/README.md)
