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
    "llama-3.2-3b-preview",
    "gemma2-9b-it",
]

# Récupère la clé principale si les clés individuelles ne sont pas définies
DEFAULT_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_KEYS = [
    os.getenv("GROQ_API_KEY_1") or DEFAULT_KEY,
    os.getenv("GROQ_API_KEY_2") or DEFAULT_KEY,
    os.getenv("GROQ_API_KEY_3") or DEFAULT_KEY,
    os.getenv("GROQ_API_KEY_4") or DEFAULT_KEY,
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
        print(f"Erreur sur le modèle {model_name}: {e}")
        return {"score": None, "reason": f"Indisponible: {str(e)}"}


@app.post("/analyze")
async def analyze(payload: AnalyzeRequest):
    text = payload.text.strip()
    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Texte trop court (minimum {MIN_CHARS} caractères).",
        )

    truncated_text = text[:MAX_CHARS_ANALYSIS]
    web_info = await asyncio.to_thread(check_web_presence, truncated_text)

    tasks = [
        query_single_groq(model, key, truncated_text, web_info)
        for model, key in zip(GROQ_MODELS, GROQ_KEYS)
    ]
    results = await asyncio.gather(*tasks)

    valid_scores = [r["score"] for r in results if r["score"] is not None]
    final_prob = sum(valid_scores) / len(valid_scores) if valid_scores else 0.5

    model_votes = []
    for idx, r in enumerate(results):
        if r["score"] is not None:
            ai_pct = int(r["score"] * 100)
            human_pct = 100 - ai_pct
            model_votes.append(
                {
                    "model": GROQ_MODELS[idx],
                    "ai_percent": ai_pct,
                    "human_percent": human_pct,
                    "reason": r["reason"],
                }
            )

    return {
        "ai_probability": round(final_prob, 4),
        "human_probability": round(1.0 - final_prob, 4),
        "status": "success",
        "has_plagiarism": web_info["exists"],
        "sources": web_info["sources"],
        "model_votes": model_votes,
    }
