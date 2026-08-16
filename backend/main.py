import asyncio
import json
import os
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from groq import AsyncGroq
from pydantic import BaseModel
import requests

app = FastAPI(title="WebRater API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Modèles Groq à faire voter
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

# Clés chargées depuis vos variables d'environnement Render
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1", ""),
    os.getenv("GROQ_API_KEY_2", ""),
    os.getenv("GROQ_API_KEY_3", ""),
    os.getenv("GROQ_API_KEY_4", ""),
]

MAX_CHARS_ANALYSIS = 1500  # Limite de tokens
MIN_CHARS = 50


class AnalyzeRequest(BaseModel):
    text: str


def check_web_presence(text: str) -> dict:
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        return {"exists": False, "sources": []}

    snippet = text[:200]
    try:
        res = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": tavily_key,
                "query": snippet,
                "search_depth": "basic",
            },
            timeout=4,
        )
        data = res.json()
        results = data.get("results", [])
        sources = [item["url"] for item in results[:3]]
        return {"exists": len(sources) > 0, "sources": sources}
    except Exception:
        return {"exists": False, "sources": []}


async def query_single_groq(
    model_name: str, api_key: str, text: str, web_info: dict
) -> dict:
    if not api_key:
        return {"score": None, "reason": "Clé API non configurée"}

    client = AsyncGroq(api_key=api_key)
    prompt = f"""
    Analyse le texte suivant pour déterminer s'il est généré par IA.
    Présence Web trouvée : {web_info['exists']} (Sources: {web_info['sources']})

    Texte :
    "{text}"

    Réponds STRICTEMENT sous ce format JSON :
    {{
      "score": <entier entre 0 et 100>,
      "reason": "<courte justification en 1 phrase en français>"
    }}
    """

    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=150,
        )
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)
        return {
            "score": float(data.get("score", 0)) / 100.0,
            "reason": data.get("reason", "Analyse effectuée."),
        }
    except Exception as e:
        return {"score": None, "reason": f"Erreur: {str(e)}"}


@app.post("/analyze")
async def analyze(payload: AnalyzeRequest):
    text = payload.text.strip()
    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Texte trop court (minimum {MIN_CHARS} caractères).",
        )

    # 1. Contrôle de consommation des tokens (tronquage)
    truncated_text = text[:MAX_CHARS_ANALYSIS]

    # 2. Recherche web (parallèle)
    web_info = check_web_presence(truncated_text)

    # 3. Interrogation simultanée des 4 modèles
    tasks = [
        query_single_groq(model, key, truncated_text, web_info)
        for model, key in zip(GROQ_MODELS, GROQ_KEYS)
    ]
    results = await asyncio.gather(*tasks)

    # 4. Calcul du score moyen
    valid_scores = [r["score"] for r in results if r["score"] is not None]
    final_prob = sum(valid_scores) / len(valid_scores) if valid_scores else 0.5

    # 5. Formattage des signaux
    signals = []
    if web_info["exists"]:
        signals.append(
            {
                "name": "Source Web trouvée",
                "description": f"Correspondances détectées sur internet ({len(web_info['sources'])} liens).",
            }
        )

    for idx, r in enumerate(results):
        if r["score"] is not None:
            signals.append(
                {
                    "name": f"{GROQ_MODELS[idx]} ({int(r['score']*100)}%)",
                    "description": r["reason"],
                }
            )

    return {
        "ai_probability": round(final_prob, 4),
        "human_probability": round(1.0 - final_prob, 4),
        "status": "success",
        "signals": signals,
        "sources": web_info["sources"],
    }
