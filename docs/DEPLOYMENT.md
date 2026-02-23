# Deployment, Docker and Desktop Packaging (Plan)

Ce document décrit:

1. comment faire tourner RedactPDF avec Docker,
2. comment livrer une expérience “un clic” pour utilisateurs non techniques.

---

## 1) Docker (backend + frontend)

## Objectif
Avoir une commande qui démarre l’application complète localement, de manière reproductible.

## Étapes recommandées

1. **Dockerfile backend**
   - Base Python slim
   - Installation dépendances backend
   - Exécution `uvicorn app.main:app --host 0.0.0.0 --port 8000`

2. **Dockerfile frontend**
   Deux approches:
   - dev: Vite dev server (simple pour debug)
   - prod: build static + serveur web (nginx/caddy)

3. **Reverse proxy / routage API**
   - Le frontend doit appeler le backend via un endpoint stable (`/api/...`)
   - En prod, servir frontend + proxy API depuis un seul host/port est recommandé

4. **docker-compose.yml**
   - Service `backend`
   - Service `frontend`
   - Variables d’env
   - Healthchecks

5. **Volumes (optionnel)**
   - Si besoin d’exports persistants ou logs partagés

6. **Sécurité runtime minimale**
   - user non-root dans les containers
   - images pinées
   - surface réseau minimale

## Commandes cibles (exemple attendu)

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

Puis ouvrir l’URL affichée (ex: `http://localhost:8080`).

---

## 2) Packaging “un seul fichier / un clic”

## Objectif
Permettre à un utilisateur non technique de:
- double-cliquer,
- lancer backend + frontend,
- ouvrir automatiquement le navigateur sur la bonne URL.

## Architecture recommandée

### Option A (recommandée): Shell desktop léger + webview/browser launch

- Un “launcher” desktop (Python/Go/Node) qui:
  1. vérifie ports disponibles,
  2. démarre backend local,
  3. sert frontend buildé (ou lance un mini serveur statique),
  4. ouvre le navigateur par défaut,
  5. surveille les process et les arrête proprement à la fermeture.

### Option B: Application desktop embarquée (Electron / Tauri)

- Embedding UI + process backend intégré.
- Plus lourd, mais UX plus contrôlée.

## Outils packaging possibles

- **Windows**: Inno Setup / NSIS / MSI
- **macOS**: `.app` + notarization
- **Linux**: AppImage / deb / rpm

## Points à gérer impérativement

1. **Cycle de vie process**
   - start/stop propre backend+frontend
2. **Mises à jour**
   - stratégie de versioning, migration
3. **Logs support**
   - emplacement clair pour diagnostic
4. **Conflits de ports**
   - fallback automatique (port alternatif)
5. **Durcissement local**
   - bind localhost uniquement

---

## 3) Validation minimale avant diffusion

- Smoke tests:
  - chargement PDF
  - redaction requête
  - redaction rectangle
  - redaction page complète
  - audit fail/pass
- Vérification export sur documents contenant:
  - texte simple
  - images
  - vector graphics
  - annotations / liens / pièces jointes

---

## 4) Notes produit

- Documenter clairement la différence entre:
  - masquage visuel,
  - suppression réelle,
  - limites sur PDFs aplatis / scans.
- Prévoir un mode “strict sécurité” visible dans l’UX pour les cas sensibles.
