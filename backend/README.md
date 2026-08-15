# WebRater — Backend

Microservice FastAPI qui reçoit un texte, interroge un modèle Hugging Face
de détection de texte IA, et renvoie un score `{ai_probability, human_probability}`.

## 1. Lancer en local

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env
# Éditez .env et collez votre clé HF_API_KEY
# (créez-en une sur https://huggingface.co/settings/tokens, droits "Read")

uvicorn main:app --reload --port 8000
```

Testez avec :

```bash
curl -X POST http://localhost:8000/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "Collez ici un texte de 50 caractères ou plus pour tester l'\''analyse."}'
```

## 2. Déployer gratuitement sur Render.com (sans carte bancaire)

1. Poussez le dossier `backend/` sur un dépôt GitHub.
2. Sur [render.com](https://render.com), **New +** → **Web Service** → connectez le dépôt.
3. Configuration :
   - **Runtime** : Python 3
   - **Build Command** : `pip install -r requirements.txt`
   - **Start Command** : `uvicorn main:app --host 0.0.0.0 --port $PORT`
4. Dans **Environment**, ajoutez la variable `HF_API_KEY` (votre clé Hugging Face).
5. Déployez. Render fournit une URL du type `https://webrater-backend.onrender.com`.
6. Reportez cette URL dans `extension/background.js` (`BACKEND_URL`) et dans
   `extension/manifest.json` (`host_permissions`), avec le chemin `/analyze`.

> Le plan gratuit de Render met le service en veille après une période
> d'inactivité : la première requête après une pause peut prendre ~30–50 s
> le temps que le service redémarre.

## Alternative : Cloudflare Tunnel (exposer un serveur local)

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
cloudflared tunnel --url http://localhost:8000
```

Cloudflare fournit une URL publique temporaire pointant vers votre machine —
utile pour des tests rapides sans déploiement permanent.

## Notes de confidentialité et sécurité

- Le texte reçu n'est jamais écrit sur disque ni en base de données ; les
  logs ne contiennent que sa longueur, jamais son contenu.
- La clé Hugging Face n'est lue que depuis la variable d'environnement
  `HF_API_KEY` et n'est jamais renvoyée au client.
- Le modèle par défaut est `Hello-SimpleAI/chatgpt-detector-roberta` ; vous
  pouvez le remplacer via la variable `HF_MODEL` (ex. `roberta-base-openai-detector`).
