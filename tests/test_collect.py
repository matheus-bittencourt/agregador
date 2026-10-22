"""Rodar com: python3 -m unittest discover -s tests"""
import csv
import sqlite3
import sys
import tempfile
import unittest
import urllib.error
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect  # noqa: E402
import ingest  # noqa: E402

TODAY = date(2026, 10, 22)
FEED = """<?xml version="1.0"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<item><title>Lula e Flávio no 2º turno</title><link>https://a.br/nova</link>
<pubDate>Wed, 21 Oct 2026 10:00:00 +0000</pubDate>
<content:encoded><![CDATA[<p>Quaest: Flávio 45%, Lula 44%. Registro BR-01234/2026.</p><script>x()</script>]]></content:encoded></item>
<item><title>Lula e Flávio em agosto</title><link>https://a.br/velha</link>
<pubDate>Mon, 03 Aug 2026 10:00:00 +0000</pubDate><description>Lula Flávio</description></item>
<item><title>Governador do Tocantins</title><link>https://a.br/outra</link>
<pubDate>Wed, 21 Oct 2026 10:00:00 +0000</pubDate><description>Sem relação</description></item>
</channel></rss>"""


def poll(**kw):
    base = dict(date="2026-10-21", inst="Quaest", registro="BR-01234/2026", lula="44", flavio="45",
                scenario="real", nacional=True)
    return {**base, **kw}


def fake_fetch(pages):
    def fetch(url):
        if url not in pages:
            raise urllib.error.HTTPError(url, 404, "nf", {}, None)
        return pages[url]
    return fetch


class Robots(unittest.TestCase):
    def test_blocks_when_site_disallows_claude(self):
        r = collect.Robots(fake_fetch({"https://a.br/robots.txt": "User-agent: ClaudeBot\nDisallow: /"}))
        self.assertFalse(r.allowed("https://a.br/feed"))

    def test_missing_robots_allows_and_network_error_blocks(self):
        self.assertTrue(collect.Robots(fake_fetch({})).allowed("https://a.br/feed"))

        def boom(url):
            raise OSError("rede")
        self.assertFalse(collect.Robots(boom).allowed("https://a.br/feed"))


class Feed(unittest.TestCase):
    def test_parse_feed_strips_html_and_scripts(self):
        items = collect.parse_feed(FEED)
        self.assertEqual([i["link"] for i in items], ["https://a.br/nova", "https://a.br/velha", "https://a.br/outra"])
        self.assertIn("Flávio 45%", items[0]["text"])
        self.assertNotIn("x()", items[0]["text"])
        self.assertEqual(items[0]["published"], date(2026, 10, 21))

    def test_pdf_links_only_same_host(self):
        html = '<a href="https://a.br/r.pdf">1</a><a href="https://a.br/r.pdf">2</a><a href="https://x.com/y.pdf">3</a>'
        self.assertEqual(collect.pdf_links(html, "https://a.br/p"), ["https://a.br/r.pdf"])


def tse_row(**kw):
    base = dict(NR_PROTOCOLO_REGISTRO="BR012342026", NM_EMPRESA="QUAEST PESQUISAS, CONSULTORIA E PROJETOS",
                NM_EMPRESA_FANTASIA="#NULO#", DS_CARGO="Presidente", SG_UF="BR",
                DS_DADO_MUNICIPIO="A área de abrangência da coleta é todo o território do Brasil.")
    return {**base, **kw}


TSE = {"BR-01234/2026": tse_row()}


