
"use strict";

(() => {
  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

  const form = $("#create-room-form");
  if (!form) return;

  const gameSelect = $("#create-game");
  const roomList = $("#room-list");
  const settingsContainer = $("#settings-fields");
  const createError = $("#create-error");
  const maxPlayers = $("#max-players");
  const tabs = $("#game-tabs");

  let games = [];

  const request = (url, options = {}) =>
    window.MPGames.request(url, options);

  function getGame(id) {
    return games.find(game => game.game_id === id);
  }

  function getOptions(field) {
    if (Array.isArray(field.options)) return field.options;
    return String(field.values || "")
      .split(",")
      .map(value => value.trim())
      .filter(Boolean);
  }

  function makeField(field) {
    const wrapper = document.createElement("div");
    wrapper.className = "dynamic-setting";
    wrapper.dataset.fieldId = field.id;

    const label = document.createElement("label");
    label.htmlFor = `setting-${field.id}`;
    label.textContent = field.name || field.id;

    let input;

    if (field.type === "drop-down" || field.type === "select") {
      input = document.createElement("select");

      getOptions(field).forEach(value => {
        const option = document.createElement("option");
        option.value = value;
        option.textContent = value;
        input.appendChild(option);
      });
    } else {
      input = document.createElement("input");

      if (field.type === "numerical_text" || field.type === "number") {
        input.type = "number";
        input.step = "1";
        if (field.min !== undefined) input.min = field.min;
        if (field.max !== undefined) input.max = field.max;
      } else {
        input.type = "text";
      }

      if (field.placeholder) input.placeholder = field.placeholder;
    }

    input.id = `setting-${field.id}`;
    input.name = field.id;
    input.dataset.settingKey = field.id;

    if (field.default !== undefined) {
      input.value = String(field.default);
    }

    input.required = field.required !== false;
    wrapper.append(label, input);

    if (field.description) {
      const help = document.createElement("p");
      help.className = "field-help";
      help.textContent = field.description;
      wrapper.appendChild(help);
    }

    return wrapper;
  }

  function fieldIsVisible(field, values, game) {
    const condition = field.show_when || field.when;
    if (!condition) return true;

    const dependency = condition.field;
    const dependencyField = (game.fields || []).find(
      item => item.id === dependency
    );

    const actual = values[dependency] ??
      dependencyField?.default ?? "";

    return String(actual) === String(condition.equals);
  }

  function currentSettings() {
    const result = {};

    $$("#settings-fields [data-setting-key]").forEach(input => {
      const wrapper = input.closest(".dynamic-setting");
      if (wrapper?.hidden || input.disabled) return;

      if (input.type === "number" && input.value.trim() === "") {
        return;
      }

      result[input.dataset.settingKey] =
        input.type === "number" ? Number(input.value) : input.value;
    });

    return result;
  }

  function updateConditionalFields() {
    const game = getGame(gameSelect.value);
    if (!game) return;

    const values = {};
    $$("#settings-fields [data-setting-key]").forEach(input => {
      values[input.dataset.settingKey] = input.value;
    });

    (game.fields || []).forEach(field => {
      const wrapper = [...settingsContainer.querySelectorAll("[data-field-id]")]
        .find(el => el.dataset.fieldId === field.id);

      if (!wrapper) return;

      const visible = fieldIsVisible(field, values, game);
      wrapper.hidden = !visible;

      const input = wrapper.querySelector("[data-setting-key]");
      if (input) {
        input.disabled = !visible;
        input.required = visible && field.required !== false;
      }
    });
  }

  function renderSettings() {
    settingsContainer.replaceChildren();

    const game = getGame(gameSelect.value);
    if (!game) return;

    (game.fields || []).forEach(field => {
      settingsContainer.appendChild(makeField(field));
    });

    const min = Number(game.min_players ?? 1);
    const max = Number(game.max_players ?? 20);

    maxPlayers.min = String(min);
    maxPlayers.max = String(max);
    maxPlayers.value = String(
      Math.max(min, Math.min(max, Number(maxPlayers.value || min)))
    );

    updateConditionalFields();
  }

  function populateGameSelect() {
    const previous = gameSelect.value;
    gameSelect.replaceChildren();

    games.forEach(game => {
      const option = document.createElement("option");
      option.value = game.game_id;
      option.textContent = game.game_name || game.name || game.game_id;
      option.disabled = !game.available;
      gameSelect.appendChild(option);
    });

    if (games.some(game => game.game_id === previous && game.available)) {
      gameSelect.value = previous;
    } else {
      const firstAvailable = games.find(game => game.available);
      if (firstAvailable) gameSelect.value = firstAvailable.game_id;
    }

    $$(".game-tab", tabs || document).forEach(tab => {
      const active = tab.dataset.gameSlug === gameSelect.value;
      tab.classList.toggle("active", active);
    });
  }

  function renderRooms(rooms) {
    roomList.replaceChildren();

    if (!rooms.length) {
      const empty = document.createElement("div");
      empty.className = "empty-state compact";

      const icon = document.createElement("span");
      icon.textContent = "🪑";

      const heading = document.createElement("h3");
      heading.textContent = "No open rooms";

      const message = document.createElement("p");
      message.textContent = "Create a room and invite your friends.";

      empty.append(icon, heading, message);
      roomList.appendChild(empty);
      return;
    }

    rooms.forEach(room => {
      const card = document.createElement("article");
      card.className = "room-card";

      const details = document.createElement("div");
      const heading = document.createElement("h3");
      heading.textContent = room.name || "Untitled room";

      const count = Number(
        room.player_count ??
        room.players_count ??
        (Array.isArray(room.players) ? room.players.length : 0)
      );

      const info = document.createElement("p");
      info.textContent =
        `${room.game_name || room.game_slug || "Game"} · ` +
        `${count}/${room.max_players ?? "?"} players`;

      details.append(heading, info);

      const actions = document.createElement("div");
      actions.className = "room-card-actions";

      const playing = room.status === "playing";
      const full = count >= Number(room.max_players);
      const status = document.createElement("span");

      status.className =
        `status-chip ${playing ? "status-soon" : "status-ready"}`;
      status.textContent = playing ? "IN GAME" : "WAITING";

      const join = document.createElement("a");
      join.className = "button button-secondary button-small";
      join.textContent = "Join room";

      // The server API returns server_id, not id.
      const serverId = room.server_id || room.id;

      if (serverId && !playing && !full) {
        join.href = `/server/${encodeURIComponent(serverId)}`;
      } else {
        join.textContent = playing ? "In game" : full ? "Full" : "Unavailable";
        join.classList.add("button-disabled");
        join.setAttribute("aria-disabled", "true");
      }

      actions.append(status, join);
      card.append(details, actions);
      roomList.appendChild(card);
    });
  }

  async function refreshRooms() {
    roomList.replaceChildren();

    const loading = document.createElement("div");
    loading.className = "loading-state";
    loading.textContent = "Loading rooms…";
    roomList.appendChild(loading);

    try {
      const game = gameSelect.value;
      const query = game ? `?game=${encodeURIComponent(game)}` : "";
      const data = await request(`/api/servers${query}`);

      renderRooms(Array.isArray(data) ? data : (data.servers || []));
    } catch (error) {
      roomList.replaceChildren();

      const message = document.createElement("p");
      message.className = "form-error";
      message.textContent = error.message || "Couldn't load rooms.";
      roomList.appendChild(message);
    }
  }

  async function loadMetadata() {
    try {
      const data = await request("/api/games");
      games = Array.isArray(data) ? data : (data.games || []);

      populateGameSelect();
      renderSettings();
      await refreshRooms();
    } catch (error) {
      createError.textContent =
        error.message || "Couldn't load the game directory.";
    }
  }

  gameSelect.addEventListener("change", () => {
    renderSettings();
    refreshRooms();

    $$(".game-tab", tabs || document).forEach(tab => {
      tab.classList.toggle(
        "active",
        tab.dataset.gameSlug === gameSelect.value
      );
    });
  });

  settingsContainer.addEventListener("change", updateConditionalFields);
  settingsContainer.addEventListener("input", updateConditionalFields);

  $("#refresh-rooms")?.addEventListener("click", refreshRooms);

  tabs?.addEventListener("click", event => {
    const button = event.target.closest("[data-game-slug]");
    if (!button || button.disabled) return;

    const game = getGame(button.dataset.gameSlug);
    if (!game || !game.available) return;

    gameSelect.value = game.game_id;
    $$(".game-tab", tabs).forEach(tab => {
      tab.classList.toggle("active", tab === button);
    });

    renderSettings();
    refreshRooms();
  });

  form.addEventListener("submit", async event => {
    event.preventDefault();
    createError.textContent = "";

    const game = getGame(gameSelect.value);
    if (!game || !game.available) {
      createError.textContent = "This game is not available yet.";
      return;
    }

    const submit = form.querySelector('[type="submit"]');
    const originalText = submit.textContent;

    submit.disabled = true;
    submit.textContent = "Creating room…";

    try {
      const payload = {
        game_slug: game.game_id,
        name: $("#room-name").value.trim(),
        max_players: Number(maxPlayers.value),
        settings: currentSettings()
      };

      const data = await request("/api/servers", {
        method: "POST",
        body: JSON.stringify(payload)
      });

      const serverId = data.server?.server_id || data.server?.id;
      const roomUrl = data.url ||
        (serverId ? `/server/${encodeURIComponent(serverId)}` : null);

      if (!roomUrl) {
        throw new Error("The server did not return a room URL.");
      }

      window.location.assign(roomUrl);
    } catch (error) {
      createError.textContent =
        error.message || "Couldn't create the room.";
      submit.disabled = false;
      submit.textContent = originalText || "Create room";
    }
  });

  loadMetadata();
})();
