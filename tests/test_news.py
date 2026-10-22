"""Rodar com: python3 -m unittest discover -s tests"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import news  # noqa: E402

FEED = """<?xml version="1.0"?><rss><channel>
<item><title>Lula e Flávio fazem campanha</title><link>https://agenciabrasil.ebc.com.br/a</link>
<pubDate>Wed, 21 Oct 2026 10:00:00 -0300</pubDate><description>x</description></item>
<item><title>Câmara aprova projeto de saneamento</title><link>https://agenciabrasil.ebc.com.br/b</link>
<pubDate>Thu, 22 Oct 2026 10:00:00 -0300</pubDate></item>
<item><title>TSE divulga horário da apuração</title><link>https://agenciabrasil.ebc.com.br/c</link>
<pubDate>Thu, 22 Oct 2026 11:00:00 -0300</pubDate></item>
<item><title>Segundo turno: eleitores sem link</title><link>javascript:alert(1)</link></item>
</channel></rss>"""


class Headlines(unittest.TestCase):
    def test_filters_election_news_newest_first(self):
        items = news.headlines(FEED)
        self.assertEqual([i["u"][-1] for i in items], ["c", "a"])
        self.assertEqual(items[0], {"t": "TSE divulga horário da apuração",
                                    "u": "https://agenciabrasil.ebc.com.br/c", "d": "2026-10-22"})

    def test_limit(self):
        self.assertEqual(len(news.headlines(FEED, limit=1)), 1)


if __name__ == "__main__":
    unittest.main()
