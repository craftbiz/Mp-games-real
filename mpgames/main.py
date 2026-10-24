
import os
import time
import threading
from collections import deque
from datetime import datetime
from flask import (
    Flask, render_template, redirect,
    url_for, session, jsonify, request,
    make_response
)
from flask_socketio import SocketIO
from flask.signals import got_request_exception

import database
from auth import auth_bp
from games import games_bp, get_game_list
from server import server_bp, register_socket_events
import server as server_module
from games.platform_api import GamePlatform
from games.plugin_loader import register_game_plugins
from profile import profile_bp


app = Flask(__name__)

app.config.update(
    SECRET_KEY=os.environ.get(
        "SECRET_KEY",
        "development-only-change-this-secret"
    ),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=bool(os.environ.get("RENDER")),
    MAX_CONTENT_LENGTH=1 * 1024 * 1024,
    PERMANENT_SESSION_LIFETIME=60 * 60 * 24 * 7
)

socketio = SocketIO(
    app,
    async_mode="threading",
    ping_interval=25,
    ping_timeout=60
)

app.register_blueprint(auth_bp)
app.register_blueprint(games_bp)
app.register_blueprint(server_bp)
app.register_blueprint(profile_bp)

register_socket_events(socketio)

# Load every available game plugin once at startup. Each plugin owns its
# gameplay rules and events; the platform supplies rooms, authentication,
# result persistence, and leaderboard updates.
game_platform = GamePlatform(
    socketio,
    server_module.SERVERS,
    server_module.LOCK,
    server_module.SID_TO_SERVER,
)
register_game_plugins(game_platform)
server_module.set_game_platform(game_platform)
app.extensions["mpgames_game_platform"] = game_platform


# --------------------------------------------------
# TEMPORARY DIAGNOSTICS
# --------------------------------------------------

_DIAG_EVENTS = deque(maxlen=1000)
_DIAG_LOCK = threading.Lock()
_DIAG_STARTED = time.perf_counter()


def _diag_add(source, event, status="INFO", details=None):
    """Keep a bounded, temporary, in-memory diagnostic timeline."""
    now = time.perf_counter()
    item = {
        "time": datetime.now().astimezone().isoformat(
            timespec="milliseconds"
        ),
        "elapsed_ms": round((now - _DIAG_STARTED) * 1000, 2),
        "source": str(source)[:40],
        "event": str(event)[:200],
        "status": str(status)[:30],
        "details": str(details or "")[:1500]
    }

    with _DIAG_LOCK:
        _DIAG_EVENTS.append(item)

    print(
        "[MPDIAG] "
        f"{item['time']} | {item['source']} | "
        f"{item['status']} | {item['event']} | "
        f"{item['details']}",
        flush=True
    )


@app.before_request
def _diag_request_start():
    # Don't flood the timeline with the diagnostic interface itself.
    if request.path.startswith("/_diag/") or request.path == "/diagnostics":
        return

    request._mpdiag_started = time.perf_counter()
    _diag_add(
        "SERVER",
        f"REQUEST START {request.method} {request.path}",
        "LOADING"
    )


@app.after_request
def _diag_request_end(response):
    if request.path.startswith("/_diag/") or request.path == "/diagnostics":
        return response

    started = getattr(request, "_mpdiag_started", None)
    duration = (
        round((time.perf_counter() - started) * 1000, 2)
        if started is not None else None
    )

    status = "DONE" if response.status_code < 400 else "FAILED"
    _diag_add(
        "SERVER",
        f"REQUEST {request.method} {request.path}",
        status,
        f"HTTP {response.status_code}; duration={duration} ms"
    )
    return response


def _diag_exception(sender, exception, **extra):
    _diag_add(
        "SERVER",
        "UNHANDLED REQUEST EXCEPTION",
        "FAILED",
        f"{type(exception).__name__}: {exception}"
    )


got_request_exception.connect(_diag_exception, app, weak=False)


@app.post("/_diag/event")
def diagnostics_receive_event():
    # Accept only small, non-sensitive diagnostic messages.
    data = request.get_json(silent=True) or {}

    event = str(data.get("event", "Unknown browser event"))[:200]
    status = str(data.get("status", "INFO"))[:30]
    details = str(data.get("details", ""))[:1500]

    _diag_add("BROWSER", event, status, details)
    return jsonify({"ok": True})


@app.get("/_diag/logs")
def diagnostics_get_logs():
    with _DIAG_LOCK:
        events = list(_DIAG_EVENTS)

    return jsonify({
        "events": events,
        "count": len(events)
    })


@app.post("/_diag/clear")
def diagnostics_clear_logs():
    with _DIAG_LOCK:
        _DIAG_EVENTS.clear()

    _diag_add("DIAGNOSTICS", "Timeline cleared", "DONE")
    return jsonify({"ok": True})


@app.get("/diagnostics")
def diagnostics_page():
    page = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>MPGames Diagnostics</title>
