"""Guarda o site/espontanea.json, que é curado à mão."""
import json
import unittest
from datetime import datetime
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "site" / "espontanea.json"


class Espontanea(unittest.TestCase):
    def test_itens_validos(self):
        doc = json.loads(FILE.read_text(encoding="utf-8"))
        self.assertTrue(doc["itens"])
        for it in doc["itens"]:
            datetime.strptime(it["d"], "%Y-%m-%d")
            self.assertTrue(it["i"].strip())
            self.assertRegex(it["r"], r"^BR-\d{5}/\d{4}$")
            self.assertTrue(it["u"].startswith("https://"))
            for k in ("l", "f"):
                self.assertTrue(0 <= it[k] <= 100, (it["i"], k))
            total = sum(it.get(k) or 0 for k in ("l", "f", "bn", "nd", "o"))
            self.assertTrue(99 <= total <= 100.5, (it["i"], total))  # cenário espontâneo soma ~100%


if __name__ == "__main__":
    unittest.main()
