import asyncio
import json
import os
import re
from pathlib import Path
from typing import List, Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
from pydantic import BaseModel

# Chargement du .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

app = FastAPI(title="WebRater API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Configuration : chaque modèle est associé à sa propre variable d'environnement
MODEL_CONFIGS = [
    {
        "model": "nvidia/nemotron-3.5-lightning:free",
        "env_key": "OPENROUTER_API_KEY_1",
    },
    {
        "model": "poolside/laguna-s-2.1:free",
        "env_key": "OPENROUTER_API_KEY_2",
    },
    {
        "model": "poolside/laguna-xs-2.1:free",
        "env_key": "OPENROUTER_API_KEY_3",
    },
    {
        "model": "cohere/north-mini-code:free",
        "env_key": "OPENROUTER_API_KEY_4",
    },
]

MAX_CHARS_ANALYSIS = 1500
MIN_CHARS = 50


class AnalyzeRequest(BaseModel):
    text: str


async def check_plagiarism_tavily(text: str) -> dict:
    """Vérifie la présence du texte sur le Web via Tavily Search API."""
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        return {"exists": False, "sources": [], "error": "TAVILY_API_KEY absente"}

    query_text = " ".join(text.split())[:250]

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            response = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": tavily_key,
                    "query": query_text,
                    "search_depth": "basic",
                    "include_answer": False,
                    "max_results": 3,
                },
            )
            if response.status_code != 200:
                return {
                    "exists": False,
                    "sources": [],
                    "error": f"HTTP {response.status_code}",
                }

            data = response.json()
            results = data.get("results", [])

            sources = [
                {
                    "title": item.get("title", "Source Web"),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", "")[:150] + "...",
                }
                for item in results
                if "url" in item
            ]

            return {"exists": len(sources) > 0, "sources": sources}
        except Exception as e:
            return {"exists": False, "sources": [], "error": str(e)}


async def query_single_openrouter(
    client: httpx.AsyncClient, model_name: str, api_key: str, text: str, web_info: dict
) -> dict:
    """Interroge un modèle OpenRouter avec sa propre clé API."""
    if not api_key:
        return {"score": None, "reason": "Clé API non configurée pour ce modèle", "model": model_name}

    sources_str = (
        ", ".join([s["url"] for s in web_info.get("sources", [])])
        if web_info.get("sources")
        else "Aucune"
    )

    prompt = f"""Tu es un expert en détection de texte IA.
Analyse le texte suivant et évalue la probabilité qu'il ait été écrit par une IA (0 = 100% Humain, 100 = 100% IA).

Contexte Web / Plagiat :
- Détecté en ligne : {web_info['exists']}
- Sources trouvées : {sources_str}

Texte à analyser :
"{text}"

Réponds UNIQUEMENT au format JSON strict suivant :
{{"score": 50, "reason": "Explication courte en 1 phrase"}}"""

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "WebRater",
    }

    payload = {
        "model": model_name,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.1,
    }

    try:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers=headers,
            json=payload,
            timeout=10.0,
        )

        if response.status_code != 200:
            return {
                "model": model_name,
                "score": None,
                "reason": f"Erreur HTTP {response.status_code}",
            }

        data = response.json()
        raw_content = data["choices"][0]["message"]["content"].strip()

        # Extraction sécurisée du bloc JSON
        match = re.search(r"\{.*\}", raw_content, re.DOTALL)
        if match:
            raw_content = match.group(0)

        parsed_json = json.loads(raw_content)
        raw_score = float(parsed_json.get("score", 50))
        normalized_score = min(max(raw_score / 100.0, 0.0), 1.0)

        return {
            "model": model_name,
            "score": normalized_score,
            "reason": parsed_json.get("reason", "Analyse réussie."),
        }
    except Exception as e:
        return {"model": model_name, "score": None, "reason": f"Erreur: {str(e)}"}


@app.get("/health")
async def health_check():
    """Vérifie la présence des clés API configurées."""
    keys_status = {
        item["env_key"]: bool(os.getenv(item["env_key"]))
        for item in MODEL_CONFIGS
    }
    tavily_configured = bool(os.getenv("TAVILY_API_KEY"))

    return {
        "status": "online",
        "openrouter_keys": keys_status,
        "tavily_api_configured": tavily_configured,
        "models": [item["model"] for item in MODEL_CONFIGS],
    }


@app.post("/analyze")
async def analyze(payload: AnalyzeRequest):
    text = payload.text.strip()
    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Texte trop court. Minimum {MIN_CHARS} caractères requis.",
        )

    truncated_text = text[:MAX_CHARS_ANALYSIS]

    # 1. Recherche de plagiat
    web_info = await check_plagiarism_tavily(truncated_text)

    # 2. Exécution en parallèle (chaque IA utilise sa clé dédiée)
    sem = asyncio.Semaphore(2)

    async def bound_query(client, item):
        model_name = item["model"]
        api_key = os.getenv(item["env_key"], "")
        async with sem:
            res = await query_single_openrouter(
                client, model_name, api_key, truncated_text, web_info
            )
            await asyncio.sleep(0.1)
            return res

    async with httpx.AsyncClient() as client:
        tasks = [bound_query(client, item) for item in MODEL_CONFIGS]
        results = await asyncio.gather(*tasks)

    # 3. Agrégation des résultats sur les modèles valides
    valid_results = [r for r in results if r["score"] is not None]

    if valid_results:
        final_prob = sum(r["score"] for r in valid_results) / len(valid_results)
    else:
        final_prob = 0.5

    model_votes = []
    for r in results:
        if r["score"] is not None:
            ai_pct = int(r["score"] * 100)
            model_votes.append(
                {
                    "model": r["model"],
                    "ai_percent": ai_pct,
                    "human_percent": 100 - ai_pct,
                    "reason": r["reason"],
                }
            )
        else:
            model_votes.append(
                {
                    "model": r["model"],
                    "ai_percent": None,
                    "human_percent": None,
                    "reason": r["reason"],
                }
            )

    return {
        "status": "success",
        "ai_probability": round(final_prob, 4),
        "human_probability": round(1.0 - final_prob, 4),
        "has_plagiarism": web_info["exists"],
        "sources": web_info["sources"],
        "model_votes": model_votes,
    }