<style>
*{box-sizing:border-box}
body{margin:0;padding:16px;background:#0b1120;color:#e5e7eb;
font:14px system-ui,Arial,sans-serif}
h1{font-size:23px;margin:0 0 8px}
p{color:#aab5c7;line-height:1.5}
.controls{display:flex;gap:8px;flex-wrap:wrap;margin:16px 0}
button{padding:10px 13px;border:1px solid #334155;border-radius:8px;
background:#172033;color:white;font-weight:600}
#summary{margin:12px 0;color:#aab5c7}
#events{display:grid;gap:9px}
.event{border:1px solid #263349;background:#111a2b;border-radius:9px;
padding:11px;overflow-wrap:anywhere}
.top{display:flex;gap:8px;justify-content:space-between;flex-wrap:wrap}
.time{color:#aab5c7;font-size:12px}
.name{font-weight:700;margin:7px 0}
.details{white-space:pre-wrap;color:#c2ccda;font-size:12px}
.DONE{color:#6ee7a0}.FAILED{color:#fca5a5}
.LOADING,.PENDING,.TIMED_OUT{color:#fcd34d}
small{color:#91a0b7}
</style>
</head>
<body>
<h1>MPGames diagnostics</h1>
<p>Temporary troubleshooting timeline. Do not share it publicly if it
contains information you consider private.</p>
<div class="controls">
<button id="refresh">Refresh now</button>
<button id="auto">Auto-refresh: ON</button>
<button id="clear">Clear timeline</button>
</div>
<div id="summary">Loading diagnostic events…</div>
<div id="events"></div>
<script>
(function(){
"use strict";
const eventsEl=document.getElementById("events");
const summary=document.getElementById("summary");
const autoButton=document.getElementById("auto");
let auto=true;
let timer=null;

function addText(parent,tag,className,value){
  const el=document.createElement(tag);
  if(className) el.className=className;
  el.textContent=value==null?"":String(value);
  parent.appendChild(el);
  return el;
}
function render(items){
  eventsEl.replaceChildren();
  summary.textContent=items.length+" events — newest at the bottom";
  items.forEach(item=>{
    const card=document.createElement("section");
    card.className="event";
    const top=document.createElement("div");
    top.className="top";
    addText(top,"span","time",item.time||"");
    addText(top,"span",item.status||"INFO",item.status||"INFO");
    card.appendChild(top);
    addText(card,"div","name",
      "["+(item.source||"?")+"] "+(item.event||""));
    addText(card,"div","details",
      (item.elapsed_ms==null?"":"Server elapsed: "+item.elapsed_ms+" ms\n")+
      (item.details||""));
    eventsEl.appendChild(card);
  });
  if(items.length) window.scrollTo(0,document.body.scrollHeight);
}
async function refresh(){
  try{
    const response=await fetch("/_diag/logs",{cache:"no-store"});
    if(!response.ok) throw new Error("HTTP "+response.status);
    const data=await response.json();
    render(data.events||[]);
  }catch(error){
    summary.textContent="Could not retrieve logs: "+error.message;
  }
}
function schedule(){
  if(timer) clearTimeout(timer);
  if(auto) timer=setTimeout(async()=>{await refresh();schedule();},2000);
}
document.getElementById("refresh").addEventListener("click",refresh);
autoButton.addEventListener("click",()=>{
  auto=!auto;
  autoButton.textContent="Auto-refresh: "+(auto?"ON":"OFF");
  schedule();
});
document.getElementById("clear").addEventListener("click",async()=>{
  if(!confirm("Clear the temporary server diagnostic timeline?")) return;
  try{
    await fetch("/_diag/clear",{method:"POST"});
    await refresh();
  }catch(error){
    summary.textContent="Could not clear logs: "+error.message;
  }
});
refresh();
schedule();
})();
</script>
</body>
</html>"""
    response = make_response(page)
    response.headers["Cache-Control"] = "no-store"
    return response


# --------------------------------------------------
# EXISTING PLATFORM ROUTES
# --------------------------------------------------

@app.route("/")
def home():
    if not session.get("user_id"):
        return redirect(url_for("auth.login"))

    import database as db

    return render_template(
        "home.html",
        username=session.get("username", "Player"),
        user_id=session.get("user_id"),
        games=get_game_list(),
        leaderboard=db.get_leaderboard("maths_trivia", limit=10)
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "service": "multiplayer-game-platform"
    })


@app.route("/debug-page")
def debug_page():
    return """
    <!doctype html>
    <html>
      <head><title>MPGames Test</title></head>
      <body style="background:#111;color:white;padding:30px;font:20px Arial">
        <h1>MPGames page test works</h1>
        <p>If you can read this, Flask and basic HTML rendering work.</p>
      </body>
    </html>
    """


if __name__ == "__main__":
    host = "0.0.0.0"
    port = int(os.environ.get("PORT", 8080))

    print(f"Multiplayer platform starting on port {port}")
    print("Open http://127.0.0.1:8080 on this device.")
    print("For other devices, use this phone's LAN IP and port 8080.")

    socketio.run(
        app,
        host=host,
        port=port,
        debug=False,
        allow_unsafe_werkzeug=True
    )
