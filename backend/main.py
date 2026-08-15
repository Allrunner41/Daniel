"""
WebRater — Backend API (FastAPI)

Rôle : recevoir un texte depuis l'extension, interroger un modèle de
détection de texte IA sur Hugging Face, et renvoyer un score structuré.

Confidentialité (Règle 1) : le texte analysé n'est JAMAIS écrit sur disque
ni dans une base de données. Les logs ne contiennent que des métadonnées
techniques (longueur du texte, code de statut) — jamais le contenu.

Sécurité (Règle 2) : la clé Hugging Face est lue uniquement depuis une
variable d'environnement (HF_API_KEY), jamais codée en dur ni renvoyée
au client.
"""

import logging
import os
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

HF_API_KEY = os.environ.get("HF_API_KEY", "")
# Modèle multilingue par défaut (supporte le français, l'anglais, etc.)
HF_MODEL = os.environ.get(
    "HF_MODEL", "Frederic/french-chatgpt-detector"
)
HF_ROUTER_URL = f"https://router.huggingface.co/hf-inference/models/{HF_MODEL}"

MIN_CHARS = 50
REQUEST_TIMEOUT = 30  # secondes

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("webrater")

app = FastAPI(title="WebRater API", version="1.0.0")

# CORS ouvert pour la V1. Le service worker de l'extension contourne déjà les
# restrictions CORS via host_permissions, mais ceci facilite les tests directs.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
    text: str = Field(..., description="Texte sélectionné à analyser")


class AnalyzeResponse(BaseModel):
    ai_probability: float
    human_probability: float
    status: str


@app.get("/")
def root():
    return {"status": "WebRater API en ligne"}


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(payload: AnalyzeRequest):
    text = payload.text.strip()

    # Log de métadonnées uniquement — jamais le contenu du texte (Règle 1).
    logger.info("Requête d'analyse reçue (%d caractères)", len(text))

    if len(text) < MIN_CHARS:
        raise HTTPException(
            status_code=422,
            detail=f"Texte trop court pour une analyse fiable (minimum {MIN_CHARS} caractères).",
        )

    raw_result = _call_huggingface(text)
    ai_prob, human_prob = _parse_hf_output(raw_result)

    return AnalyzeResponse(
        ai_probability=round(ai_prob, 4),
        human_probability=round(human_prob, 4),
        status="success",
    )


def _call_huggingface(text: str) -> object:
    if not HF_API_KEY:
        raise HTTPException(
            status_code=500,
            detail="Clé API Hugging Face manquante côté serveur (variable HF_API_KEY).",
        )

    headers = {
        "Authorization": f"Bearer {HF_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "inputs": text,
        "parameters": {"function_to_apply": "softmax"},
    }

    try:
        response = requests.post(
            HF_ROUTER_URL, headers=headers, json=payload, timeout=REQUEST_TIMEOUT
        )
    except requests.exceptions.RequestException as exc:
        logger.error("Erreur réseau lors de l'appel à Hugging Face: %s", exc)
        raise HTTPException(
            status_code=502, detail="Impossible de joindre le service d'analyse."
        )

    if response.status_code == 503:
        # Le modèle est en cours de chargement côté infrastructure Hugging Face.
        raise HTTPException(
            status_code=503,
            detail="Le modèle d'analyse démarre, réessayez dans quelques secondes.",
        )

    if not response.ok:
        logger.error(
            "Réponse Hugging Face non-OK: %s - %s",
            response.status_code,
            response.text[:200],
        )
        raise HTTPException(
            status_code=502, detail="Le service d'analyse a renvoyé une erreur."
        )

    return response.json()


def _parse_hf_output(raw: object) -> Tuple[float, float]:
    scores = raw
    if isinstance(scores, list) and scores and isinstance(scores[0], list):
        scores = scores[0]

    if not isinstance(scores, list):
        logger.error("Format de réponse Hugging Face inattendu.")
        raise HTTPException(
            status_code=502, detail="Format de réponse inattendu du modèle."
        )

    ai_prob: Optional[float] = None
    human_prob: Optional[float] = None

    for item in scores:
        label = str(item.get("label", "")).lower()
        try:
            score = float(item.get("score", 0))
        except (TypeError, ValueError):
            continue

        # Prise en compte des labels IA (RoBERTa, XLM, BERT, LABEL_1, etc.)
        if any(
            k in label
            for k in (
                "fake",
                "generated",
                "chatgpt",
                "gpt",
                "ai",
                "label_1",
                "machine",
                "artificial",
            )
        ):
            ai_prob = score
        # Prise en compte des labels Humain
        elif any(
            k in label for k in ("real", "human", "label_0", "original")
        ):
            human_prob = score

    if ai_prob is None and human_prob is not None:
        ai_prob = 1 - human_prob
    if human_prob is None and ai_prob is not None:
        human_prob = 1 - ai_prob

    if ai_prob is None or human_prob is None:
        logger.error(
            "Impossible d'associer les labels du modèle (%s) à IA/Humain.", scores
        )
        raise HTTPException(
            status_code=502, detail="Impossible d'interpréter le résultat du modèle."
        )

    return ai_prob, human_prob