#!/usr/bin/env python3
"""Manchetes sobre a eleição para o painel: RSS de política da Agência Brasil (EBC) -> site/news.json

Só guarda título, data e link (o site da EBC reserva os direitos do texto). Sem LLM.
O site do TSE bloqueia acesso automatizado (403 até no robots.txt), por isso não entra aqui.

Uso: python news.py
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import collect

FEED = "https://agenciabrasil.ebc.com.br/rss/politica/feed.xml"
SOURCE = {"nome": "Agência Brasil (EBC)", "url": "https://agenciabrasil.ebc.com.br/politica"}
ELECTION = re.compile(r"elei|turno|lula|fl[áa]vio|tse|apura|urna|eleitor|vot[oa]|presiden", re.I)


def headlines(xml, limit=8):
    items = [it for it in collect.parse_feed(xml) if ELECTION.search(it["title"])]
    items.sort(key=lambda it: it["published"] or datetime.min.date(), reverse=True)
    return [{"t": it["title"], "u": it["link"],
             "d": it["published"].isoformat() if it["published"] else None} for it in items[:limit]]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="site/news.json")
    a = ap.parse_args()
    if not collect.Robots().allowed(FEED):
        sys.exit(f"robots.txt não permite ler {FEED}")
    try:
        items = headlines(collect.fetch(FEED))
    except Exception as exc:  # mantém o news.json anterior se o feed falhar
        sys.exit(f"falha ao ler {FEED}: {type(exc).__name__}")
    out = Path(a.out)
    if out.exists() and json.loads(out.read_text(encoding="utf-8")).get("itens") == items:
        print("Sem manchetes novas.")  # não reescreve: evita um commit a cada rodada
        return
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "fonte": SOURCE, "itens": items}
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(a.out)
    print(f"{len(items)} manchetes -> {a.out}")


if __name__ == "__main__":
    main()
