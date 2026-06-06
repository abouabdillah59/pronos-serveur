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
#  UPDATE AUTOMATIQUE DES AMICAUX DE TEST (via TheSportsDB, gratuit)
#  Le serveur va chercher les scores réels et remplit friendlyResults.
# ============================================================
import urllib.request

THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "123")  # clé de test gratuite

# Mapping des amicaux de test : id -> date (UTC) + noms d'équipes (alias EN)
FRIENDLIES_FETCH = [
    {"id": "f1", "dates": ["2026-06-03"], "home": ["netherlands", "holland"], "away": ["algeria"]},
    {"id": "f2", "dates": ["2026-06-03"], "home": ["luxembourg"], "away": ["italy"]},
    {"id": "f3", "dates": ["2026-06-03"], "home": ["poland"], "away": ["nigeria"]},
    {"id": "f4", "dates": ["2026-06-03"], "home": ["denmark"], "away": ["dr congo", "congo dr", "democratic republic"]},
    {"id": "f5", "dates": ["2026-06-04"], "home": ["france"], "away": ["ivory coast", "cote d'ivoire", "côte d'ivoire"]},
    {"id": "f6", "dates": ["2026-06-04"], "home": ["spain"], "away": ["iraq"]},
    {"id": "f7", "dates": ["2026-06-04"], "home": ["sweden"], "away": ["greece"]},
    {"id": "f8", "dates": ["2026-06-04"], "home": ["northern ireland"], "away": ["guinea"]},
]


def _norm(s):
    return (s or "").strip().lower()


def _matches(name, aliases):
    n = _norm(name)
    return any(a in n or n in a for a in aliases)


def _fetch_events_for_date(date):
    url = (
        f"https://www.thesportsdb.com/api/v1/json/{THESPORTSDB_KEY}"
        f"/eventsday.php?d={date}&s=Soccer"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "pronos-mondial"})
    with urllib.request.urlopen(req, timeout=15) as r:
        data = json.load(r)
    return data.get("events") or []


@app.post("/fetch-friendlies")
def fetch_friendlies():
    body = request.get_json(silent=True) or {}
    if body.get("pin") != ADMIN_PIN:
        return jsonify(error="code admin incorrect"), 403

    # récupère tous les événements des dates concernées (une seule fois par date)
    all_dates = sorted({d for f in FRIENDLIES_FETCH for d in f["dates"]})
    events = []
    errors = []
    for d in all_dates:
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

    return jsonify(ok=True, updated=updated, count=len(updated), errors=errors)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)