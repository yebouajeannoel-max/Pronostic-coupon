import json
import math
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS_FILE = ROOT / "pronostics.json"
API_URL = "https://api.football-data.org/v4/matches"
ODDS_API_URL = "https://api.the-odds-api.com/v4/sports/{}/odds"
FINISHED_STATUSES = {"FINISHED", "AET", "PEN"}
UPCOMING_STATUSES = {"SCHEDULED", "TIMED"}
MIN_TEAM_MATCHES = 3
FREE_PICKS_PER_DAY = 1
ODDS_SPORT_KEYS = {
    "PL": "soccer_epl",
    "BL1": "soccer_germany_bundesliga",
    "DED": "soccer_netherlands_eredivisie",
    "BSA": "soccer_brazil_campeonato",
    "PD": "soccer_spain_la_liga",
    "FL1": "soccer_france_ligue_one",
    "SA": "soccer_italy_serie_a",
    "PPL": "soccer_portugal_primeira_liga",
    "CL": "soccer_uefa_champs_league",
    "EL": "soccer_uefa_europa_league",
    "ELC": "soccer_efl_champ",
    "FAC": "soccer_fa_cup",
    "DFB": "soccer_germany_dfb_pokal",
    "CDR": "soccer_spain_copa_del_rey",
    "CIT": "soccer_italy_coppa_italia",
}


def parse_matches(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("matches"), list):
        raise ValueError("La réponse football-data.org ne contient pas la liste des matchs.")

    matches = []
    for raw in payload["matches"]:
        if not isinstance(raw, dict):
            continue
        status = raw.get("status")
        if status not in FINISHED_STATUSES and status not in UPCOMING_STATUSES:
            continue

        utc_date = raw.get("utcDate")
        home = raw.get("homeTeam") or {}
        away = raw.get("awayTeam") or {}
        competition = raw.get("competition") or {}
        if not utc_date or not home.get("id") or not away.get("id"):
            continue
        if not home.get("name") or not away.get("name"):
            continue

        item = {
            "id": raw.get("id"),
            "date": utc_date[:10],
            "utcDate": utc_date,
            "status": status,
            "competition": competition.get("code") or competition.get("name") or "",
            "homeId": home["id"],
            "awayId": away["id"],
            "home": home["name"],
            "away": away["name"],
        }
        if status in FINISHED_STATUSES:
            full_time = (raw.get("score") or {}).get("fullTime") or {}
            home_score = full_time.get("home")
            away_score = full_time.get("away")
            if (
                not isinstance(home_score, int) or isinstance(home_score, bool)
                or not isinstance(away_score, int) or isinstance(away_score, bool)
            ):
                continue
            item["homeScore"] = home_score
            item["awayScore"] = away_score
        matches.append(item)

    return sorted(matches, key=lambda item: (
        item["date"], item["competition"], item["home"], item["away"]
    ))


