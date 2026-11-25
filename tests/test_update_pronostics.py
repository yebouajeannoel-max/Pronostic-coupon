import unittest
from datetime import date, datetime, timezone

from scripts.update_pronostics import (
    _best_market,
    _poisson,
    attach_odds,
    build_document,
    odds_for_fixture,
    parse_matches,
)


def finished_match(match_id, day, home_id, away_id, home_score, away_score):
    return {
        "id": match_id,
        "date": day,
        "utcDate": day + "T18:00:00Z",
        "status": "FINISHED",
        "competition": "TEST",
        "homeId": home_id,
        "awayId": away_id,
        "home": "Team {}".format(home_id),
        "away": "Team {}".format(away_id),
        "homeScore": home_score,
        "awayScore": away_score,
    }


class UpdatePronosticsTests(unittest.TestCase):
    def test_parser_keeps_finished_scores_and_future_fixtures_only(self):
        payload = {
            "matches": [
                {
                    "id": 1,
                    "status": "FINISHED",
                    "utcDate": "2025-01-10T18:00:00Z",
                    "competition": {"code": "TEST"},
                    "homeTeam": {"id": 10, "name": "Team A"},
                    "awayTeam": {"id": 20, "name": "Team B"},
                    "score": {"fullTime": {"home": 2, "away": 1}},
                },
                {
                    "id": 2,
                    "status": "SCHEDULED",
                    "utcDate": "2025-01-20T18:00:00Z",
                    "competition": {"code": "TEST"},
                    "homeTeam": {"id": 10, "name": "Team A"},
                    "awayTeam": {"id": 20, "name": "Team B"},
                    "score": {"fullTime": {"home": None, "away": None}},
                },
                {
                    "id": 3,
                    "status": "IN_PLAY",
                    "utcDate": "2025-01-20T17:00:00Z",
                    "homeTeam": {"id": 10, "name": "Team A"},
                    "awayTeam": {"id": 20, "name": "Team B"},
                },
            ]
        }

        parsed = parse_matches(payload)

        self.assertEqual([match["id"] for match in parsed], [1, 2])
        self.assertEqual(parsed[0]["homeScore"], 2)
        self.assertEqual(parsed[1]["status"], "SCHEDULED")

    def test_poisson_probabilities_are_normalized(self):
        self.assertAlmostEqual(sum(_poisson(1.7)), 1.0)
        market, probability = _best_market(3.0, 0.3)
        self.assertEqual(market, "1N · domicile ou nul")
        self.assertGreater(probability, 0.8)

    def test_odds_are_matched_to_the_correct_fixture_and_keep_bookmaker_names(self):
        fixture = {
            "id": 8,
            "utcDate": "2025-01-20T18:00:00Z",
            "home": "Team A FC",
            "away": "Team B",
        }
        events = [{
            "commence_time": "2025-01-20T18:00:00Z",
            "home_team": "Team A",
            "away_team": "Team B",
            "bookmakers": [{
                "title": "Bookmaker A",
                "last_update": "2025-01-20T10:00:00Z",
                "markets": [{
                    "key": "h2h",
                    "outcomes": [
                        {"name": "Team A", "price": 2.1},
                        {"name": "Draw", "price": 3.2},
                        {"name": "Team B", "price": 3.5},
                    ],
                }],
            }],
        }]

        quotes = odds_for_fixture(fixture, events)

        self.assertEqual(len(quotes), 1)
        self.assertEqual(quotes[0]["bookmaker"], "Bookmaker A")
        self.assertEqual((quotes[0]["home"], quotes[0]["draw"], quotes[0]["away"]), (2.1, 3.2, 3.5))
        events[0]["commence_time"] = "2025-01-21T18:00:00Z"
        self.assertEqual(odds_for_fixture(fixture, events), [])

    def test_attach_odds_updates_the_pick_and_timestamp(self):
        fixture = {
            "id": 8,
            "date": "2025-01-20",
            "utcDate": "2025-01-20T18:00:00Z",
            "status": "SCHEDULED",
            "competition": "PL",
            "home": "Team A",
            "away": "Team B",
        }
        document = {
            "updatedAt": "2025-01-19T00:00:00+00:00",
            "free": {"2025-01-20": [{"matchId": 8}]},
            "fixtures": [{
                "matchId": 8,
                "k": "2025-01-20",
                "home": "Team A",
                "away": "Team B",
                "competition": "PL",
                "d": "lun. 20 janv. · Début 18h00",
                "odds": [],
            }],
            "history": [],
        }
        odds = {
            "soccer_epl": [{
                "commence_time": fixture["utcDate"],
                "home_team": "Team A",
                "away_team": "Team B",
                "bookmakers": [{
                    "title": "Bookmaker A",
                    "markets": [{
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Team A", "price": 2.1},
                            {"name": "Draw", "price": 3.2},
                            {"name": "Team B", "price": 3.5},
                        ],
                    }],
                }],
            }]
        }

        result = attach_odds(
            document,
            [fixture],
            odds,
            now=datetime(2025, 1, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(result["free"]["2025-01-20"][0]["odds"][0]["bookmaker"], "Bookmaker A")
        self.assertEqual(result["fixtures"][0]["home"], "Team A")
        self.assertEqual(result["fixtures"][0]["away"], "Team B")
        self.assertEqual(result["fixtures"][0]["odds"][0]["draw"], 3.2)
        self.assertEqual(result["updatedAt"], "2025-01-20T00:00:00+00:00")

    def test_build_document_creates_predictions_and_archives_past_picks(self):
        matches = []
        for index in range(5):
            day = "2025-01-{:02d}".format(index + 1)
            matches.append(finished_match(index * 2 + 1, day, 10, 20, 4, 0))
            matches.append(finished_match(index * 2 + 2, day, 30, 40, 1, 1))
        matches.append({
            "id": 99,
            "date": "2025-01-20",
            "utcDate": "2025-01-20T18:00:00Z",
            "status": "SCHEDULED",
            "competition": "TEST",
            "homeId": 10,
            "awayId": 20,
            "home": "Team 10",
            "away": "Team 20",
        })
        previous = {
            "updatedAt": "2025-01-19T05:00:00+00:00",
            "free": {
                "2025-01-19": [{
                    "matchId": 50,
                    "m": "Ancien match",
                    "d": "dim. 19 janv.",
                    "p": "1",
                    "pr": "60 %",
                    "t": "1",
                }]
            },
            "history": [],
        }

        result = build_document(
            matches,
            previous,
            today=date(2025, 1, 20),
            now=datetime(2025, 1, 20, tzinfo=timezone.utc),
        )

        self.assertEqual(len(result["free"]["2025-01-20"]), 1)
        self.assertEqual(result["free"]["2025-01-20"][0]["matchId"], 99)
        self.assertEqual(len(result["fixtures"]), 1)
        self.assertEqual(result["fixtures"][0]["home"], "Team 10")
        self.assertEqual(result["fixtures"][0]["away"], "Team 20")
        self.assertEqual(result["fixtures"][0]["k"], "2025-01-20")
        self.assertEqual(result["history"][0]["m"], "Ancien match")


if __name__ == "__main__":
    unittest.main()
