#!/usr/bin/env python3
"""Pipeline de pesquisas do 2º turno 2026: CSV curado + registro do TSE -> SQLite -> site/polls.json

Uso:
  python ingest.py                          # data/polls.csv -> site/polls.json
  python ingest.py --tse data/tse.csv       # confirma registros e completa amostra, margem e contratante
  python ingest.py --extract artigos/*.txt  # extrai pesquisas de textos para data/staged.csv (revisão humana)
"""
import argparse
import base64
import csv
import json
import os
import random
import re
import sqlite3
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ELECTION = "2026-10-25"
# Aceita "BR-08729/2026" (como os institutos divulgam) e "BR087292026" (como o TSE grava).
REG = re.compile(r"\bBR-?(\d{5})/?(\d{4})\b", re.I)
TSE_NULL = {"#NULO#", "#NE#", "#NULO", "#NE"}

# Colunas do arquivo de dados abertos do TSE (pesquisa_eleitoral_2026_BRASIL.csv, conferido em
# 22/10/2026). O arquivo não traz margem de erro; NM_CONTRATANTE vem do arquivo de contratantes,
# que o tse.py junta ao principal.
TSE_COLS = {
    "registro": ["NR_PROTOCOLO_REGISTRO", "registro"],
    "n": ["QT_ENTREVISTADO", "amostra"],
    "contratante": ["NM_CONTRATANTE", "contratante"],
    "empresa": ["NM_EMPRESA", "NM_EMPRESA_FANTASIA", "empresa"],
}


def norm_reg(s):
    m = REG.search(s or "")
    return f"BR-{m[1]}/{m[2]}" if m else None


def fold(s):
    """Maiúsculas sem acento, para comparar nomes."""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()


def num(s):
    try:
        return float(str(s).replace(",", "."))
    except (TypeError, ValueError):
        return None


def pick(row, names):
    low = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        v = (low.get(n.lower()) or "").strip()
        if v and v not in TSE_NULL:
            return v
    return None


def parse_row(r):
    """Valida uma linha do CSV. Retorna (pesquisa, lista de erros)."""
    errs = []
    d = (r.get("date") or "").strip()
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except ValueError:
        errs.append("data inválida")
    l, f = num(r.get("lula")), num(r.get("flavio"))
    if l is None or f is None or not (0 <= l <= 100 and 0 <= f <= 100) or l + f > 100:
        errs.append("percentuais inválidos")
    k = (r.get("scenario") or "").strip()
    if k not in ("real", "sim"):
        errs.append("scenario deve ser real ou sim")
    raw_reg = (r.get("registro") or "").strip()
    reg = norm_reg(raw_reg)
    if raw_reg and not reg:
        errs.append("registro fora do formato BR-00000/2026")
    inst = (r.get("inst") or "").strip()
    if not inst:
        errs.append("instituto vazio")
    n = num(r.get("n"))
    p = dict(d=d, i=inst, r=reg, n=int(n) if n else None, m=num(r.get("margin")),
             c=(r.get("contratante") or "").strip() or None, l=l, f=f, k=k,
             s=(r.get("source_url") or "").strip() or None, v=False,
             a=(r.get("origem") or "").strip() == "auto")  # publicada pelo collect.py sem revisão
    return p, errs


def key(p):
    return p["r"] or f'{p["i"]}|{p["d"]}|{p["k"]}'


def load_seed(path):
    polls, bad = {}, 0
    with open(path, newline="", encoding="utf-8") as fh:
        for ln, row in enumerate(csv.DictReader(fh), start=2):
            p, errs = parse_row(row)
            if errs:
                bad += 1
                print(f"[erro] {path}:{ln}: {'; '.join(errs)}", file=sys.stderr)
                continue
            polls[key(p)] = p  # a última linha vence (deduplicação)
    return polls, bad


def enrich(polls, path, encoding, delimiter):
    with open(path, newline="", encoding=encoding) as fh:
        idx = {}
        for row in csv.DictReader(fh, delimiter=delimiter):
            reg = norm_reg(pick(row, TSE_COLS["registro"]))
            if reg:
                idx[reg] = row
    for p in polls.values():
        if not p["r"]:
            continue
        row = idx.get(p["r"])
        if not row:
            print(f"[aviso] {p['r']} ({p['i']}, {p['d']}) não encontrado no arquivo do TSE", file=sys.stderr)
            continue
        # Registro trocado (de outro instituto) não pode virar "confirmado".
        empresa = " ".join(fold(row.get(c)) for c in TSE_COLS["empresa"] if row.get(c) not in (None, *TSE_NULL))
        nomes = [w for w in re.split(r"[^A-Z0-9]+", fold(p["i"])) if len(w) >= 4]  # "Genial/Quaest" -> GENIAL, QUAEST
        if empresa.strip() and nomes and not any(w in empresa for w in nomes):
            print(f"[aviso] {p['r']} está registrado no TSE por {empresa.strip()[:60]}, não por {p['i']}; "
                  "não confirmado", file=sys.stderr)
            continue
        p["v"] = True
        if p["n"] is None and (n := num(pick(row, TSE_COLS["n"]))):
            p["n"] = int(n)
        if p["c"] is None:
            p["c"] = pick(row, TSE_COLS["contratante"])


