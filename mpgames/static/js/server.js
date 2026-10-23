
"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);

  const root = $("#room-app");
  if (!root) return;

  const SERVER_ID = root.dataset.serverId;
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

  let room = null;
  let players = [];
  let connected = false;
  let started = false;
  let currentOwnerId = "";
  let minPlayers = 2;

  function text(value) {
    return String(value ?? "");
  }

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
        user_id: player.user_id || id,
        ...player
      }));
    }
    return [];
  }

  function normalizeRoom(data) {
    return data?.server || data?.room || data || {};
  }

  function isOwner() {
    if (room?.is_owner !== undefined) return Boolean(room.is_owner);
    if (room?.owner_id !== undefined && USER_ID) {
      return String(room.owner_id) === String(USER_ID);
    }
    if (currentOwnerId && USER_ID) {
      return String(currentOwnerId) === String(USER_ID);
    }
    return false;
  }

  function renderRoom(data) {
    room = normalizeRoom(data);

    const id = room.id || room.server_id || SERVER_ID;
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
    $("#info-capacity").textContent = limit ? `${players.length}/${limit}` : "—";
    playerCount.textContent = String(players.length);
    playerLimit.textContent = limit ? ` / ${limit} players` : " players";
    $("#players-heading-count").textContent = `(${players.length})`;

    const playing = room.status === "playing" || started;
    roomStatus.textContent = playing ? "IN GAME" : "WAITING";
    roomStatus.className = `status-chip ${playing ? "status-soon" : "status-ready"}`;

    const owner = isOwner();
    startButton.hidden = playing;
    startButton.disabled = !connected || !owner || players.length < minPlayers;
    $("#owner-note").textContent = owner
      ? `You are the owner. At least ${minPlayers} players are required to start.`
      : `Waiting for ${ownerName} to start the match.`;

    if (room.settings && typeof room.settings === "object") {
      const settings = room.settings;
      const quickRules = $("#quick-rule-list");
      if (room.game_slug === "maths_trivia") {
        quickRules.replaceChildren();
        [
          `Answer each question before its ${settings.seconds_per_question || 5}-second timer expires.`,
          "Correct answers earn points; incorrect answers lose points.",
          "Your first answer is final.",
          "The match ends at its configured question or time limit."
        ].forEach(item => {
          const li = document.createElement("li");
          li.textContent = item;
          quickRules.appendChild(li);
        });
      }
    }
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
    const empty = $(".chat-system-message", chatMessages);
    if (empty) empty.remove();

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
    root.querySelectorAll("#room-content, #room-hero").forEach(el => {
      el.hidden = true;
    });
    closedPanel.hidden = false;
    $("#room-closed-message").textContent =
      message || "This room is no longer available.";
    startButton.disabled = true;
    setConnection(false, "Room closed");
  }

  const socket = typeof window.io === "function"
    ? window.io({ transports: ["websocket", "polling"] })
    : null;

  if (!socket) {
    setConnection(false, "Socket.IO unavailable");
    window.MPGames?.toast("Socket.IO failed to load. Check your internet connection.", "error");
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

  socket.on("room_chat_message", data => {
    addChatMessage(data || {});
  });

  socket.on("server_closed", data => {
    showClosed(data?.message || "The room was closed or expired.");
  });

  socket.on("game_starting", data => {
    started = true;
    roomContent.hidden = true;
    gamePanel.hidden = false;
    startButton.disabled = true;

    const game = data?.game_name || room?.game_name || "Game";
    $("#game-start-title").textContent = `${game} is starting!`;
    $("#game-start-message").textContent =
      "The server has announced the start. Game-specific gameplay controls must be supplied by the corresponding game engine.";
    $("#game-stage").replaceChildren();

    const note = document.createElement("div");
    note.className = "panel";
    note.textContent = "Waiting for the game engine to provide the first question or board…";
    $("#game-stage").appendChild(note);
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
    startError.textContent = data?.message || "The room action failed.";
    startButton.disabled = false;
  });

  $("#leave-room-link")?.addEventListener("click", () => {
    socket.emit("room_leave", { server_id: SERVER_ID });
  });

  $("#open-rulebook")?.addEventListener("click", () => {
    window.MPGames.showModal(rulebookModal);
  });

  $("#close-rulebook")?.addEventListener("click", () => {
    window.MPGames.hideModal(rulebookModal);
  });

  $("#rulebook-done")?.addEventListener("click", () => {
    window.MPGames.hideModal(rulebookModal);
  });

  rulebookModal?.addEventListener("click", event => {
    if (event.target === rulebookModal) {
      window.MPGames.hideModal(rulebookModal);
    }
  });

  $("#back-to-lobby")?.addEventListener("click", () => {
    started = false;
    gamePanel.hidden = true;
    roomContent.hidden = false;
    renderRoom(room || {});
  });

  window.addEventListener("pagehide", () => {
    if (socket.connected) socket.emit("room_leave", { server_id: SERVER_ID });
  });
})();
