# WebRater — Extension (Manifest V3)

## 1. Configurer l'URL du backend

Avant de charger l'extension, déployez d'abord le backend (voir
`backend/README.md`), puis :

1. Ouvrez `background.js` et remplacez la valeur de `BACKEND_URL` par
   `https://VOTRE-URL-BACKEND/analyze`.
2. Ouvrez `manifest.json` et remplacez, dans `host_permissions`, l'URL
   `https://your-backend-url.onrender.com/*` par la vôtre.

Pour tester en local (backend lancé avec `uvicorn`), la valeur par défaut
`http://localhost:8000/analyze` fonctionne déjà.

## 2. Charger l'extension (Chrome, Edge, Brave)

1. Ouvrez `chrome://extensions` (ou l'équivalent Edge/Brave).
2. Activez le **Mode développeur** (en haut à droite).
3. Cliquez sur **Charger l'extension non empaquetée**.
4. Sélectionnez le dossier `extension/`.

## 3. Utiliser

1. Sélectionnez un texte (50 caractères minimum) sur n'importe quelle page.
2. Clic droit → **Analyser le texte avec WebRater**.
3. Une carte flottante apparaît en bas à droite de la page avec le score.

## Structure des fichiers

| Fichier | Rôle |
|---|---|
| `manifest.json` | Déclaration Manifest V3, permissions, icônes |
| `background.js` | Service worker : menu contextuel + appel API |
| `content.js` | Injecte la carte de résultat (Shadow DOM isolé du site) |
| `content.css` | Styles de la carte (chargés dans le Shadow DOM) |
| `icons/` | Icônes 16/48/128 px |
