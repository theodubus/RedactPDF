# Données de langue Tesseract

Ces fichiers sont embarqués pour que la fonction « proposer des zones dans les
images » marche sans rien installer. Le moteur, lui, est déjà dans PyMuPDF
(`_mupdf.so`), il n'y a donc ni binaire ni bibliothèque native à ajouter : seules
ces données manquaient.

## Origine

Variante `tessdata_fast`, dépôt <https://github.com/tesseract-ocr/tessdata_fast>,
branche `main`, récupérée le 9 septembre 2026. Les empreintes sont dans
`SHA256SUMS` et se revérifient avec :

```bash
curl -sSLO https://raw.githubusercontent.com/tesseract-ocr/tessdata_fast/main/fra.traineddata
sha256sum -c SHA256SUMS
```

Vérifié à l'ajout : ces fichiers sont identiques bit pour bit à ceux des paquets
Debian `tesseract-ocr-fra` et `tesseract-ocr-eng` d'Ubuntu 24.04.

## Pourquoi `fast` et pas `best`

Mesuré sur un relevé de notes scanné, en français : `tessdata_best` (19 Mo) ne
lit pas un mot de plus que `tessdata_fast` (5 Mo) et met 4,92 s au lieu de
1,21 s. Quatre fois plus lent, quatre fois plus lourd, aucun gain.

## Pourquoi seulement `fra` et `eng`, pour le moment

Ce sont les deux langues du projet, et le couple `fra+eng` a été mesuré
strictement meilleur que `fra` seul, y compris sur du texte français : le modèle
français seul lisait « BULLE CUT » là où le couple lit « BULLETIN CUMULATIF ».

Ce choix n'est pas définitif. Il tient à ce qu'on sait des utilisateurs
aujourd'hui, pas à une limite technique : ajouter une langue, c'est déposer son
`.traineddata` ici et l'ajouter à `SHA256SUMS`. Une langue installée sur la
machine hôte est de toute façon utilisable, la détection système reste en repli.

## Licence

Apache License 2.0. Copyright 1988-1995 Hewlett-Packard Company, 2006-2022
Google Inc. Le texte de la licence est dans `licenses/Apache-2.0.txt` à la racine
du dépôt.
