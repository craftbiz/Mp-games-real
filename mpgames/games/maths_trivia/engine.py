
"""Server-authoritative Maths Trivia engine."""

import math
import random
import time


def make_question():
    kind = random.choice([
        "addition", "subtraction", "multiplication", "division",
        "square", "power", "linear", "percent", "factorial",
        "hcf", "lcm", "remainder", "absolute"
    ])

    if kind == "addition":
        a, b = random.randint(12, 180), random.randint(5, 160)
        prompt, answer = f"{a} + {b} = ?", a + b

    elif kind == "subtraction":
        a, b = random.randint(30, 200), random.randint(5, 29)
        prompt, answer = f"{a} − {b} = ?", a - b

    elif kind == "multiplication":
        a, b = random.randint(4, 25), random.randint(3, 18)
        prompt, answer = f"{a} × {b} = ?", a * b

    elif kind == "division":
        answer, divisor = random.randint(3, 24), random.randint(2, 12)
        prompt = f"{answer * divisor} ÷ {divisor} = ?"

    elif kind == "square":
        a = random.randint(3, 25)
        prompt, answer = f"{a}² = ?", a * a

    elif kind == "power":
        a, exponent = random.randint(2, 6), random.randint(2, 3)
        prompt, answer = f"{a}^{exponent} = ?", a ** exponent

    elif kind == "linear":
        x = random.randint(-8, 12)
        a, b = random.randint(2, 9), random.randint(-15, 15)
        prompt = f"Solve for x: {a}x + ({b}) = {a * x + b}"
        answer = x

    elif kind == "percent":
        percent = random.choice((10, 20, 25, 50, 75))
        if percent in (25, 75):
            base = random.randint(2, 40) * 4
        else:
            base = random.randint(2, 40) * 10
        prompt = f"{percent}% of {base} = ?"
        answer = percent * base // 100

    elif kind == "factorial":
        n = random.randint(3, 7)
        prompt, answer = f"{n}! = ?", math.factorial(n)

    elif kind == "hcf":
        a, b = random.randint(12, 90), random.randint(12, 90)
        prompt, answer = f"HCF({a}, {b}) = ?", math.gcd(a, b)

    elif kind == "lcm":
        a, b = random.randint(2, 15), random.randint(2, 15)
        prompt, answer = f"LCM({a}, {b}) = ?", math.lcm(a, b)

    elif kind == "remainder":
        divisor = random.randint(3, 12)
        number = random.randint(20, 150)
        prompt = f"Remainder when {number} is divided by {divisor}?"
        answer = number % divisor

    else:
        number = random.randint(-100, 100)
        prompt, answer = f"|{number}| = ?", abs(number)

    choices = {answer}
    spread = max(4, min(20, abs(answer) // 3 + 3))

    while len(choices) < 4:
        candidate = answer + random.randint(-spread, spread)
        choices.add(candidate)

    choices = list(choices)
    random.shuffle(choices)

    return {
        "prompt": prompt,
        "choices": choices,
        "correct_answer": answer,
    }


def public_scores(state):
    return [
        {
            "user_id": user_id,
            "username": player["username"],
            "score": player["score"],
        }
        for user_id, player in state["players"].items()
    ]


def finish_match(socketio, server_id, rooms, lock, reason, platform=None):
    with lock:
        room = rooms.get(server_id)
        if not room:
            return

        state = room.get("_maths_trivia")
        if not state or state["finished"]:
            return

        state["finished"] = True
        scores = sorted(
            public_scores(state),
            key=lambda item: (
                -item["score"],
                item["username"].lower()
            )
        )
        state["final_scores"] = scores
        question_number = state["question_number"]
        results = [
            {
                "user_id": item["user_id"],
                "score": item["score"],
                "data": {
                    "username": item["username"],
                    "question_count": question_number,
                    "reason": reason,
                },
            }
            for item in scores
        ]

    if platform is not None and results:
        try:
            platform.submit_results(
                server_id,
                results,
                {
                    "reason": reason,
                    "question_number": question_number,
                    "game_slug": "maths_trivia",
                },
            )
        except Exception as exc:
            socketio.emit(
                "maths_trivia_error",
                {"error": "The match ended, but results could not be saved."},
                to=server_id,
            )
            print(f"[MPGames] Failed to save Maths Trivia results: {exc}", flush=True)

    socketio.emit(
        "maths_trivia_finished",
        {
            "reason": reason,
            "scores": scores,
            "question_number": question_number,
        },
        to=server_id,
    )


def run_match(socketio, server_id, rooms, lock, platform=None):
    # Wait until players have completed the lobby-to-gameplay handoff so the
    # first question is not emitted before the new browser sockets join.
    handoff_deadline = time.monotonic() + 60
    while True:
        socketio.sleep(0.1)
        with lock:
            room = rooms.get(server_id)
            if not room:
                return
            joined = [
                user_id for user_id, player in room["players"].items()
                if player.get("gameplay_joined")
            ]
            all_joined = len(joined) == len(room["players"])
            timed_out = time.monotonic() >= handoff_deadline
            if all_joined or timed_out:
                state = room.get("_maths_trivia")
                if not state or state["finished"]:
                    return
                if timed_out:
                    state["players"] = {
                        user_id: player
                        for user_id, player in state["players"].items()
                        if user_id in joined
                    }
                    state["answers"] = {}
                if len(state["players"]) < 2:
                    should_finish_early = True
                else:
                    should_finish_early = False
                break

    if should_finish_early:
        finish_match(socketio, server_id, rooms, lock, "not_enough_players", platform)
        return

    while True:
        with lock:
            room = rooms.get(server_id)
            if not room:
                return

            state = room.get("_maths_trivia")
            if not state or state["finished"]:
                return

            settings = state["settings"]

            if settings.get("end_condition", "questions") == "questions":
                limit = int(settings.get("question_count", 10))
                should_finish = state["question_number"] >= limit
                finish_reason = "question_limit"
            else:
                should_finish = time.monotonic() >= state["match_deadline"]
                finish_reason = "time_limit"

        if should_finish:
            finish_match(
                socketio, server_id, rooms, lock, finish_reason, platform
            )
            return

        question = make_question()

        with lock:
            room = rooms.get(server_id)
            if not room:
                return

            state = room.get("_maths_trivia")
            if not state or state["finished"]:
                return

            state["question_number"] += 1
            state["question"] = question
            state["answers"] = {}

            now = time.monotonic()
            seconds = int(state["settings"].get(
                "seconds_per_question", 5
            ))
            deadline = now + seconds

            if state["settings"].get("end_condition") == "minutes":
                deadline = min(deadline, state["match_deadline"])

            state["question_deadline"] = deadline

            public_question_data = {
                "number": state["question_number"],
                "prompt": question["prompt"],
                "choices": question["choices"],
                "seconds": max(1, int(deadline - now)),
                "scores": public_scores(state),
            }

        socketio.emit(
            "maths_trivia_question",
            public_question_data,
            to=server_id,
        )

        while True:
            socketio.sleep(0.1)

            with lock:
                room = rooms.get(server_id)
                if not room:
                    return

                state = room.get("_maths_trivia")
                if not state or state["finished"]:
                    return

                active_ids = set(state["players"])
                all_answered = active_ids.issubset(state["answers"])
                expired = time.monotonic() >= state["question_deadline"]

                duration_expired = (
                    state["settings"].get("end_condition") == "minutes"
                    and time.monotonic() >= state["match_deadline"]
                )

                if all_answered or expired or duration_expired:
                    question = state["question"]
                    reveal = {
                        "number": state["question_number"],
                        "correct_answer": question["correct_answer"],
                        "answers": dict(state["answers"]),
                        "scores": public_scores(state),
                    }
                    break

        socketio.emit("maths_trivia_reveal", reveal, to=server_id)
        socketio.sleep(1.5)


def start_match(socketio, server_id, rooms, lock, platform=None):
    """Initialize a match and start its background task."""
    with lock:
        room = rooms.get(server_id)

        if not room or room.get("game_slug") != "maths_trivia":
            return False

        settings = dict(room.get("settings") or {})
        players = {
            str(user_id): {
                "username": player.get("username", "Player"),
                "score": 0,
            }
            for user_id, player in room["players"].items()
        }

        if len(players) < 2:
            return False

        duration = int(settings.get("duration_minutes", 3))

        room["_maths_trivia"] = {
            "settings": settings,
            "players": players,
            "answers": {},
            "question": None,
            "question_number": 0,
            "question_deadline": None,
            "match_deadline": (
                time.monotonic() + duration * 60
                if settings.get("end_condition") == "minutes"
                else None
            ),
            "finished": False,
        }

    socketio.start_background_task(
        run_match, socketio, server_id, rooms, lock
    )
    return True


def submit_answer(server_id, user_id, data, rooms, lock):
    """Validate one answer. Returns an error string or None."""
    data = data if isinstance(data, dict) else {}

    try:
        answer = int(data.get("answer"))
    except (TypeError, ValueError):
        return "Choose one of the available answers."

    with lock:
        room = rooms.get(server_id)
        if not room or room.get("game_slug") != "maths_trivia":
            return "Maths Trivia room not found."

        state = room.get("_maths_trivia")
        if not state or state["finished"]:
            return "This match has ended."

        user_id = str(user_id)
        if user_id not in state["players"]:
            return "You are not playing in this match."

        if time.monotonic() >= state["question_deadline"]:
            return "Time is up for this question."

        if user_id in state["answers"]:
            return "Your answer is already locked."

        question = state["question"]
        if answer not in question["choices"]:
            return "That is not one of the available choices."

        correct = answer == question["correct_answer"]
        state["answers"][user_id] = {
            "answer": answer,
            "correct": correct,
        }

        player = state["players"][user_id]
        player["score"] += 10 if correct else -1

    return None
