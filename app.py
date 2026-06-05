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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
