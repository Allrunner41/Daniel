// ============================================================
// WebRater — Content Script
// Injecte une carte flottante (Shadow DOM, isolée du CSS du site hôte)
// pour afficher le chargement, une erreur, ou le résultat de l'analyse.
// ============================================================

(() => {
  const HOST_ID = "webrater-shadow-host";
  let stylesLoaded = false;

  async function getShadowRoot() {
    let host = document.getElementById(HOST_ID);
    if (host) {
      // Nettoie le contenu précédent (garde le <style> déjà injecté)
      host.shadowRoot.querySelectorAll(".wr-card").forEach((el) => el.remove());
      return host.shadowRoot;
    }

    host = document.createElement("div");
    host.id = HOST_ID;
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    try {
      const res = await fetch(chrome.runtime.getURL("content.css"));
      style.textContent = await res.text();
    } catch (_) {
      // En cas d'échec de chargement du CSS, la carte reste utilisable mais non stylée.
    }
    shadow.appendChild(style);
    stylesLoaded = true;
    return shadow;
  }

  function closeCard() {
    const host = document.getElementById(HOST_ID);
    if (host) host.remove();
  }

  function baseCardShell(bodyHtml, extraClass = "") {
    const wrapper = document.createElement("div");
    wrapper.className = `wr-card ${extraClass}`.trim();
    wrapper.innerHTML = `
      <div class="wr-header">
        <span class="wr-logo">WebRater</span>
        <button class="wr-close" aria-label="Fermer">&times;</button>
      </div>
      <div class="wr-body">${bodyHtml}</div>
    `;
    wrapper.querySelector(".wr-close").addEventListener("click", closeCard);
    return wrapper;
  }

  async function renderLoading() {
    const shadow = await getShadowRoot();
    const card = baseCardShell(
      `<div class="wr-spinner"></div><p class="wr-loading-text">Analyse en cours…</p>`,
      "wr-loading"
    );
    shadow.appendChild(card);
  }

  async function renderError(message) {
    const shadow = await getShadowRoot();
    const card = baseCardShell(
      `<div class="wr-badge wr-badge-uncertain">⚠ Information</div>
       <p class="wr-error-text">${escapeHtml(message)}</p>`,
      "wr-error"
    );
    shadow.appendChild(card);
  }

  async function renderResult(data) {
    const shadow = await getShadowRoot();

    const aiPct = clampPct(data.ai_probability);
    const humanPct = clampPct(
      data.human_probability !== undefined ? data.human_probability : 1 - data.ai_probability
    );

    let statusLabel, statusClass, fillClass;
    if (aiPct >= 65) {
      statusLabel = "Probablement généré par IA";
      statusClass = "wr-badge-ai";
      fillClass = "wr-fill-ai";
    } else if (aiPct <= 35) {
      statusLabel = "Probablement humain";
      statusClass = "wr-badge-human";
      fillClass = "wr-fill-human";
    } else {
      statusLabel = "Incertain";
      statusClass = "wr-badge-uncertain";
      fillClass = "wr-fill-uncertain";
    }

    const radius = 52;
    const circumference = 2 * Math.PI * radius;
    const offset = circumference - (aiPct / 100) * circumference;

    const bodyHtml = `
      <div class="wr-gauge">
        <svg width="130" height="130" viewBox="0 0 130 130">
          <circle class="wr-gauge-bg" cx="65" cy="65" r="${radius}" />
          <circle class="wr-gauge-fill ${fillClass}" cx="65" cy="65" r="${radius}"
            stroke-dasharray="${circumference}"
            stroke-dashoffset="${circumference}" />
        </svg>
        <div class="wr-gauge-label">
          <span class="wr-gauge-pct">${aiPct}%</span>
          <span class="wr-gauge-sub">probabilité IA</span>
        </div>
      </div>
      <div class="wr-badge ${statusClass}">${statusLabel}</div>
      <div class="wr-scores">
        <div class="wr-score-row">
          <span>IA</span>
          <div class="wr-bar"><div class="wr-bar-fill wr-bar-ai" style="width:0%"></div></div>
          <span>${aiPct}%</span>
        </div>
        <div class="wr-score-row">
          <span>Humain</span>
          <div class="wr-bar"><div class="wr-bar-fill wr-bar-human" style="width:0%"></div></div>
          <span>${humanPct}%</span>
        </div>
      </div>
      <div class="wr-disclaimer">
        <span class="wr-info-icon">ⓘ</span>
        <span>WebRater fournit une estimation algorithmique. Les détecteurs d'IA ne sont pas infaillibles.</span>
      </div>
    `;

    const card = baseCardShell(bodyHtml);
    shadow.appendChild(card);

    // Anime la jauge et les barres après insertion dans le DOM
    requestAnimationFrame(() => {
      const ring = card.querySelector(".wr-gauge-fill");
      const bars = card.querySelectorAll(".wr-bar-fill");
      requestAnimationFrame(() => {
        ring.style.strokeDashoffset = String(offset);
        bars[0].style.width = `${aiPct}%`;
        bars[1].style.width = `${humanPct}%`;
      });
    });
  }

  function clampPct(value) {
    const n = Math.round((Number(value) || 0) * 100);
    return Math.min(100, Math.max(0, n));
  }

  function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
  }

  chrome.runtime.onMessage.addListener((message) => {
    switch (message.type) {
      case "WEBRATER_LOADING":
        renderLoading();
        break;
      case "WEBRATER_ERROR":
        renderError(message.message);
        break;
      case "WEBRATER_RESULT":
        renderResult(message.payload);
        break;
    }
  });
})();
