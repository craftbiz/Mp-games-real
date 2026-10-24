"use strict";

/*
 * Shared browser runtime for all MPGames plugins.
 * Game-specific scripts may use window.MPGamesGame.socket and listen for
 * "mpgames:ready", "platform_match_finished", and their own game events.
 */
(() => {
  const root = document.querySelector("#game-app");
  if (!root) return;

  const serverId = String(root.dataset.serverId || "");
  const gameId = String(root.dataset.gameId || "");
  const userId = String(root.dataset.userId || "");
  const handoffToken = String(root.dataset.handoffToken || "");
  const connection = document.querySelector("#game-connection");
  const connectionText = document.querySelector("#game-connection-text");
  const errorBox = document.querySelector("#game-runtime-error");
  let ready = false;

  function status(message, connected) {
    if (connectionText) connectionText.textContent = message;
    if (connection) {
      connection.classList.toggle("connected", Boolean(connected));
      connection.classList.toggle("disconnected", !connected);
    }
  }

  function showError(message) {
    if (errorBox) errorBox.textContent = String(message || "Game connection error.");
  }

  if (typeof window.io !== "function") {
    status("Socket.IO unavailable", false);
    showError("The multiplayer connection library did not load. Refresh this page.");
    return;
  }

  const socket = window.io({ transports: ["websocket", "polling"] });
  window.MPGamesGame = {
    root,
    socket,
    serverId,
    gameId,
    userId,
    get ready() { return ready; },
    emit(eventName, payload) {
      if (!ready) {
        showError("Your game session is still connecting. Please wait.");
        return false;
      }
      socket.emit(eventName, payload || {});
      return true;
    },
    showError,
    clearError() { if (errorBox) errorBox.textContent = ""; },
  };

  socket.on("connect", () => {
    status("Verifying game session…", false);
    socket.emit("gameplay_join", {
      server_id: serverId,
      handoff_token: handoffToken,
    });
  });

  socket.on("disconnect", () => {
    ready = false;
    status("Reconnecting…", false);
  });

  socket.on("connect_error", () => {
    status("Connection error", false);
    showError("Could not connect to the match. Check your connection and refresh.");
  });

  socket.on("gameplay_joined", data => {
    ready = true;
    status("Connected to match", true);
    window.MPGamesGame.room = data || {};
    window.dispatchEvent(new CustomEvent("mpgames:ready", { detail: data || {} }));
  });

  socket.on("gameplay_error", data => {
    ready = false;
    status("Session rejected", false);
    showError(data?.error || "This gameplay session is invalid or expired.");
  });

  socket.on("room_error", data => showError(data?.error || data?.message || "Room error."));
  socket.on("platform_match_finished", data => {
    window.dispatchEvent(new CustomEvent("mpgames:match-finished", { detail: data || {} }));
  });

  socket.on("server_closed", data => {
    showError(data?.message || "This room has closed.");
    status("Room closed", false);
  });
})();
