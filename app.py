"""
Pronos Mondial 2026 — serveur du classement commun
API minimaliste : stocke les pronos de chaque joueur + les vrais résultats (admin),
et permet à l'appli de tout récupérer pour afficher un classement partagé.

Stockage : un simple fichier JSON sur le disque (data.json). Pas de base de données
à installer — suffisant pour une ligue entre amis.
"""
import json, os, threading
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # autorise l'appli (autre domaine) à parler au serveur

# Render fournit un disque éphémère ; on stocke à côté du script.
DATA_FILE = os.path.join(os.path.dirname(__file__), "data.json")
LOCK = threading.Lock()

# Code admin pour enregistrer les VRAIS résultats (à changer si tu veux)
ADMIN_PIN = os.environ.get("ADMIN_PIN", "2026")


def _empty():
    return {"players": {}, "results": {}, "friendlyResults": {}, "locked": False}


def load():
    if not os.path.exists(DATA_FILE):
        return _empty()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
        # garde-fous si le fichier est incomplet
        for k, v in _empty().items():
            d.setdefault(k, v)
        return d
    except Exception:
        return _empty()


def save(d):
    tmp = DATA_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    os.replace(tmp, DATA_FILE)  # écriture atomique


@app.get("/")
def home():
    return "Pronos Mondial 2026 — serveur en ligne ✅", 200


@app.get("/health")
def health():
    return jsonify(ok=True)


# --- L'appli récupère tout l'état de la ligue (pour afficher le classement) ---
@app.get("/league")
def get_league():
    with LOCK:
        return jsonify(load())


# --- Un joueur enregistre/ met à jour SES pronos ---
# body attendu : { "name": "Jamel", "matches": {...}, "friendlies": {...} }
@app.post("/predictions")
def post_predictions():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if len(name) < 2:
        return jsonify(error="pseudo invalide"), 400
    with LOCK:
        d = load()
        if d.get("locked"):
            # une fois verrouillé, on n'accepte plus les pronos de POULE,
            # mais on tolère encore l'enregistrement (les matchs déjà commencés
            # sont de toute façon figés côté appli). On enregistre tel quel.
            pass
        d["players"][name] = {
            "matches": body.get("matches", {}),
            "friendlies": body.get("friendlies", {}),
        }
        save(d)
    return jsonify(ok=True)


# --- L'admin enregistre les VRAIS résultats ---
# body : { "pin": "2026", "results": {...}, "friendlyResults": {...}, "locked": true/false }
@app.post("/results")
def post_results():
    body = request.get_json(silent=True) or {}
    if body.get("pin") != ADMIN_PIN:
        return jsonify(error="code admin incorrect"), 403
    with LOCK:
        d = load()
        if "results" in body:
            d["results"] = body["results"]
        if "friendlyResults" in body:
            d["friendlyResults"] = body["friendlyResults"]
        if "locked" in body:
            d["locked"] = bool(body["locked"])
        save(d)
    return jsonify(ok=True)


# ============================================================
#  UPDATE AUTOMATIQUE — via API-Football (api-sports.io)
#  Clé gratuite à mettre dans la variable d'environnement API_FOOTBALL_KEY (sur Render).
# ============================================================
import urllib.request

API_KEY = os.environ.get("API_FOOTBALL_KEY", "")  # <-- à définir sur Render
API_HOST = "v3.football.api-sports.io"

# Mapping des amicaux de test : id -> dates + noms d'équipes (alias, en minuscules)
FRIENDLIES_FETCH = [
    {"id": "f1", "dates": ["2026-06-03"], "home": ["netherlands", "holland"], "away": ["algeria"]},
    {"id": "f2", "dates": ["2026-06-03"], "home": ["luxembourg"], "away": ["italy"]},
    {"id": "f3", "dates": ["2026-06-03"], "home": ["poland"], "away": ["nigeria"]},
    {"id": "f4", "dates": ["2026-06-03"], "home": ["denmark"], "away": ["dr congo", "congo dr", "democratic republic"]},
    {"id": "f5", "dates": ["2026-06-04"], "home": ["france"], "away": ["ivory coast", "cote d'ivoire", "côte d'ivoire"]},
    {"id": "f6", "dates": ["2026-06-04"], "home": ["spain"], "away": ["iraq"]},
    {"id": "f7", "dates": ["2026-06-04"], "home": ["sweden"], "away": ["greece"]},
    {"id": "f8", "dates": ["2026-06-04"], "home": ["northern ireland"], "away": ["guinea"]},
    {"id": "f9", "dates": ["2026-06-08"], "home": ["france"], "away": ["northern ireland"]},
]


