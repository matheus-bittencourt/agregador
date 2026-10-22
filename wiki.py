#!/usr/bin/env python3
"""Pesquisas recentes do 2º turno compiladas na Wikipédia (en) -> site/wiki.json

Fonte secundária, sem LLM: lê a tabela "October (after 1st round)" da página de pesquisas e guarda,
para cada linha, instituto, período, percentuais, margem, amostra e o link da matéria citada.
Não entra no polls.csv nem passa pelas travas do collect.py (não há registro do TSE na tabela):
o painel mostra essas linhas num bloco à parte, marcado como Wikipédia, com o link de cada fonte.

robots.txt da Wikipédia (conferido em 22/10/2026): /wiki/ liberado; /w/ e /api/ (inclusive api.php)
bloqueados para robôs, por isso o script lê a página HTML. Conteúdo sob CC BY-SA 4.0: o painel atribui.

Uso: python wiki.py
"""
import argparse
import json
import re
import sys
from datetime import date, datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import collect

PAGE = "https://en.wikipedia.org/wiki/Opinion_polling_for_the_2026_Brazilian_presidential_election"
SECTION = "October_(after_1st_round)"
YEAR = 2026
MAX_AGE = 30  # dias
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov",
                                      "dec"], 1)}
SOURCE = {"nome": "Wikipédia (en), Opinion polling for the 2026 Brazilian presidential election", "url": PAGE,
          "licenca": "CC BY-SA 4.0"}


class _Table(HTMLParser):
    """Linhas (<tr>) da primeira tabela depois do título da seção: cada célula vira (texto, ids de nota, links)."""

    def __init__(self, section):
        super().__init__(convert_charrefs=True)
        self.section, self.state, self.depth = section, "seek", 0
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.state == "seek":
            if a.get("id") == self.section:
                self.state = "head"
        elif self.state == "head" and tag == "table":
            self.state, self.depth = "table", 1
        elif self.state == "table":
            if tag == "table":
                self.depth += 1
            elif tag == "tr" and self.depth == 1:
                self.row = []
            elif tag in ("td", "th") and self.row is not None:
                self.cell = {"tag": tag, "text": [], "refs": [], "links": []}
            elif tag == "a" and self.cell is not None:
                href = a.get("href") or ""
                if href.startswith("#cite_note-"):
                    self.cell["refs"].append(href[1:])
                elif href.startswith("https://") and "external" in (a.get("class") or ""):
                    self.cell["links"].append(href)
            elif tag == "sup" and self.cell is not None:
                self.cell["text"].append(" ")

    def handle_endtag(self, tag):
        if self.state != "table":
            return
        if tag == "table":
            self.depth -= 1
            if not self.depth:
                self.state = "done"
        elif tag in ("td", "th") and self.cell is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == "tr" and self.row is not None:
            self.rows.append(self.row)
            self.row = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)


class _Refs(HTMLParser):
    """Primeiro link externo de cada nota de rodapé (<li id="cite_note-...">)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cur, self.urls = None, {}

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "li" and (a.get("id") or "").startswith("cite_note-"):
            self.cur = a["id"]
        elif tag == "a" and self.cur and self.cur not in self.urls:
            href = a.get("href") or ""
            if href.startswith("https://") and "external" in (a.get("class") or ""):
                self.urls[self.cur] = href

    def handle_endtag(self, tag):
        if tag == "li":
            self.cur = None


def _text(cell):
    return re.sub(r"\[\d+\]", "", re.sub(r"\s+", " ", "".join(cell["text"]))).strip()


def _num(s):
    m = re.search(r"\d+(?:[.,]\d+)*", s or "")
    return float(m.group().replace(",", "")) if m else None


def end_date(period, year=YEAR):
    """Último dia do período de campo: "20–22 Oct" -> 2026-10-22; "30 Sep – 2 Oct" -> 2026-10-02."""
    days, months = re.findall(r"\d{1,2}", period), re.findall(r"[A-Za-z]{3,}", period)
    month = MONTHS.get(months[-1][:3].lower()) if months else None
    if not days or not month:
        return None
    try:
        return date(year, month, int(days[-1]))
    except ValueError:
        return None


def polls(html, today, section=SECTION, max_age=MAX_AGE):
    """Linhas válidas da tabela, da mais recente para a mais antiga, e quantas foram descartadas."""
    t = _Table(section)
    t.feed(html)
    refs = _Refs()
    refs.feed(html)
    out, bad = [], 0
    for row in t.rows:
        if len(row) < 8 or any(c["tag"] != "td" for c in row):
            continue  # cabeçalho
        inst, period = _text(row[0]), _text(row[1])
        lula, flavio, other = _num(_text(row[2])), _num(_text(row[3])), _num(_text(row[4]))
        margin, n = _num(_text(row[5])), _num(_text(row[6]))
        link = next((refs.urls[r] for c in row[7:] for r in c["refs"] if r in refs.urls), None) \
            or next((u for c in row[7:] for u in c["links"]), None)
        d = end_date(period)
        # Travas contra erro de digitação ou vandalismo na página: na dúvida, a linha fica de fora.
        ok = (inst and d and link and lula is not None and flavio is not None
              and 15 <= lula <= 75 and 15 <= flavio <= 75 and lula + flavio <= 100
              and today - timedelta(days=max_age) <= d <= today + timedelta(days=1)
              and (n is None or n >= 300) and (margin is None or margin <= 10))
        if not ok:
            bad += 1
            continue
        out.append({"i": inst, "p": period, "d": d.isoformat(), "l": lula, "f": flavio, "o": other,
                    "m": margin, "n": int(n) if n else None, "u": link})
    out.sort(key=lambda p: p["d"], reverse=True)
    return out, bad


def revision(html):
    m = re.search(r'"wgRevisionId":(\d+)', html)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/wiki.json")
    a = ap.parse_args()
    if not collect.Robots().allowed(PAGE):
        sys.exit(f"robots.txt não permite ler {PAGE}")
    try:
        html = collect.fetch(PAGE)
    except Exception as exc:  # mantém o wiki.json anterior se a página falhar
        sys.exit(f"falha ao ler {PAGE}: {type(exc).__name__}")
    items, bad = polls(html, datetime.now(timezone.utc).date())
    if bad:
        print(f"[aviso] {bad} linhas da tabela descartadas pelas travas")
    if not items:
        sys.exit("nenhuma pesquisa válida na tabela; mantém o wiki.json anterior")
    out = Path(a.out)
    if out.exists() and json.loads(out.read_text(encoding="utf-8")).get("itens") == items:
        print("Sem pesquisas novas na Wikipédia.")  # não reescreve: evita um commit a cada rodada
        return
    rev = revision(html)
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "fonte": SOURCE | {"revisao": f"https://en.wikipedia.org/w/index.php?oldid={rev}" if rev else None},
           "itens": items}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(a.out)
    print(f"{len(items)} pesquisas -> {a.out}")


if __name__ == "__main__":
    main()
