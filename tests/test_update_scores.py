import unittest
from datetime import datetime, timezone

from scripts.update_scores import build_document, parse_scores
from scripts.write_auth_config import build_config


class UpdateScoresTests(unittest.TestCase):
    def test_parse_scores_keeps_only_completed_matches_with_final_scores(self):
        payload = {
            "matches": [
                {
                    "id": 8,
                    "status": "FINISHED",
                    "utcDate": "2026-11-24T18:00:00Z",
                    "competition": {"code": "PL"},
                    "homeTeam": {"name": "Team A"},
                    "awayTeam": {"name": "Team B"},
                    "score": {"fullTime": {"home": 2, "away": 1}},
                },
                {
                    "status": "IN_PLAY",
                    "utcDate": "2026-11-24T20:00:00Z",
                    "homeTeam": {"name": "Team C"},
                    "awayTeam": {"name": "Team D"},
                    "score": {"fullTime": {"home": None, "away": None}},
                },
                {
                    "status": "FINISHED",
                    "utcDate": "2026-11-24T17:00:00Z",
                    "homeTeam": {"name": "Team E"},
                    "awayTeam": {"name": "Team F"},
                    "score": {"fullTime": {"home": None, "away": None}},
                },
            ]
        }

        self.assertEqual(parse_scores(payload), [{
            "id": 8,
            "date": "2026-11-24",
            "competition": "PL",
            "home": "Team A",
            "away": "Team B",
            "homeScore": 2,
            "awayScore": 1,
        }])

    def test_unchanged_scores_keep_their_last_update_time(self):
        scores = [{"date": "2026-11-24", "home": "A", "away": "B", "homeScore": 1, "awayScore": 0}]
        previous = {"updatedAt": "2026-11-24T10:00:00+00:00", "matches": scores}

        result = build_document(
            scores,
            previous,
            now=datetime(2026, 11, 24, 11, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(result["updatedAt"], previous["updatedAt"])

    def test_auth_config_uses_only_an_https_supabase_project_and_public_key(self):
        config = build_config("https://example.supabase.co", "public-anon-key")

        self.assertIn('"url":"https://example.supabase.co"', config)
        self.assertIn('"anonKey":"public-anon-key"', config)
        with self.assertRaises(ValueError):
            build_config("http://example.supabase.co", "public-anon-key")
        with self.assertRaises(ValueError):
            build_config("https://example.supabase.co.evil.test", "public-anon-key")


if __name__ == "__main__":
    unittest.main()
