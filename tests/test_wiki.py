"""Rodar com: python3 -m unittest discover -s tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wiki  # noqa: E402

TODAY = date(2026, 10, 22)


def row(inst, period, lula, flavio, ref="cite_note-1", other="7", margin="±2 pp", n="2,520"):
    return (f'<tr><td><i>{inst}</i></td><td><i>{period}</i></td><td>{lula}</td><td style="b">{flavio}</td>'
            f'<td>{other}</td><td>{margin}</td><td>{n}</td><td>1</td>'
            f'<td><sup class="mw-ref reference"><a href="#{ref}"><span>[1]</span></a></sup></td></tr>')


def page(*rows):
    return ('<h4 id="Aug–Oct_(Campaign_period)">x</h4><table><tr><td>a</td></tr></table>'
            '<h4 id="October_(after_1st_round)">October</h4>'
            '<table class="wikitable"><tbody><tr><th rowspan="3">Pollster</th><th>Polling</th></tr>'
            + "".join(rows) + '</tbody></table><h4 id="Aug–Oct_(Campaign_period)_2">x</h4>'
            '<table><tr><td>Velha</td><td>1–2 Sep</td><td>40</td><td>40</td><td>1</td><td>1</td><td>1</td>'
            '<td>1</td></tr></table>'
            '<ol><li id="cite_note-1"><a href="#cite_ref-1">↑</a> <a class="external text" '
            'href="https://www1.folha.uol.com.br/x.shtml">Datafolha</a></li>'
            '<li id="cite_note-2"><a class="external text" href="javascript:alert(1)">x</a></li></ol>'
            '<script>"wgRevisionId":1381496003</script>')


class EndDate(unittest.TestCase):
    def test_periods(self):
        self.assertEqual(wiki.end_date("20–22 Oct"), date(2026, 10, 22))
        self.assertEqual(wiki.end_date("30 Sep – 2 Oct"), date(2026, 10, 2))
        self.assertIsNone(wiki.end_date("Oct"))
        self.assertIsNone(wiki.end_date("31 Feb"))


class Polls(unittest.TestCase):
    def test_reads_only_the_section_table(self):
        items, bad = wiki.polls(page(row("Datafolha", "20–22 Oct", "46", "47"),
                                     row("Quaest", "17–20 Oct", "44", "45", n="2,154")), TODAY)
        self.assertEqual(bad, 0)
        self.assertEqual([p["i"] for p in items], ["Datafolha", "Quaest"])
        self.assertEqual(items[0], {"i": "Datafolha", "p": "20–22 Oct", "d": "2026-10-22", "l": 46.0, "f": 47.0,
                                    "o": 7.0, "m": 2.0, "n": 2520, "u": "https://www1.folha.uol.com.br/x.shtml"})
        self.assertEqual(wiki.revision(page()), 1381496003)

    def test_guardrails_drop_suspicious_rows(self):
        rows = [row("Soma", "20–22 Oct", "55", "50"),          # passa de 100%
                row("Baixo", "20–22 Oct", "4", "47"),          # fora da faixa plausível
                row("Futuro", "28–29 Oct", "46", "47"),
                row("Antiga", "1–2 Aug", "46", "47"),
                row("Sem link", "20–22 Oct", "46", "47", ref="cite_note-2"),  # só link não https
                row("Amostra", "20–22 Oct", "46", "47", n="120"),
                row("", "20–22 Oct", "46", "47")]
        items, bad = wiki.polls(page(*rows), TODAY)
        self.assertEqual(items, [])
        self.assertEqual(bad, len(rows))

    def test_missing_section_returns_nothing(self):
        self.assertEqual(wiki.polls(page(row("Datafolha", "20–22 Oct", "46", "47")), TODAY, section="Nope"),
                         ([], 0))


if __name__ == "__main__":
    unittest.main()
