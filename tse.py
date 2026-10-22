#!/usr/bin/env python3
"""Baixa do portal de dados abertos do TSE o registro das pesquisas nacionais e grava data/tse.csv,
no formato que o `ingest.py --tse` lê (latin-1, separado por ";").

Junta ao arquivo de pesquisas (pesquisa_eleitoral_<ano>_BRASIL.csv) a coluna NM_CONTRATANTE, que o
TSE publica em outro arquivo. O TSE regenera os dois todo dia. Sem LLM.

Uso: python tse.py [--ano 2026] [--out data/tse.csv]
"""
import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

import collect

BASE = "https://cdn.tse.jus.br/estatistica/sead/odsele/pesquisa_eleitoral"
MAX_ZIP = 100 * 2**20


def brasil_csv(zip_bytes, prefix):
    """Linhas do CSV nacional (…_BRASIL.csv) de um ZIP do TSE."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        name = next(n for n in z.namelist() if n.startswith(prefix) and n.endswith("_BRASIL.csv"))
        text = z.read(name).decode("latin-1")
    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    return reader.fieldnames, list(reader)


def merge(polls, contratantes):
    """Acrescenta NM_CONTRATANTE (vários contratantes separados por " / ") a cada registro."""
    by_reg = {}
    for r in contratantes:
        nome = (r.get("NM_CONTRATANTE") or "").strip()
        if nome and nome not in by_reg.setdefault(r["NR_PROTOCOLO_REGISTRO"], []):
            by_reg[r["NR_PROTOCOLO_REGISTRO"]].append(nome)
    for r in polls:
        r["NM_CONTRATANTE"] = " / ".join(by_reg.get(r["NR_PROTOCOLO_REGISTRO"], []))
    return polls


def fetch_zip(url):
    req = urllib.request.Request(url, headers={"User-Agent": collect.UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read(MAX_ZIP + 1)
    if len(data) > MAX_ZIP:
        raise ValueError("arquivo grande demais")
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ano", default="2026")
    ap.add_argument("--out", default="data/tse.csv")
    a = ap.parse_args()
    try:
        fields, polls = brasil_csv(fetch_zip(f"{BASE}/pesquisa_eleitoral_{a.ano}.zip"), "pesquisa_eleitoral")
        _, contr = brasil_csv(fetch_zip(f"{BASE}/pesquisa_contratante_{a.ano}.zip"), "pesquisa_contratante")
    except Exception as exc:  # mantém o tse.csv anterior, se houver
        sys.exit(f"falha ao baixar os arquivos do TSE: {type(exc).__name__}")
    out = Path(a.out)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="latin-1", errors="replace") as fh:
        w = csv.DictWriter(fh, fieldnames=fields + ["NM_CONTRATANTE"], delimiter=";")
        w.writeheader()
        w.writerows(merge(polls, contr))
    tmp.replace(out)
    print(f"{len(polls)} registros nacionais -> {out}")


if __name__ == "__main__":
    main()
