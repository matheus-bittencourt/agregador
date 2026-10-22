#!/usr/bin/env python3
"""Coleta automática: lê os feeds de data/sources.csv, extrai pesquisas novas com o LLM e
publica direto em data/polls.csv (origem=auto) as que passam nas travas de PUBLISH_RULES.
O que não passa vai para data/staged.csv, com o motivo, para revisão humana.

Uso:
  python collect.py               # roda uma vez (o GitHub Actions chama a cada 2 h)
  python collect.py --dry-run     # mostra o que faria, sem chamar o LLM nem gravar nada
"""
import argparse
import csv
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import ingest

UA = "agregador-pesquisas/1.0"
# O texto coletado vai para a API da Anthropic: respeita também o que o site diz aos robôs dela.
ROBOT_AGENTS = (UA, "ClaudeBot", "anthropic-ai")
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
RELEVANT = re.compile(r"lula.*fl[áa]vio|fl[áa]vio.*lula|BR-?\d{5}/2026", re.I | re.S)
MAX_SUM = 97  # Lula + Flávio acima disso sugere votos válidos lidos como total
MAX_AGE = 30  # dias
MAX_PDF = 10 * 2**20  # bytes; institutos como a Paraná Pesquisas só publicam os números em PDF
PDF_LINK = re.compile(r'href="(https?://[^"]+?\.pdf)"', re.I)


def fetch_bytes(url, timeout=30, limit=MAX_PDF):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise ValueError("arquivo grande demais")
    return data


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode(r.headers.get_content_charset() or "utf-8", "replace")


def pdf_links(html, page_url, limit=2):
    """PDFs do mesmo site linkados na página (os relatórios das pesquisas)."""
    host, out = urlsplit(page_url).netloc, []
    for u in PDF_LINK.findall(html or ""):
        if urlsplit(u).netloc == host and u not in out:
            out.append(u)
    return out[:limit]


class Robots:
    """Cache de robots.txt por host. Sem robots.txt (404) vale tudo; erro de rede bloqueia."""

    def __init__(self, fetch=fetch):
        self.fetch, self.cache = fetch, {}

    def allowed(self, url):
        p = urlsplit(url)
        base = f"{p.scheme}://{p.netloc}"
        if base not in self.cache:
            rp = RobotFileParser()
            try:
                rp.parse(self.fetch(base + "/robots.txt").splitlines())
            except urllib.error.HTTPError as exc:
                rp.parse([] if exc.code == 404 else ["User-agent: *", "Disallow: /"])
            except Exception:
                rp.parse(["User-agent: *", "Disallow: /"])
            self.cache[base] = rp
        return all(self.cache[base].can_fetch(a, url) for a in ROBOT_AGENTS)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.out, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.out.append(data)


def html_text(html):
    p = _Text()
    p.feed(html or "")
    return re.sub(r"\s+", " ", " ".join(p.out)).strip()


def parse_feed(xml):
    """Itens de um feed RSS: dicts com link, title, published (date ou None) e text."""
    items = []
    for it in ET.fromstring(xml).iter("item"):
        link = (it.findtext("link") or it.findtext("guid") or "").strip()
        if not link.startswith(("http://", "https://")):
            continue
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate") or "").date()
        except (TypeError, ValueError):
            pub = None
        body = it.findtext(CONTENT) or it.findtext("description") or ""
        title = (it.findtext("title") or "").strip()
        items.append(dict(link=link, title=title, published=pub, text=html_text(f"{title}. {body}")))
    return items


