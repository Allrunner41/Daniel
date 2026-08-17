# WebRater — Backend API

API FastAPI de détection de texte généré par IA et de recherche de plagiat/sources web. Utilisée par l'extension Chrome WebRater.

## 🛠️ Stack Technique

* **Framework** : FastAPI + Uvicorn
* **Détection IA Multi-Modèles** : Client Groq (Llama-3.3-70b, Llama-3.1-8b, Llama-3.2-3b, Gemma2-9b)
* **Analyse Plagiat / Web** : Tavily Search API
* **Fallback & Résilience** : Gestion gracieuse des erreurs et dégradation vers score neutre (0.5) en cas de panne d'API externe.

---

## 🚀 Installation & Configuration

### 1. Prérequis
* Python 3.10+
* Clé API Groq ([console.groq.com](https://console.groq.com))
* Clé API Tavily ([tavily.com](https://tavily.com))

### 2. Dépendances
```bash
pip install -r requirements.txt