def _norm(s):
    return (s or "").strip().lower()


def _matches(name, aliases):
    n = _norm(name)
    return any(a in n or n in a for a in aliases)


def _api_get(path):
    if not API_KEY:
        raise RuntimeError("API_FOOTBALL_KEY manquante (à définir sur Render)")
    url = f"https://{API_HOST}/{path}"
    req = urllib.request.Request(url, headers={"x-apisports-key": API_KEY})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    return data.get("response", [])


def _fetch_events_for_date(date):
    resp = _api_get(f"fixtures?date={date}")
    out = []
    for it in resp:
        teams = it.get("teams", {})
        goals = it.get("goals", {})
        status = (it.get("fixture", {}).get("status", {}) or {}).get("short")
        out.append({
            "strHomeTeam": (teams.get("home") or {}).get("name"),
            "strAwayTeam": (teams.get("away") or {}).get("name"),
            "intHomeScore": goals.get("home"),
            "intAwayScore": goals.get("away"),
            "status": status,
        })
    return out


@app.post("/test-connection")
def test_connection():
    body = request.get_json(silent=True) or {}
    if body.get("pin") != ADMIN_PIN:
        return jsonify(error="code admin incorrect"), 403
    date = body.get("date", "2026-06-04")
    try:
        events = _fetch_events_for_date(date)
    except Exception as e:
        return jsonify(ok=False, error=str(e))
    sample = [
        f"{e['strHomeTeam']} {e['intHomeScore']}-{e['intAwayScore']} {e['strAwayTeam']} [{e['status']}]"
        for e in events[:25]
    ]
    return jsonify(ok=True, date=date, events_seen=len(events), sample=sample)


@app.post("/fetch-friendlies")
def fetch_friendlies():
    body = request.get_json(silent=True) or {}
    if body.get("pin") != ADMIN_PIN:
        return jsonify(error="code admin incorrect"), 403

    # fenêtre de dates élargie (±1 jour) pour absorber les décalages de fuseau
    from datetime import datetime, timedelta
    base = sorted({d for f in FRIENDLIES_FETCH for d in f["dates"]})
    dates = set()
    for d in base:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            for off in (-1, 0, 1):
                dates.add((dt + timedelta(days=off)).strftime("%Y-%m-%d"))
        except Exception:
            dates.add(d)

    events = []
    errors = []
    for d in sorted(dates):
        try:
            events.extend(_fetch_events_for_date(d))
        except Exception as e:
            errors.append(f"{d}: {e}")

    updated = []
    with LOCK:
        data = load()
        fr = data.get("friendlyResults", {})
        for f in FRIENDLIES_FETCH:
            for ev in events:
                if _matches(ev.get("strHomeTeam"), f["home"]) and _matches(ev.get("strAwayTeam"), f["away"]):
                    hs, as_ = ev.get("intHomeScore"), ev.get("intAwayScore")
                    if hs is not None and as_ is not None and str(hs) != "" and str(as_) != "":
                        fr[f["id"]] = {"h": int(hs), "a": int(as_)}
                        updated.append(f["id"])
                    break
        data["friendlyResults"] = fr
        save(data)

    # rapport de diagnostic : ce que l'API a réellement renvoyé
    sample = [
        f"{e.get('strHomeTeam')} {e.get('intHomeScore')}-{e.get('intAwayScore')} {e.get('strAwayTeam')}"
        for e in events[:25]
    ]
    return jsonify(ok=True, updated=updated, count=len(updated),
                   events_seen=len(events), sample=sample, errors=errors)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)