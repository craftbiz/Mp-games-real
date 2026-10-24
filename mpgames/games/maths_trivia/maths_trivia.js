"use strict";

(() => {
  const runtime = window.MPGamesGame;
  if (!runtime || runtime.gameId !== "maths_trivia") return;

  const stage = document.querySelector("#game-stage");
  const userId = String(runtime.userId || "");
  let currentQuestion = null;
  let selectedAnswer = null;
  let timerId = null;
  let deadline = 0;

  const text = value => String(value ?? "");

  function node(tag, className, value) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (value !== undefined) el.textContent = text(value);
    return el;
  }

  function clearTimer() {
    if (timerId !== null) {
      window.clearInterval(timerId);
      timerId = null;
    }
  }

  function renderScores(scores, heading) {
    const section = node("section", "mt-score-panel");
    section.appendChild(node("h3", "", heading || "Scores"));
    const list = node("ol", "mt-score-list");
    [...(scores || [])]
      .sort((a, b) => Number(b.score) - Number(a.score))
      .forEach((player, index) => {
        const row = node("li", "mt-score-row");
        row.append(
          node("span", "mt-score-name", `${index + 1}. ${player.username || "Player"}`),
          node("strong", "mt-score-value", player.score)
        );
        list.appendChild(row);
      });
    section.appendChild(list);
    return section;
  }

  function renderQuestion(question) {
    clearTimer();
    currentQuestion = question;
    selectedAnswer = null;
    deadline = Date.now() + Number(question.seconds || 5) * 1000;
    runtime.clearError();
    stage.replaceChildren();

    const card = node("section", "mt-question-card");
    const top = node("div", "mt-question-top");
    top.append(
      node("span", "mt-question-number", `QUESTION ${question.number}`),
      node("span", "mt-clock", "")
    );
    const clock = top.lastElementChild;
    clock.id = "mt-clock";

    const prompt = node("h2", "mt-prompt", question.prompt);
    const choices = node("div", "mt-choices");
    choices.setAttribute("role", "group");
    choices.setAttribute("aria-label", "Answer choices");

    const status = node("p", "mt-answer-status",
      "Choose one answer. Your first answer is final.");
    status.id = "mt-answer-status";
    status.setAttribute("aria-live", "polite");

    question.choices.forEach(value => {
      const button = node("button", "mt-choice", value);
      button.type = "button";
      button.dataset.answer = String(value);
      button.addEventListener("click", () => {
        if (selectedAnswer !== null || !runtime.ready) return;
        selectedAnswer = Number(value);
        choices.querySelectorAll("button").forEach(item => {
          item.disabled = true;
          if (item === button) item.classList.add("mt-selected");
        });
        status.textContent = "Submitting your answer…";
        runtime.emit("maths_trivia_answer", { answer: selectedAnswer });
      });
      choices.appendChild(button);
    });

    card.append(top, prompt, choices, status);
    stage.appendChild(card);
    if (question.scores) stage.appendChild(renderScores(question.scores, "Current scores"));

    function updateClock() {
      const remaining = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
      clock.textContent = `${remaining}s`;
      if (remaining <= 0) {
        choices.querySelectorAll("button").forEach(button => { button.disabled = true; });
        clearTimer();
        if (selectedAnswer === null) {
          status.textContent = "Time is up. Waiting for the answer reveal…";
        }
      }
    }
    updateClock();
    timerId = window.setInterval(updateClock, 200);
  }

  function showWaiting(message) {
    clearTimer();
    stage.replaceChildren(node("div", "mt-waiting", message || "Waiting for the first question…"));
  }

  window.addEventListener("mpgames:ready", () => {
    showWaiting("Connected. Waiting for the game engine to begin…");
  });

  runtime.socket.on("maths_trivia_question", question => renderQuestion(question));

  runtime.socket.on("maths_trivia_answer_status", data => {
    const status = document.querySelector("#mt-answer-status");
    if (status && data?.accepted) {
      status.textContent = "Answer locked. You cannot change it for this question.";
    }
  });

  runtime.socket.on("maths_trivia_error", data => {
    const status = document.querySelector("#mt-answer-status");
    const message = data?.error || "Your answer could not be accepted.";
    if (status) status.textContent = message;
    else runtime.showError(message);
  });

  runtime.socket.on("maths_trivia_reveal", data => {
    clearTimer();
    const card = stage.querySelector(".mt-question-card");
    if (!card) return;

    card.querySelectorAll(".mt-choice").forEach(button => {
      button.disabled = true;
      if (Number(button.dataset.answer) === Number(data.correct_answer)) {
        button.classList.add("mt-correct");
      } else if (selectedAnswer !== null &&
                 Number(button.dataset.answer) === selectedAnswer) {
        button.classList.add("mt-incorrect");
      }
    });

    const status = document.querySelector("#mt-answer-status");
    const myAnswer = data.answers?.[userId];
    if (!myAnswer) {
      status.textContent = `Time's up. The correct answer was ${data.correct_answer}.`;
    } else if (myAnswer.correct) {
      status.textContent = `Correct! +10 points. Answer: ${data.correct_answer}.`;
    } else {
      status.textContent = `Incorrect. −1 point. Correct answer: ${data.correct_answer}.`;
    }

    if (data.scores) {
      stage.querySelector(".mt-score-panel")?.remove();
      stage.appendChild(renderScores(data.scores, "Scores"));
    }
  });

  runtime.socket.on("maths_trivia_finished", data => {
    clearTimer();
    stage.replaceChildren();
    const result = node("section", "mt-finished");
    result.appendChild(node("h2", "", "Match complete!"));

    let reason = "The match has ended.";
    if (data?.reason === "question_limit") reason = "The configured question limit was reached.";
    if (data?.reason === "time_limit") reason = "The configured match duration has ended.";
    if (data?.reason === "not_enough_players") reason = "Not enough players connected to gameplay.";
    result.appendChild(node("p", "muted", reason));

    const winner = data?.scores?.[0];
    if (winner) result.appendChild(node("p", "mt-winner", `Top player: ${winner.username}`));
    result.appendChild(renderScores(data?.scores, "Final leaderboard"));
    stage.appendChild(result);
  });

  runtime.socket.on("platform_match_finished", data => {
    if (data?.game_slug === "maths_trivia") {
      runtime.clearError();
    }
  });

  showWaiting("Verifying your game session…");
})();