def save(polls, db):
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE IF NOT EXISTS polls(
        key TEXT PRIMARY KEY, d TEXT, i TEXT, r TEXT, n INT, m REAL, c TEXT,
        l REAL, f REAL, k TEXT, s TEXT, v INT, updated TEXT, a INT DEFAULT 0)""")
    if "a" not in [r[1] for r in con.execute("PRAGMA table_info(polls)")]:  # banco anterior à coleta automática
        con.execute("ALTER TABLE polls ADD COLUMN a INT DEFAULT 0")
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for p in polls.values():
        con.execute("""INSERT INTO polls(key,d,i,r,n,m,c,l,f,k,s,v,updated,a) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(key) DO UPDATE SET d=excluded.d, i=excluded.i, r=excluded.r,
              n=COALESCE(excluded.n, polls.n), m=COALESCE(excluded.m, polls.m),
              c=COALESCE(excluded.c, polls.c), l=excluded.l, f=excluded.f, k=excluded.k,
              s=COALESCE(excluded.s, polls.s), v=MAX(polls.v, excluded.v), updated=excluded.updated,
              a=excluded.a""",
                    (key(p), p["d"], p["i"], p["r"], p["n"], p["m"], p["c"], p["l"], p["f"],
                     p["k"], p["s"], int(p["v"]), now, int(p["a"])))
    # O CSV é a fonte de verdade: remove do banco o que foi apagado ou corrigido nele.
    keys = [key(p) for p in polls.values()]
    con.execute(f"DELETE FROM polls WHERE key NOT IN ({','.join('?' * len(keys))})", keys)
    con.commit()
    return con


def export(con, out):
    cur = con.execute("SELECT d,i,r,n,m,c,l,f,k,s,v,a FROM polls ORDER BY d, i")
    cols = ["d", "i", "r", "n", "m", "c", "l", "f", "k", "s", "v", "a"]
    polls = [dict(zip(cols, row)) for row in cur]
    for p in polls:
        p["v"], p["a"] = bool(p["v"]), bool(p["a"])
    doc = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
           "election_date": ELECTION, "polls": polls}
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(out).with_suffix(".tmp")  # escreve e renomeia: o painel nunca lê JSON pela metade
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(out)
    print(f"{len(polls)} pesquisas -> {out}")


PROMPT = (
    "Extraia do texto as pesquisas nacionais de intenção de voto do 2º turno presidencial "
    "(Lula x Flávio Bolsonaro). Responda SOMENTE com uma lista JSON de objetos com as chaves: "
    "date (YYYY-MM-DD, divulgação), inst, registro (BR-00000/2026 ou null), n (inteiro ou null), "
    "margin (número ou null), contratante (texto ou null), lula, flavio (percentuais sobre o total "
    "de entrevistados, nunca votos válidos), scenario (\"real\"), nacional (true só se a amostra é "
    "do eleitorado do Brasil inteiro; false para pesquisas de um estado ou município). Não invente "
    "nada: use null quando o dado não estiver no texto. Se houver só votos válidos, devolva lista vazia."
)
FIELDS = ["date", "inst", "registro", "n", "margin", "contratante", "scenario", "lula", "flavio", "source_url"]
STAGED_FIELDS = FIELDS + ["motivo"]


RETRYABLE = {429, 500, 502, 503, 504, 529}
NETWORK_ERRORS = ("APIConnectionError", "APITimeoutError", "TimeoutError", "ConnectionError")
# Modelos permitidos, em ordem de preferência (fallback). Só da conta Anthropic que você já usa.
MODELS = [m.strip() for m in os.environ.get("LLM_MODELS", "claude-sonnet-5-5").split(",") if m.strip()]


def _log(msg):
    print(msg, file=sys.stderr)


def is_retryable(exc):
    status = getattr(exc, "status_code", None)
    if status is not None:
        return status in RETRYABLE
    return type(exc).__name__ in NETWORK_ERRORS


def retry_after(exc):
    try:
        return min(float(exc.response.headers["retry-after"]), 60.0)
    except Exception:
        return None


def call_llm(create, models, retries=3, base=1.0, sleep=time.sleep, log=_log):
    """Chama create(model) com retry (backoff exponencial + jitter) e fallback entre modelos.

    Só repete erros retentáveis (429, 5xx, rede). Erros 400/401/403 sobem na hora.
    Nunca registra chaves nem o conteúdo do prompt.
    """
    last = None
    for model in models:
        for attempt in range(retries + 1):
            try:
                resp = create(model)
                log(f"[llm] respondeu: {model} (tentativa {attempt + 1})")
                return resp
            except Exception as exc:
                last = exc
                if not is_retryable(exc):
                    raise
                if attempt == retries:
                    log(f"[llm] {model} esgotou as tentativas ({type(exc).__name__}); tentando o próximo modelo")
                    break
                wait = retry_after(exc) or min(base * 2 ** attempt, 30) * random.uniform(0.5, 1.5)
                log(f"[llm] {model}: {type(exc).__name__}, nova tentativa em {wait:.1f}s")
                sleep(wait)
    raise last


def safe_cell(v):
    """Evita injeção de fórmula quando o CSV é aberto no Excel."""
    return "'" + v if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v


def llm_client():
    import anthropic  # pip install anthropic; usa ANTHROPIC_API_KEY
    return anthropic.Anthropic(timeout=60.0, max_retries=0)  # retries ficam em call_llm


def extract_items(client, text, src, pdfs=()):
    """Extrai pesquisas de um texto. Devolve só os itens que passam na validação do CSV curado.

    Levanta exceção se o LLM falhar ou não responder JSON, para quem chama decidir se tenta de novo.
    """
    prompt = f"{PROMPT}\n\n<texto>\n{text[:20000]}\n</texto>"
    if pdfs:
        prompt += "\nOs PDFs anexos fazem parte da mesma publicação; use-os como fonte."
    content = [{"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                               "data": base64.b64encode(pdf).decode()}} for pdf in pdfs]
    content.append({"type": "text", "text": prompt})
    msg = call_llm(lambda m: client.messages.create(
        model=m, max_tokens=1500, messages=[{"role": "user", "content": content}]), MODELS)
    raw = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    items = json.loads(raw)
    out = []
    for it in items if isinstance(items, list) else []:
        if not isinstance(it, dict):
            continue
        it = {k: v if v is None or isinstance(v, bool) else str(v) for k, v in it.items()}
        _, errs = parse_row({**it, "source_url": src})  # mesma validação do CSV curado
        if errs:
            _log(f"[aviso] {src}: item descartado ({'; '.join(errs)})")
            continue
        out.append(it)
    return out


def stage(rows, staged):
    """Acrescenta a staged.csv, para revisão humana, linhas (item, fonte, motivo)."""
    if not rows:
        return
    new = not Path(staged).exists()
    with open(staged, "a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=STAGED_FIELDS)
        if new:
            w.writeheader()
        for it, src, why in rows:
            w.writerow({k: safe_cell(it.get(k)) for k in FIELDS[:-1]} | {"source_url": src, "motivo": why})


def extract(files, staged):
    client = llm_client()
    rows = []
    for fp in files:
        try:
            items = extract_items(client, Path(fp).read_text(encoding="utf-8"), fp)
        except json.JSONDecodeError:
            _log(f"[aviso] resposta não é JSON para {fp}")
            continue
        except Exception as exc:
            _log(f"[aviso] falha ao processar {fp}: {type(exc).__name__}")
            continue
        rows += [(it, fp, "extraída de arquivo local") for it in items]
    stage(rows, staged)
    print(f"Revise {staged} e copie as linhas corretas para data/polls.csv.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", default="data/polls.csv")
    ap.add_argument("--db", default="data/polls.db")
    ap.add_argument("--out", default="site/polls.json")
    ap.add_argument("--tse")
    ap.add_argument("--tse-encoding", default="latin-1")
    ap.add_argument("--tse-delimiter", default=";")
    ap.add_argument("--extract", nargs="+")
    a = ap.parse_args()
    if a.extract:
        extract(a.extract, "data/staged.csv")
        return
    polls, bad = load_seed(a.seed)
    if not polls:  # evita apagar o banco e o JSON por causa de um CSV vazio ou quebrado
        sys.exit("Nenhuma pesquisa válida em " + a.seed)
    if a.tse:
        enrich(polls, a.tse, a.tse_encoding, a.tse_delimiter)
    con = save(polls, a.db)
    export(con, a.out)
    con.close()
    sys.exit(2 if bad else 0)


if __name__ == "__main__":
    main()