def fetch_matches(api_key, today=None):
    today = today or datetime.now(timezone.utc).date()
    month_end = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    date_from = (today - timedelta(days=180)).isoformat()
    offset = 0
    matches = []

    while True:
        query = urlencode({
            "dateFrom": date_from,
            "dateTo": month_end.isoformat(),
            "limit": 500,
            "offset": offset,
        })
        request = Request(
            API_URL + "?" + query,
            headers={"X-Auth-Token": api_key, "User-Agent": "Pronostic-coupon"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                payload = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(
                "football-data.org a refusé la demande (HTTP {}). Vérifie FOOTBALL_KEY et ton forfait.".format(exc.code)
            ) from exc
        except URLError as exc:
            raise RuntimeError("Connexion à football-data.org impossible : {}".format(exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("football-data.org a renvoyé une réponse JSON invalide.") from exc

        page = parse_matches(payload)
        raw_count = len(payload["matches"])
        matches.extend(page)
        result_set = payload.get("resultSet") or {}
        count = result_set.get("count")
        if raw_count == 0 or not isinstance(count, int) or offset + raw_count >= count:
            break
        offset += raw_count

    unique = {}
    for match in matches:
        unique[match["id"] or (match["date"], match["home"], match["away"])] = match
    return list(unique.values())


def _normalized_name(name):
    value = unicodedata.normalize("NFKD", str(name or "").casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"\b(?:fc|cf|afc|sc|club)\b", " ", value)
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def _same_team(left, right):
    left = _normalized_name(left)
    right = _normalized_name(right)
    if not left or not right:
        return False
    if left == right:
        return True
    return min(len(left), len(right)) >= 5 and SequenceMatcher(None, left, right).ratio() >= 0.88


def _event_matches_fixture(event, fixture):
    if not isinstance(event, dict):
        return False
    if not _same_team(event.get("home_team"), fixture.get("home")):
        return False
    if not _same_team(event.get("away_team"), fixture.get("away")):
        return False
    try:
        event_time = datetime.fromisoformat(event["commence_time"].replace("Z", "+00:00"))
        fixture_time = datetime.fromisoformat(fixture["utcDate"].replace("Z", "+00:00"))
    except (AttributeError, KeyError, TypeError, ValueError):
        return False
    return abs(event_time - fixture_time) <= timedelta(hours=8)


def odds_for_fixture(fixture, events):
    quotes = []
    event_list = events if isinstance(events, list) else []
    for event in event_list:
        if not _event_matches_fixture(event, fixture):
            continue
        bookmakers = event.get("bookmakers")
        if not isinstance(bookmakers, list):
            continue
        for bookmaker in bookmakers:
            if not isinstance(bookmaker, dict):
                continue
            outcomes = {"home": None, "draw": None, "away": None}
            markets = bookmaker.get("markets")
            if not isinstance(markets, list):
                continue
            for market in markets:
                if not isinstance(market, dict):
                    continue
                if market.get("key") != "h2h":
                    continue
                market_outcomes = market.get("outcomes")
                if not isinstance(market_outcomes, list):
                    continue
                for outcome in market_outcomes:
                    if not isinstance(outcome, dict):
                        continue
                    name = _normalized_name(outcome.get("name"))
                    price = outcome.get("price")
                    if not isinstance(price, (int, float)) or isinstance(price, bool) or price <= 1:
                        continue
                    if name in {"draw", "the draw", "tie", "match nul"}:
                        outcomes["draw"] = round(float(price), 2)
                    elif _same_team(name, event.get("home_team")):
                        outcomes["home"] = round(float(price), 2)
                    elif _same_team(name, event.get("away_team")):
                        outcomes["away"] = round(float(price), 2)
            if all(value is not None for value in outcomes.values()):
                quotes.append({
                    "bookmaker": bookmaker.get("title") or bookmaker.get("key") or "Bookmaker",
                    "home": outcomes["home"],
                    "draw": outcomes["draw"],
                    "away": outcomes["away"],
                    "updatedAt": bookmaker.get("last_update") or event.get("commence_time", ""),
                })
    return sorted(quotes, key=lambda quote: quote["bookmaker"].casefold())


def fetch_odds(api_key, sport_keys):
    odds = {}
    for sport_key in sorted(set(sport_keys)):
        query = urlencode({
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        })
        request = Request(
            ODDS_API_URL.format(sport_key) + "?" + query,
            headers={"x-api-key": api_key, "User-Agent": "Pronostic-coupon"},
        )
        try:
            with urlopen(request, timeout=30) as response:
                events = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(
                "The Odds API a refusé la demande (HTTP {}). Vérifie ODDS_API_KEY et les crédits disponibles.".format(exc.code)
            ) from exc
        except URLError as exc:
            raise RuntimeError("Connexion à The Odds API impossible : {}".format(exc.reason)) from exc
        except json.JSONDecodeError as exc:
            raise RuntimeError("The Odds API a renvoyé une réponse JSON invalide.") from exc
        if not isinstance(events, list):
            raise RuntimeError("The Odds API a renvoyé un format de cotes inattendu.")
        odds[sport_key] = events
    return odds


def attach_odds(document, matches, odds_by_sport, now=None):
    matches_by_id = {match.get("id"): match for match in matches if match.get("id") is not None}
    changed = False
    for fixture in document.get("fixtures", []):
        match = matches_by_id.get(fixture.get("matchId"))
        if not match:
            continue
        sport_key = ODDS_SPORT_KEYS.get(match.get("competition"))
        if sport_key not in odds_by_sport:
            continue
        quotes = odds_for_fixture(match, odds_by_sport[sport_key])
        if fixture.get("odds") != quotes:
            fixture["odds"] = quotes
            changed = True
    for picks in document.get("free", {}).values():
        for pick in picks:
            match = matches_by_id.get(pick.get("matchId"))
            if not match:
                continue
            sport_key = ODDS_SPORT_KEYS.get(match.get("competition"))
            if sport_key not in odds_by_sport:
                continue
            quotes = odds_for_fixture(match, odds_by_sport[sport_key])
            if pick.get("odds") != quotes:
                pick["odds"] = quotes
                changed = True
    if changed:
        now = now or datetime.now(timezone.utc)
        document["updatedAt"] = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return document


def _finished_before(matches, before):
    return [
        match for match in matches
        if match.get("status") in FINISHED_STATUSES
        and match.get("date", "") < before
        and isinstance(match.get("homeScore"), int)
        and isinstance(match.get("awayScore"), int)
    ]


def _league_baseline(matches, competition, before):
    completed = _finished_before(matches, before)
    same_competition = [
        match for match in completed
        if match.get("competition") == competition
    ]
    if len(same_competition) >= 5:
        completed = same_competition
    if not completed:
        return None

    completed = completed[-100:]
    home_average = sum(match["homeScore"] for match in completed) / len(completed)
    away_average = sum(match["awayScore"] for match in completed) / len(completed)
    overall_average = (home_average + away_average) / 2
    if overall_average <= 0:
        return None
    return home_average, away_average, overall_average


def _team_form(matches, team_id, competition, before, baseline):
    completed = _finished_before(matches, before)
    team_matches = [
        match for match in completed
        if match.get("homeId") == team_id or match.get("awayId") == team_id
    ]
    same_competition = [
        match for match in team_matches
        if match.get("competition") == competition
    ]
    if len(same_competition) >= MIN_TEAM_MATCHES:
        team_matches = same_competition
    team_matches = sorted(team_matches, key=lambda item: item["utcDate"])[-8:]
    if len(team_matches) < MIN_TEAM_MATCHES:
        return None

    scored = 0
    conceded = 0
    for match in team_matches:
        if match["homeId"] == team_id:
            scored += match["homeScore"]
            conceded += match["awayScore"]
        else:
            scored += match["awayScore"]
            conceded += match["homeScore"]

    count = len(team_matches)
    prior_weight = 2
    average_scored = (scored + baseline * prior_weight) / (count + prior_weight)
    average_conceded = (conceded + baseline * prior_weight) / (count + prior_weight)
    return average_scored, average_conceded, count


def _poisson(lam):
    probabilities = []
    for goals in range(9):
        probabilities.append(math.exp(-lam) * (lam ** goals) / math.factorial(goals))
    total = sum(probabilities)
    return [value / total for value in probabilities]


def _best_market(home_lambda, away_lambda):
    home_goals = _poisson(home_lambda)
    away_goals = _poisson(away_lambda)
    home_win = 0.0
    draw = 0.0
    away_win = 0.0
    for home_score, home_probability in enumerate(home_goals):
        for away_score, away_probability in enumerate(away_goals):
            probability = home_probability * away_probability
            if home_score > away_score:
                home_win += probability
            elif home_score == away_score:
                draw += probability
            else:
                away_win += probability

    markets = [
        ("1N · domicile ou nul", home_win + draw),
        ("N2 · nul ou extérieur", draw + away_win),
        ("12 · pas de match nul", home_win + away_win),
        ("1 · victoire domicile", home_win),
        ("N · match nul", draw),
        ("2 · victoire extérieur", away_win),
    ]
    return max(markets, key=lambda item: item[1])


def _date_label(utc_date):
    try:
        kickoff = datetime.fromisoformat(utc_date.replace("Z", "+00:00"))
        days = ["lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim."]
        months = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
                  "juil.", "août", "sept.", "oct.", "nov.", "déc."]
        return "{} {} {} · Début {:02d}h{:02d}".format(
            days[kickoff.weekday()], kickoff.day, months[kickoff.month - 1],
            kickoff.hour, kickoff.minute,
        )
    except (ValueError, IndexError):
        return utc_date[:10]


def _prediction(match, matches):
    baseline = _league_baseline(matches, match["competition"], match["date"])
    if baseline is None:
        return None
    home_baseline, away_baseline, overall_baseline = baseline
    home_form = _team_form(
        matches, match["homeId"], match["competition"], match["date"], overall_baseline
    )
    away_form = _team_form(
        matches, match["awayId"], match["competition"], match["date"], overall_baseline
    )
    if home_form is None or away_form is None:
        return None

    home_attack, home_defence, home_count = home_form
    away_attack, away_defence, away_count = away_form
    home_lambda = home_baseline * (home_attack / overall_baseline) * (away_defence / overall_baseline)
    away_lambda = away_baseline * (away_attack / overall_baseline) * (home_defence / overall_baseline)
    home_lambda = min(5.0, max(0.1, home_lambda))
    away_lambda = min(5.0, max(0.1, away_lambda))
    market, probability = _best_market(home_lambda, away_lambda)

    percent = "{:.1f}".format(probability * 100).replace(".", ",")
    return {
        "matchId": match["id"],
        "m": "{} – {}".format(match["home"], match["away"]),
        "d": _date_label(match["utcDate"]),
        "p": market,
        "pr": percent + " %",
        "a": (
            "Estimation statistique calculée avec les résultats récents "
            "({} matchs pour l’équipe à domicile, {} pour l’équipe visiteuse). "
            "Ce n’est jamais une certitude."
        ).format(home_count, away_count),
        "t": market.split(" · ", 1)[0],
        "hot": probability >= 0.8,
        "_probability": probability,
    }


def build_document(matches, previous, today=None, now=None):
    today = today or datetime.now(timezone.utc).date()
    today_text = today.isoformat()
    month_end = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    upcoming = {
        match["id"]: match for match in matches
        if match.get("status") in UPCOMING_STATUSES
        and match.get("id") is not None
        and today_text <= match.get("date", "") < month_end.isoformat()
    }
    fixtures = [
        {
            "matchId": match["id"],
            "k": match["date"],
            "home": match["home"],
            "away": match["away"],
            "competition": match.get("competition", ""),
            "d": _date_label(match["utcDate"]),
            "odds": [],
        }
        for match in sorted(
            upcoming.values(),
            key=lambda item: (item["date"], item["utcDate"], item["home"], item["away"]),
        )
    ]

    old_free = previous.get("free", {}) if isinstance(previous, dict) else {}
    free = {}
    history = list(previous.get("history", [])) if isinstance(previous, dict) else []
    tracked_ids = set()
    previous_days = old_free.items() if isinstance(old_free, dict) else []
    for old_date, picks in previous_days:
        if not isinstance(picks, list):
            continue
        for pick in picks:
            if not isinstance(pick, dict) or not isinstance(pick.get("m"), str):
                continue
            match_id = pick.get("matchId")
            if old_date >= today_text and (match_id is None or match_id in upcoming):
                if len(free.get(old_date, [])) < FREE_PICKS_PER_DAY:
                    free.setdefault(old_date, []).append(pick)
                    if match_id is not None:
                        tracked_ids.add(match_id)
            else:
                history.append({
                    "k": old_date,
                    "m": pick["m"],
                    "d": pick.get("d", ""),
                    "p": pick.get("p", ""),
                    "pr": pick.get("pr", ""),
                    "t": pick.get("t", ""),
                })

    candidates = {}
    for match in matches:
        if match.get("id") not in upcoming or match["id"] in tracked_ids:
            continue
        prediction = _prediction(match, matches)
        if prediction is None:
            continue
        prediction["_date"] = match["date"]
        candidates.setdefault(match["date"], []).append(prediction)

    for match_date, picks in candidates.items():
        picks.sort(key=lambda pick: pick["_probability"], reverse=True)
        if not free.get(match_date) and picks:
            free_pick = picks[0]
            free_pick.pop("_probability", None)
            free_pick.pop("_date", None)
            free.setdefault(match_date, []).append(free_pick)

    cutoff = (today - timedelta(days=120)).isoformat()
    unique_history = {}
    for pick in history:
        if not isinstance(pick, dict) or pick.get("k", "") < cutoff:
            continue
        key = (pick.get("k"), pick.get("m"), pick.get("t"))
        unique_history[key] = pick
    history = sorted(
        unique_history.values(),
        key=lambda pick: (pick.get("k", ""), pick.get("m", "")),
    )
    free = {key: value for key, value in sorted(free.items()) if value}

    content = {"free": free, "history": history, "fixtures": fixtures}
    old_content = {
        "free": previous.get("free", {}),
        "history": previous.get("history", []),
        "fixtures": previous.get("fixtures", []),
    } if isinstance(previous, dict) else None
    updated_at = previous.get("updatedAt") if isinstance(previous, dict) else None
    if old_content != content or not updated_at:
        now = now or datetime.now(timezone.utc)
        updated_at = now.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return {"updatedAt": updated_at, **content}


def write_document(document):
    PREDICTIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(
        prefix="pronostics-", suffix=".json", dir=str(PREDICTIONS_FILE.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
            json.dump(document, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temp_path, PREDICTIONS_FILE)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def main():
    api_key = os.environ.get("FOOTBALL_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Le secret GitHub FOOTBALL_KEY est manquant.")

    matches = fetch_matches(api_key)
    try:
        with PREDICTIONS_FILE.open(encoding="utf-8") as source:
            previous = json.load(source)
    except FileNotFoundError:
        previous = None

    document = build_document(matches, previous)
    odds_key = os.environ.get("ODDS_API_KEY", "").strip()
    if odds_key:
        match_by_id = {match.get("id"): match for match in matches if match.get("id") is not None}
        active_ids = {fixture["matchId"] for fixture in document["fixtures"]}
        active_ids.update(
            pick.get("matchId")
            for picks in document["free"].values()
            for pick in picks
            if pick.get("matchId") is not None
        )
        sport_keys = {
            ODDS_SPORT_KEYS[match_by_id[match_id].get("competition")]
            for match_id in active_ids
            if match_id in match_by_id
            and match_by_id[match_id].get("competition") in ODDS_SPORT_KEYS
        }
        if sport_keys:
            try:
                odds_by_sport = fetch_odds(odds_key, sport_keys)
            except RuntimeError as exc:
                print("Cotes non actualisées : {}".format(exc), file=sys.stderr)
            else:
                document = attach_odds(document, matches, odds_by_sport)
        else:
            print("Aucune compétition sélectionnée n’est couverte par la liste de sports des cotes.")
    else:
        print("Cotes non chargées : ajoute le secret GitHub ODDS_API_KEY pour les activer.")

    write_document(document)
    count = sum(len(picks) for picks in document["free"].values())
    print("{} match(s) avec équipes, {} pronostic(s) gratuit(s) enregistré(s).".format(
        len(document["fixtures"]), count
    ))


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, ValueError, OSError, json.JSONDecodeError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
