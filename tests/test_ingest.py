"""Rodar com: python3 -m unittest discover -s tests"""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402


class FakeAPIError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status_code = status


class APITimeoutError(Exception):  # mesmo nome da classe do SDK
    pass


def scripted(outcomes):
    """Cria create(model) que devolve/levanta os resultados na ordem e registra as chamadas."""
    calls = []

    def create(model):
        calls.append(model)
        out = outcomes[len(calls) - 1]
        if isinstance(out, Exception):
            raise out
        return out
    return create, calls


class CallLLM(unittest.TestCase):
    def run_llm(self, outcomes, models=("a", "b"), retries=2):
        create, calls = scripted(outcomes)
        sleeps = []
        try:
            res = ingest.call_llm(create, list(models), retries=retries, sleep=sleeps.append, log=lambda m: None)
        except Exception as exc:
            res = exc
        return res, calls, sleeps

    def test_retry_429_then_success(self):
        res, calls, sleeps = self.run_llm([FakeAPIError(429), FakeAPIError(429), "ok"])
        self.assertEqual(res, "ok")
        self.assertEqual(calls, ["a", "a", "a"])
        self.assertEqual(len(sleeps), 2)

    def test_5xx_exhausts_then_falls_back_to_next_model(self):
        res, calls, _ = self.run_llm([FakeAPIError(503)] * 3 + ["ok"])
        self.assertEqual(res, "ok")
        self.assertEqual(calls, ["a", "a", "a", "b"])

    def test_timeout_is_retried(self):
        res, calls, _ = self.run_llm([APITimeoutError(), "ok"])
        self.assertEqual((res, calls), ("ok", ["a", "a"]))

    def test_400_and_401_are_not_retried(self):
        for status in (400, 401, 403):
            res, calls, sleeps = self.run_llm([FakeAPIError(status), "ok"])
            self.assertIsInstance(res, FakeAPIError)
            self.assertEqual((calls, sleeps), (["a"], []))

    def test_stops_after_last_model(self):
        res, calls, _ = self.run_llm([FakeAPIError(529)] * 6)
        self.assertIsInstance(res, FakeAPIError)
        self.assertEqual(calls, ["a", "a", "a", "b", "b", "b"])

    def test_honors_retry_after(self):
        err = FakeAPIError(429)
        err.response = type("R", (), {"headers": {"retry-after": "7"}})()
        _, _, sleeps = self.run_llm([err, "ok"])
        self.assertEqual(sleeps, [7.0])


class Pipeline(unittest.TestCase):
    def write_csv(self, path, rows):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["date", "inst", "registro", "n", "margin", "contratante", "scenario", "lula", "flavio", "source_url"])
            w.writerows(rows)

    def test_parse_row_rejects_bad_data(self):
        base = dict(date="2026-10-14", inst="Quaest", registro="BR-08729/2026", lula="44", flavio="46", scenario="real")
        self.assertEqual(ingest.parse_row(base)[1], [])
        for bad in ({"date": "14/10"}, {"lula": "70", "flavio": "50"}, {"scenario": "x"}, {"registro": "123"}, {"inst": ""}):
            self.assertTrue(ingest.parse_row({**base, **bad})[1], bad)

    def test_database_follows_csv_and_json_is_valid(self):
        with tempfile.TemporaryDirectory() as d:
            seed, db, out = f"{d}/p.csv", f"{d}/p.db", f"{d}/p.json"
            self.write_csv(seed, [["2026-10-14", "Quaest", "BR-08729/2026", "", "", "", "real", 44, 46, ""],
                                  ["2026-10-08", "Datafolha", "", "", "", "", "real", 45, 49, ""]])
            polls, _ = ingest.load_seed(seed)
            con = ingest.save(polls, db)
            ingest.export(con, out)
            con.close()
            self.assertEqual(len(json.load(open(out))["polls"]), 2)
            self.write_csv(seed, [["2026-10-14", "Quaest", "BR-08729/2026", "", "", "", "real", 44, 46, ""]])
            polls, _ = ingest.load_seed(seed)
            con = ingest.save(polls, db)
            ingest.export(con, out)  # linha apagada do CSV some do JSON
            con.close()
            self.assertEqual([p["i"] for p in json.load(open(out))["polls"]], ["Quaest"])
            self.assertFalse(Path(out).with_suffix(".tmp").exists())

    def test_safe_cell_blocks_formulas(self):
        self.assertEqual(ingest.safe_cell("=1+1"), "'=1+1")
        self.assertEqual(ingest.safe_cell("Quaest"), "Quaest")


if __name__ == "__main__":
    unittest.main()
