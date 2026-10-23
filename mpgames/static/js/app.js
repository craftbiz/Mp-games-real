
"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);

  window.MPGames = {
    toast(message, type = "info") {
      const region = $("#toast-region");
      if (!region) return;

      const toast = document.createElement("div");
      toast.className = `toast ${type === "error" ? "toast-error" : ""}`;
      toast.textContent = String(message);
      region.appendChild(toast);

      window.setTimeout(() => toast.remove(), 4000);
    },

    async request(url, options = {}) {
      const response = await fetch(url, {
        credentials: "same-origin",
        ...options,
        headers: {
          Accept: "application/json",
          ...(options.body ? { "Content-Type": "application/json" } : {}),
          ...(options.headers || {})
        }
      });

      let data = {};
      try {
        data = await response.json();
      } catch {
        data = {};
      }

      if (!response.ok) {
        throw new Error(data.error || data.message || `Request failed (${response.status})`);
      }
      return data;
    }
  };

  const profileModal = $("#profile-modal");
  const openProfile = $("#open-profile");
  const closeProfile = $("#close-profile");
  const profileContent = $("#profile-content");

  function showModal(modal) {
    if (!modal) return;
    modal.hidden = false;
    document.body.style.overflow = "hidden";
  }

  function hideModal(modal) {
    if (!modal) return;
    modal.hidden = true;

    if (!document.querySelector(".modal-backdrop:not([hidden])")) {
      document.body.style.overflow = "";
    }
  }

  async function loadProfile() {
    if (!profileContent) return;

    profileContent.replaceChildren();
    const loading = document.createElement("p");
    loading.className = "muted";
    loading.textContent = "Loading profile…";
    profileContent.appendChild(loading);

    try {
      const data = await window.MPGames.request("/api/profile/me");
      const profile = data.profile || data;
      profileContent.replaceChildren();

      const hero = document.createElement("div");
      hero.className = "profile-hero";

      const avatar = document.createElement("div");
      avatar.className = "profile-big-avatar";
      avatar.textContent = String(profile.username || "P").slice(0, 1).toUpperCase();

      const identity = document.createElement("div");
      const name = document.createElement("h3");
      name.textContent = profile.username || "Player";
      const id = document.createElement("p");
      id.className = "muted small";
      id.textContent = `Player ID: ${profile.user_id || "—"}`;

      identity.append(name, id);
      hero.append(avatar, identity);
      profileContent.appendChild(hero);

      const scores = Array.isArray(profile.scores) ? profile.scores : [];
      const highest = scores.reduce(
        (sum, item) => sum + Number(item.highest_score || 0), 0
      );

      const stats = document.createElement("div");
      stats.className = "profile-stat-grid";
      [
        ["Games with scores", String(scores.length)],
        ["Combined best scores", String(highest)]
      ].forEach(([label, value]) => {
        const card = document.createElement("div");
        card.className = "profile-stat";
        const labelEl = document.createElement("span");
        labelEl.textContent = label;
        const valueEl = document.createElement("strong");
        valueEl.textContent = value;
        card.append(labelEl, valueEl);
        stats.appendChild(card);
      });
      profileContent.appendChild(stats);

      const scoresSection = document.createElement("div");
      scoresSection.className = "profile-scores";
      const heading = document.createElement("h3");
      heading.textContent = "Your game scores";
      scoresSection.appendChild(heading);

      if (!scores.length) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "No saved scores yet. Play a game to get started!";
        scoresSection.appendChild(empty);
      } else {
        scores.forEach(item => {
          const row = document.createElement("div");
          row.className = "profile-score-row";

          const game = document.createElement("span");
          game.textContent = item.game_name || item.game_slug || "Game";

          const score = document.createElement("strong");
          score.textContent = String(item.highest_score ?? 0);

          row.append(game, score);
          scoresSection.appendChild(row);
        });
      }

      profileContent.appendChild(scoresSection);
    } catch (error) {
      profileContent.replaceChildren();
      const message = document.createElement("p");
      message.className = "form-error";
      message.textContent = error.message || "Couldn't load your profile.";
      profileContent.appendChild(message);
    }
  }

  openProfile?.addEventListener("click", async () => {
    showModal(profileModal);
    await loadProfile();
  });

  closeProfile?.addEventListener("click", () => hideModal(profileModal));

  profileModal?.addEventListener("click", event => {
    if (event.target === profileModal) hideModal(profileModal);
  });

  // Allow other page scripts to use the same modal helpers.
  window.MPGames.showModal = showModal;
  window.MPGames.hideModal = hideModal;

  document.addEventListener("keydown", event => {
    if (event.key !== "Escape") return;
    document.querySelectorAll(".modal-backdrop:not([hidden])").forEach(hideModal);
  });
})();
