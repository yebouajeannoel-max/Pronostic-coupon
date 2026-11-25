import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SCORES_FILE = ROOT / "scores.json"
API_URL = "https://api.football-data.org/v4/matches"
FINISHED_STATUSES = {"FINISHED", "AET", "PEN"}


def parse_scores(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("La réponse football-data.org ne contient pas la liste des matchs.")

    scores = []
    for match in payload["matches"]:
        if not isinstance(match, dict) or match.get("status") not in FINISHED_STATUSES:
            continue

        utc_date = match.get("utcDate")
        competition = match.get("competition") or {}
        home_team = match.get("homeTeam") or {}
        away_team = match.get("awayTeam") or {}
        score = (match.get("score") or {}).get("fullTime") or {}
        home_score = score.get("home")
        away_score = score.get("away")

        if not utc_date or not home_team.get("name") or not away_team.get("name"):
            continue
        if not isinstance(home_score, int) or isinstance(home_score, bool):
            continue
        if not isinstance(away_score, int) or isinstance(away_score, bool):
            continue

        scores.append({
            "id": match.get("id"),
            "date": utc_date[:10],
            "competition": competition.get("code") or competition.get("name") or "",
            "home": home_team["name"],
            "away": away_team["name"],
            "homeScore": home_score,
            "awayScore": away_score,
        })

    return sorted(scores, key=lambda item: (
        item["date"], item["competition"], item["home"], item["away"]
    ))


def fetch_scores(api_key, today=None):
    today = today or datetime.now(timezone.utc).date()
    query = urlencode({
        "dateFrom": (today - timedelta(days=60)).isoformat(),
        "dateTo": (today + timedelta(days=31)).isoformat(),
    })
    request = Request(
        API_URL + "?" + query,
        headers={"X-Auth-Token": api_key, "User-Agent": "Pronostic-coupon"},
    )
    try:
        with urlopen(request, timeout=30) as response:
            return parse_scores(json.load(response))
    except HTTPError as exc:
        raise RuntimeError(
            "football-data.org a refusé la demande (HTTP {}). Vérifie FOOTBALL_KEY et ton forfait.".format(exc.code)
        ) from exc
    except URLError as exc:
        raise RuntimeError("Connexion à football-data.org impossible : {}".format(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError("football-data.org a renvoyé une réponse JSON invalide.") from exc


def build_document(scores, previous, now=None):
    previous_scores = previous.get("matches") if isinstance(previous, dict) else None
    updated_at = previous.get("updatedAt") if isinstance(previous, dict) else None
    if previous_scores != scores or not updated_at:
        now = now or datetime.now(timezone.utc)
        updated_at = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return {"updatedAt": updated_at, "matches": scores}


def write_document(document):
    SCORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix="scores-", suffix=".json", dir=str(SCORES_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            json.dump(document, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temp_path, SCORES_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    api_key = os.environ.get("FOOTBALL_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Le secret GitHub FOOTBALL_KEY est manquant.")

    scores = fetch_scores(api_key)
    try:
        with SCORES_FILE.open(encoding="utf-8") as source:
            previous = json.load(source)
    except FileNotFoundError:
        previous = None

    document = build_document(scores, previous)
    write_document(document)
    print("{} score(s) terminé(s) enregistrés.".format(len(scores)))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