class Guardrails(unittest.TestCase):
    def test_accepts_valid_national_poll(self):
        self.assertIsNone(collect.publish_problem(poll(), set(), TODAY, TSE))

    def test_tse_registry_checks(self):
        cases = {
            "sem arquivo do TSE": None,
            "registro ausente": {},
            "outro cargo": {"BR-01234/2026": tse_row(DS_CARGO="Governador, Senador")},
            "pesquisa estadual": {"BR-01234/2026": tse_row(
                DS_DADO_MUNICIPIO="A pesquisa será realizada no Estado do Tocantins.")},
            "outro instituto": {"BR-01234/2026": tse_row(NM_EMPRESA="DATAFOLHA INSTITUTO DE PESQUISAS LTDA.")},
        }
        for name, tse in cases.items():
            self.assertIsNotNone(collect.publish_problem(poll(), set(), TODAY, tse), name)

    def test_rejections(self):
        cases = {
            "estado": poll(nacional=False),
            "sem abrangência": poll(nacional=None),
            "sem registro": poll(registro=None),
            "já conhecido": poll(),
            "votos válidos": poll(lula="49", flavio="51"),
            "futuro": poll(date="2026-10-30"),
            "antiga": poll(date="2026-08-01"),
            "simulação": poll(scenario="sim"),
        }
        for name, it in cases.items():
            known = {"BR-01234/2026"} if name == "já conhecido" else set()
            self.assertIsNotNone(collect.publish_problem(it, known, TODAY, TSE), name)


class Collect(unittest.TestCase):
    def run_collect(self, found, seen=None):
        pages = {"https://a.br/feed": FEED, "https://a.br/nova": "<p>Quaest: Flávio 45%, Lula 44%.</p>",
                 "https://a.br/outra": "<p>Governador</p>"}
        calls = []

        def extract(text, link, pdfs):
            calls.append(link)
            return found
        seen = {} if seen is None else seen
        pub, rev = collect.collect([{"feed": "https://a.br/feed"}], seen, set(), extract, TSE,
                                   fetch=fake_fetch(pages), today=TODAY, log=lambda m: None)
        return pub, rev, calls, seen

    def test_publishes_good_and_stages_doubtful(self):
        pub, rev, calls, seen = self.run_collect([poll(), poll(registro="BR-09999/2026", nacional=False)])
        self.assertEqual(calls, ["https://a.br/nova"])  # velha e irrelevante não vão ao LLM
        self.assertEqual([p["registro"] for p, _ in pub], ["BR-01234/2026"])
        self.assertEqual([p["registro"] for p, _, _ in rev], ["BR-09999/2026"])
        self.assertEqual(set(seen), {"https://a.br/nova", "https://a.br/velha", "https://a.br/outra"})

    def test_seen_items_are_not_sent_again(self):
        _, _, calls, _ = self.run_collect([], seen={"https://a.br/nova": "2026-10-21"})
        self.assertEqual(calls, [])

    def test_llm_failure_retries_next_run(self):
        def extract(text, link, pdfs):
            raise RuntimeError("API fora")
        seen = {}
        collect.collect([{"feed": "https://a.br/feed"}], seen, set(), extract, TSE,
                        fetch=fake_fetch({"https://a.br/feed": FEED}), today=TODAY, log=lambda m: None)
        self.assertNotIn("https://a.br/nova", seen)


class AutoRows(unittest.TestCase):
    def test_append_polls_marks_auto_and_ingest_exports_flag(self):
        with tempfile.TemporaryDirectory() as d:
            seed, db, out = f"{d}/p.csv", f"{d}/p.db", f"{d}/p.json"
            with open(seed, "w", newline="", encoding="utf-8") as fh:
                csv.writer(fh).writerows([ingest.FIELDS, ["2026-10-14", "Quaest", "BR-08729/2026", "", "", "",
                                                          "real", 44, 46, ""]])
            # banco criado antes da coluna "a" existir
            con = sqlite3.connect(db)
            con.execute("""CREATE TABLE polls(key TEXT PRIMARY KEY, d TEXT, i TEXT, r TEXT, n INT, m REAL, c TEXT,
                l REAL, f REAL, k TEXT, s TEXT, v INT, updated TEXT)""")
            con.close()
            collect.append_polls(seed, [(poll(), "https://a.br/nova")])
            polls, bad = ingest.load_seed(seed)
            self.assertEqual(bad, 0)
            con = ingest.save(polls, db)
            ingest.export(con, out)
            con.close()
            import json
            rows = {p["r"]: p for p in json.load(open(out, encoding="utf-8"))["polls"]}
            self.assertFalse(rows["BR-08729/2026"]["a"])
            self.assertTrue(rows["BR-01234/2026"]["a"])
            self.assertEqual(rows["BR-01234/2026"]["s"], "https://a.br/nova")


if __name__ == "__main__":
    unittest.main()
