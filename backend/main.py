import asyncio
import json
import os
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

GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
    "mixtral-8x7b-32768",
    "gemma2-9b-it",
]

# Clé de secours si une seule clé est configurée sur Render
DEFAULT_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1", DEFAULT_KEY),
    os.getenv("GROQ_API_KEY_2", DEFAULT_KEY),
    os.getenv("GROQ_API_KEY_3", DEFAULT_KEY),
    os.getenv("GROQ_API_KEY_4", DEFAULT_KEY),
]

MAX_CHARS_ANALYSIS = 1500
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
    Analyse le texte suivant pour déterminer s'il est généré par une IA.
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
        return {"score": None, "reason": f"Erreur modèle: {str(e)}"}


@app.post("/analyze")
async def analyze(payload: AnalyzeRequest):
    text = payload.text.strip()
    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Texte trop court (minimum {MIN_CHARS} caractères).",
        )

    truncated_text = text[:MAX_CHARS_ANALYSIS]

    # 1. Verification Web via Tavily
    web_info = check_web_presence(truncated_text)

    # 2. Exécution parallèle des 4 requêtes Groq
    tasks = [
        query_single_groq(model, key, truncated_text, web_info)
        for model, key in zip(GROQ_MODELS, GROQ_KEYS)
    ]
    results = await asyncio.gather(*tasks)

    # 3. Calcul de la moyenne des scores valides
    valid_scores = [r["score"] for r in results if r["score"] is not None]
    
    if valid_scores:
        final_prob = sum(valid_scores) / len(valid_scores)
    else:
        final_prob = 0.5  # Valeur par défaut en cas d'échec global

    # 4. Construction des signaux d'analyse
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
                    "name": f"{GROQ_MODELS[idx]} ({int(r['score'] * 100)}%)",
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