def load_sources(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return [r for r in csv.DictReader(fh) if (r.get("ativo") or "").strip().lower() == "sim"]


def publish_problem(it, known, today):
    """Motivo para NÃO publicar automaticamente (None = pode publicar)."""
    p, errs = ingest.parse_row(it)
    if errs:
        return "; ".join(errs)
    if it.get("nacional") is not True:
        return "não é pesquisa nacional (ou abrangência não informada)"
    if p["k"] != "real":
        return "cenário não é o 2º turno real"
    if not p["r"]:
        return "sem registro BR-00000/2026"
    if p["r"] in known:
        return "registro já está no polls.csv"
    if p["l"] + p["f"] > MAX_SUM:
        return f"Lula + Flávio > {MAX_SUM}%: provavelmente votos válidos"
    d = date.fromisoformat(p["d"])
    if d > today or d < today - timedelta(days=MAX_AGE):
        return "data de divulgação fora da janela de 30 dias"
    return None


def append_polls(path, rows):
    """Acrescenta pesquisas ao polls.csv, criando a coluna origem se faltar."""
    with open(path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header, old = list(reader.fieldnames), list(reader)
    if "origem" not in header:
        header.append("origem")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(old)
        for it, src in rows:
            w.writerow({k: ingest.safe_cell(it.get(k)) for k in ingest.FIELDS[:-1]}
                       | {"source_url": src, "origem": "auto"})


def collect(sources, seen, known, extract, fetch=fetch, fetch_bytes=fetch_bytes, today=None, max_items=12,
            log=ingest._log):
    """Percorre os feeds e devolve (publicar, revisar). Atualiza `seen` e `known` no lugar.

    Um item só entra em `seen` depois de processado; se o LLM falhar, tenta de novo na próxima rodada.
    """
    today = today or datetime.now(timezone.utc).date()
    robots, publish, review, done = Robots(fetch), [], [], 0
    for src in sources:
        feed = src["feed"].strip()
        if not robots.allowed(feed):
            log(f"[aviso] robots.txt não permite ler {feed}; fonte ignorada")
            continue
        try:
            items = parse_feed(fetch(feed))
        except Exception as exc:
            log(f"[aviso] falha ao ler {feed}: {type(exc).__name__}")
            continue
        for it in items:
            link = it["link"]
            if link in seen:
                continue
            if it["published"] and it["published"] < today - timedelta(days=MAX_AGE):
                seen[link] = today.isoformat()
                continue
            text, pdfs = it["text"], []
            if len(text) < 600 and robots.allowed(link):  # feed só com resumo: busca a página
                try:
                    html = fetch(link)
                    text = f"{it['title']}. {html_text(html)}"
                    if RELEVANT.search(text):
                        pdfs = [fetch_bytes(u) for u in pdf_links(html, link) if robots.allowed(u)]
                except Exception as exc:
                    log(f"[aviso] falha ao ler {link}: {type(exc).__name__}")
                    continue
            if not RELEVANT.search(text):
                seen[link] = today.isoformat()
                continue
            if done >= max_items:
                log(f"[info] limite de {max_items} textos por rodada; o resto fica para a próxima")
                return publish, review
            try:
                found = extract(text, link, pdfs)
            except Exception as exc:
                log(f"[aviso] extração falhou para {link}: {type(exc).__name__}")
                continue
            done += 1
            seen[link] = today.isoformat()
            for p in found:
                why = publish_problem(p, known, today)
                if why:
                    review.append((p, link, why))
                else:
                    publish.append((p, link))
                    known.add(ingest.norm_reg(p["registro"]))
                    log(f"[auto] {p['inst']} {p['date']} {ingest.norm_reg(p['registro'])}: "
                        f"Lula {p['lula']}, Flávio {p['flavio']} ({link})")
    return publish, review


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="data/sources.csv")
    ap.add_argument("--seed", default="data/polls.csv")
    ap.add_argument("--seen", default="data/seen.json")
    ap.add_argument("--staged", default="data/staged.csv")
    ap.add_argument("--max", type=int, default=12, help="máximo de textos enviados ao LLM por rodada")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    seen = json.loads(Path(a.seen).read_text(encoding="utf-8")) if Path(a.seen).exists() else {}
    polls, _ = ingest.load_seed(a.seed)
    known = {p["r"] for p in polls.values() if p["r"]}
    if a.dry_run:
        def extract(text, link, pdfs):
            print(f"[dry-run] enviaria ao LLM: {link} ({len(text)} caracteres, {len(pdfs)} PDF)")
            return []
    else:
        client = ingest.llm_client()
        def extract(text, link, pdfs):
            return ingest.extract_items(client, text, link, pdfs)

    publish, review = collect(load_sources(a.sources), seen, known, extract, max_items=a.max)
    if a.dry_run:
        return
    if publish:
        append_polls(a.seed, publish)
    ingest.stage(review, a.staged)
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=90)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    Path(a.seen).write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(publish)} publicadas automaticamente, {len(review)} para revisão em {a.staged}")


if __name__ == "__main__":
    sys.exit(main())
