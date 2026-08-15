// ============================================================
// WebRater — Service Worker (Manifest V3)
// Rôle : créer le menu contextuel, récupérer le texte sélectionné,
// interroger le backend, transmettre le résultat au content script.
// ============================================================

// ⚠️ À CONFIGURER : remplacez par l'URL réelle de votre backend une fois déployé.
// En développement local (uvicorn main:app --reload) : "http://localhost:8000/analyze"
const BACKEND_URL = "http://localhost:8000/analyze";

const MIN_CHARS = 50;
const CONTEXT_MENU_ID = "webrater-analyze";

chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.create({
    id: CONTEXT_MENU_ID,
    title: "Analyser le texte avec WebRater",
    contexts: ["selection"]
  });
});

chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== CONTEXT_MENU_ID || !tab?.id) return;
  handleAnalyzeRequest(info, tab);
});

async function handleAnalyzeRequest(info, tab) {
  const selectedText = (info.selectionText || "").trim();

  // Affiche immédiatement la carte en mode "chargement" (feedback instantané)
  await safeSendMessage(tab.id, { type: "WEBRATER_LOADING" });

  // Règle 3 (UI) : blocage local si le texte est trop court, sans appel réseau.
  if (selectedText.length < MIN_CHARS) {
    await safeSendMessage(tab.id, {
      type: "WEBRATER_ERROR",
      message: `Texte trop court pour une analyse fiable (minimum ${MIN_CHARS} caractères).`
    });
    return;
  }

  try {
    const response = await fetch(BACKEND_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: selectedText })
    });

    if (!response.ok) {
      let detail = `Erreur du serveur d'analyse (code ${response.status}).`;
      try {
        const errJson = await response.json();
        if (errJson?.detail) detail = errJson.detail;
      } catch (_) {
        // corps de réponse non-JSON, on garde le message générique
      }
      throw new Error(detail);
    }

    const data = await response.json();

    if (data.status !== "success") {
      throw new Error(data.message || "Réponse invalide du serveur d'analyse.");
    }

    await safeSendMessage(tab.id, { type: "WEBRATER_RESULT", payload: data });
  } catch (err) {
    const isNetworkError = err instanceof TypeError;
    await safeSendMessage(tab.id, {
      type: "WEBRATER_ERROR",
      message: isNetworkError
        ? "Impossible de contacter le serveur d'analyse. Vérifiez votre connexion ou réessayez plus tard."
        : err.message
    });
  }
}

// Le content script peut ne pas encore être injecté (ex. page ouverte avant
// l'installation de l'extension) : on avale l'erreur plutôt que de planter le worker.
async function safeSendMessage(tabId, message) {
  try {
    await chrome.tabs.sendMessage(tabId, message);
  } catch (_) {
    // Pas de content script actif dans cet onglet — rien à faire côté V1.
  }
}
