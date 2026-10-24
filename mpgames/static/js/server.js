
"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const root = $("#room-app");
  if (!root) return;

  const SERVER_ID = root.dataset.serverId || "";
  const USER_ID = root.dataset.userId || "";

  const connection = $("#connection-status");
  const connectionText = $("#connection-text");
  const roomTitle = $("#room-title");
  const roomGame = $("#room-game");
  const roomStatus = $("#room-status");
  const playerCount = $("#player-count");
  const playerLimit = $("#player-limit");
  const playerList = $("#player-list");
  const chatMessages = $("#chat-messages");
  const chatForm = $("#chat-form");
  const chatInput = $("#chat-input");
  const startButton = $("#start-game");
  const startError = $("#start-error");
  const roomContent = $("#room-content");
  const closedPanel = $("#room-closed");
  const gamePanel = $("#game-start-panel");
  const rulebookModal = $("#rulebook-modal");
  const rulebookBody = $("#rulebook-body");

  let room = null;
  let players = [];
  let connected = false;
  let started = false;
  let currentOwnerId = "";
  let minPlayers = 2;
  let gameMetadata = null;
  let leavingIntentionally = false;
  let handoffRequested = false;

  const text = value => String(value ?? "");

  function setConnection(ok, message) {
    connected = ok;
    connection.classList.toggle("connected", ok);
    connection.classList.toggle("disconnected", !ok);
    connectionText.textContent = message;
  }

  function normalizePlayers(value) {
    if (Array.isArray(value)) return value;

    if (value && typeof value === "object") {
      return Object.entries(value).map(([id, player]) => ({
        ...player,
        user_id: player.user_id || id
      }));
    }

    return [];
  }

  function normalizeRoom(data) {
    return data?.server || data?.room || data || {};
  }

  function isOwner() {
    const ownerId = room?.owner_id || currentOwnerId;
    return Boolean(USER_ID && ownerId &&
      String(ownerId) === String(USER_ID));
  }

  function renderRoom(data) {
    room = normalizeRoom(data);

    const id = room.server_id || room.id || SERVER_ID;
    roomTitle.textContent = room.name || "Multiplayer room";
    roomGame.textContent = room.game_name || room.game_slug || "Game";
    $("#room-id-label").textContent = `Room ID: ${id}`;

    currentOwnerId = text(room.owner_id || room.owner_user_id || "");
    minPlayers = Number(room.min_players || room.minimum_players || 2);

    const ownerName = room.owner_name || room.owner_username || "—";
    $("#owner-name").textContent = ownerName;
    $("#info-game").textContent = room.game_name || room.game_slug || "—";
    $("#info-status").textContent = room.status || "waiting";

    const limit = Number(room.max_players || 0);
    $("#info-capacity").textContent =
      limit ? `${players.length}/${limit}` : "—";

    playerCount.textContent = String(players.length);
    playerLimit.textContent = limit ? ` / ${limit} players` : " players";
    $("#players-heading-count").textContent = `(${players.length})`;

    const playing = room.status === "playing" || started;
    roomStatus.textContent = playing ? "IN GAME" : "WAITING";
    roomStatus.className =
      `status-chip ${playing ? "status-soon" : "status-ready"}`;

    const owner = isOwner();
    startButton.hidden = playing;
    startButton.disabled =
      !connected || !owner || players.length < minPlayers;

    $("#owner-note").textContent = owner
      ? `You are the owner. At least ${minPlayers} players are required to start.`
      : `Waiting for ${ownerName} to start the match.`;

    renderCompactRules();
  }

  function renderPlayers(nextPlayers) {
    players = normalizePlayers(nextPlayers);
    playerList.replaceChildren();

    if (!players.length) {
      const empty = document.createElement("div");
      empty.className = "loading-state";
      empty.textContent = "No players are currently in this room.";
      playerList.appendChild(empty);
    } else {
      players.forEach(player => {
        const card = document.createElement("article");
        card.className = "player-card";

        const username = player.username || player.name || "Player";
        const userId = player.user_id || player.id || "";
        const owner = String(userId) === String(currentOwnerId) ||
          Boolean(player.is_owner);
        const self = USER_ID && String(userId) === String(USER_ID);

        const avatar = document.createElement("div");
        avatar.className = "player-avatar";
        avatar.textContent = username.slice(0, 1).toUpperCase();

        const info = document.createElement("div");
        info.className = "player-card-info";

        const name = document.createElement("strong");
        name.textContent = username + (self ? " (you)" : "");

        const role = document.createElement("span");
        role.className = owner ? "owner-badge" : "";
        role.textContent = owner ? "★ Room owner" : "Player";

        info.append(name, role);
        card.append(avatar, info);
        playerList.appendChild(card);
      });
    }

    renderRoom(room || {});
  }

  function addChatMessage(data) {
    $(".chat-system-message", chatMessages)?.remove();

    const item = document.createElement("div");
    item.className = "chat-message";

    const header = document.createElement("div");
    header.className = "chat-message-head";

    const username = document.createElement("strong");
    username.textContent = data.username || data.name || "Player";

    const time = document.createElement("time");
    time.textContent = data.time || data.timestamp || "";

    const message = document.createElement("p");
    message.textContent = text(data.message).slice(0, 500);

    header.append(username, time);
    item.append(header, message);
    chatMessages.appendChild(item);

    while (chatMessages.children.length > 100) {
      chatMessages.firstElementChild?.remove();
    }

    chatMessages.scrollTop = chatMessages.scrollHeight;
  }

  function showClosed(message) {
    $(".room-hero", root)?.setAttribute("hidden", "");
    roomContent.hidden = true;
    gamePanel.hidden = true;
    closedPanel.hidden = false;

    $("#room-closed-message").textContent =
      message || "This room is no longer available.";

    startButton.disabled = true;
    setConnection(false, "Room closed");
  }

  function renderCompactRules() {
    if (!gameMetadata) return;

    const list = $("#quick-rule-list");
    if (!list || !Array.isArray(gameMetadata.rule_book_compact)) return;

    list.replaceChildren();

    gameMetadata.rule_book_compact.forEach(rule => {
      const item = document.createElement("li");
      item.textContent = rule;
      list.appendChild(item);
    });
  }

  function renderDetailedRules() {
    if (!rulebookBody || !gameMetadata) return;

    const sections = gameMetadata.rule_book_detailed;
    if (!Array.isArray(sections)) return;

    rulebookBody.replaceChildren();

    sections.forEach(section => {
      const wrapper = document.createElement("section");
      wrapper.className = "rule-section";

      const heading = document.createElement("h3");
      heading.textContent = section.heading || "Rules";
      wrapper.appendChild(heading);

      (section.paragraphs || []).forEach(paragraph => {
        const p = document.createElement("p");
        p.textContent = paragraph;
        wrapper.appendChild(p);
      });

      if (Array.isArray(section.bullets) && section.bullets.length) {
        const list = document.createElement("ul");

        section.bullets.forEach(bullet => {
          const li = document.createElement("li");
          li.textContent = bullet;
          list.appendChild(li);
        });

        wrapper.appendChild(list);
      }

      rulebookBody.appendChild(wrapper);
    });
  }

  async function loadGameMetadata() {
    try {
      const data = await window.MPGames.request("/api/games");
      const games = Array.isArray(data) ? data : (data.games || []);
      const slug = room?.game_slug;

      gameMetadata = games.find(game =>
        game.game_id === slug || game.slug === slug
      ) || null;

      renderCompactRules();
      renderDetailedRules();
    } catch (error) {
      // The room remains usable if metadata cannot be loaded.
      console.warn("Could not load game rules:", error);
    }
  }

  function showGameplayError(message) {
    gamePanel.hidden = false;
    roomContent.hidden = true;
    $("#game-start-title").textContent = "Preparing the match";
    $("#game-start-message").textContent =
      message || "The server did not provide a gameplay link yet.";
    $("#game-stage").replaceChildren();
  }

  function navigateToGameplay(data) {
    const url = data?.gameplay_url || data?.url || data?.href;

    if (typeof url === "string" && url.startsWith("/")) {
      handoffRequested = true;
      window.location.assign(url);
      return true;
    }

    if (typeof url === "string" && url.startsWith(window.location.origin)) {
      handoffRequested = true;
      window.location.assign(url);
      return true;
    }

    return false;
  }

  function prepareGameplay(data = {}) {
    if (navigateToGameplay(data)) return;
    if (!connected || handoffRequested) return;

    handoffRequested = true;
    showGameplayError("Preparing your game session…");

    socket.emit("prepare_gameplay", {
      server_id: SERVER_ID,
      game_id: room?.game_slug || data.game_id || ""
    });
  }

  const socket = typeof window.io === "function"
    ? window.io({ transports: ["websocket", "polling"] })
    : null;

  if (!socket) {
    setConnection(false, "Socket.IO unavailable");
    window.MPGames?.toast(
      "Socket.IO failed to load. Check your internet connection.",
      "error"
    );
    startButton.disabled = true;
    return;
  }

  socket.on("connect", () => {
    setConnection(true, "Connected");
    socket.emit("room_join", { server_id: SERVER_ID });
  });

  socket.on("disconnect", () => {
    setConnection(false, "Disconnected");
    startButton.disabled = true;
  });

  socket.on("connect_error", () => {
    setConnection(false, "Connection error");
  });

  socket.on("room_state", data => {
    renderRoom(data);

    const normalized = normalizeRoom(data);
    if (normalized.players) renderPlayers(normalized.players);

    loadGameMetadata();
  });

  socket.on("room_players", data => {
    const next = Array.isArray(data) ? data : (data?.players || []);
    if (data?.owner_id) currentOwnerId = text(data.owner_id);
    renderPlayers(next);
  });

  socket.on("room_notice", data => {
    const message = typeof data === "string" ? data : data?.message;
    if (message) window.MPGames?.toast(message);
  });

  socket.on("room_chat_message", data => addChatMessage(data || {}));

  socket.on("server_closed", data => {
    showClosed(data?.message || "The room was closed or expired.");
  });

  socket.on("game_starting", data => {
    started = true;
    startButton.disabled = true;
    roomStatus.textContent = "IN GAME";

    $("#game-start-title").textContent =
      `${data?.game_name || room?.game_name || "Game"} is starting!`;

    prepareGameplay(data || {});
  });

  // Accept the common response event names used by the gameplay handoff.
  [
    "gameplay_handoff",
    "gameplay_ready",
    "gameplay_redirect",
    "gameplay_url",
    "gameplay_prepared"
  ].forEach(eventName => {
    socket.on(eventName, data => {
      if (navigateToGameplay(data || {})) return;

      handoffRequested = false;
      showGameplayError(
        data?.error || data?.message ||
        "The server did not return a valid gameplay URL."
      );
    });
  });

  chatForm?.addEventListener("submit", event => {
    event.preventDefault();

    const message = chatInput.value.trim();
    if (!message || !connected) return;

    socket.emit("room_chat", { message });
    chatInput.value = "";
    chatInput.focus();
  });

  startButton?.addEventListener("click", () => {
    if (!connected || !isOwner()) return;

    startError.textContent = "";
    startButton.disabled = true;
    socket.emit("start_game", { server_id: SERVER_ID });
  });

  socket.on("room_error", data => {
    startError.textContent =
      data?.error || data?.message || "The room action failed.";
    renderRoom(room || {});
  });

  $("#leave-room-link")?.addEventListener("click", event => {
    event.preventDefault();

    if (leavingIntentionally) return;
    leavingIntentionally = true;

    socket.emit("room_leave", { server_id: SERVER_ID });
    socket.disconnect();

    window.setTimeout(() => {
      window.location.assign($("#leave-room-link").href);
    }, 80);
  });

  $("#open-rulebook")?.addEventListener("click", () => {
    window.MPGames?.showModal(rulebookModal);
  });

  $("#close-rulebook")?.addEventListener("click", () => {
    window.MPGames?.hideModal(rulebookModal);
  });

  $("#rulebook-done")?.addEventListener("click", () => {
    window.MPGames?.hideModal(rulebookModal);
  });

  rulebookModal?.addEventListener("click", event => {
    if (event.target === rulebookModal) {
      window.MPGames?.hideModal(rulebookModal);
    }
  });

  // Do not emit room_leave on pagehide. The backend must distinguish an
  // intentional gameplay handoff from a real socket disconnect.
})();
