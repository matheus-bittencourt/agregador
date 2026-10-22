"""Rodar com: python3 -m unittest discover -s tests"""
import csv
import io
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ingest  # noqa: E402
import tse  # noqa: E402

HEADER = ["NR_PROTOCOLO_REGISTRO", "NM_EMPRESA", "NM_EMPRESA_FANTASIA", "QT_ENTREVISTADO", "NM_CONTRATANTE"]


def poll(inst, reg):
    p, errs = ingest.parse_row(dict(date="2026-10-14", inst=inst, registro=reg, lula="44", flavio="46",
                                    scenario="real"))
    assert not errs
    return {ingest.key(p): p}


class Registro(unittest.TestCase):
    def test_accepts_tse_and_press_formats(self):
        for raw in ("BR-08729/2026", "BR087292026", "br08729/2026", "Registro TSE n.º BR-08729/2026"):
            self.assertEqual(ingest.norm_reg(raw), "BR-08729/2026", raw)
        for raw in ("BR0872920261", "SP-08729/2026", "123"):
            self.assertIsNone(ingest.norm_reg(raw), raw)

    def test_pick_ignores_tse_null_marker(self):
        self.assertEqual(ingest.pick({"NM_EMPRESA_FANTASIA": "#NULO#", "NM_EMPRESA": "QUAEST"},
                                     ["NM_EMPRESA_FANTASIA", "NM_EMPRESA"]), "QUAEST")


class Enrich(unittest.TestCase):
    def enrich(self, polls, rows):
        with tempfile.TemporaryDirectory() as d:
            path = f"{d}/tse.csv"
            with open(path, "w", newline="", encoding="latin-1") as fh:
                w = csv.writer(fh, delimiter=";")
                w.writerow(HEADER)
                w.writerows(rows)
            ingest.enrich(polls, path, "latin-1", ";")
        return next(iter(polls.values()))

    def test_confirms_and_fills_from_tse_row(self):
        p = self.enrich(poll("Genial/Quaest", "BR-08729/2026"),
                        [["BR087292026", "QUAEST PESQUISAS, CONSULTORIA E PROJETOS", "#NULO#", "2154", "BANCO GENIAL S.A."]])
        self.assertEqual((p["v"], p["n"], p["c"]), (True, 2154, "BANCO GENIAL S.A."))

    def test_registration_of_another_institute_is_not_confirmed(self):
        p = self.enrich(poll("Datafolha", "BR-08729/2026"),
                        [["BR087292026", "QUAEST PESQUISAS, CONSULTORIA E PROJETOS", "#NULO#", "2154", ""]])
        self.assertFalse(p["v"])
        self.assertIsNone(p["n"])

    def test_accents_do_not_block_match(self):
        p = self.enrich(poll("Paraná Pesquisas", "BR-09051/2026"),
                        [["BR090512026", "INSTITUTO PARANA PESQUISAS LTDA", "#NULO#", "1500", ""]])
        self.assertTrue(p["v"])


class Download(unittest.TestCase):
    def zip_with(self, name, rows):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerows(rows)
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr(name.replace("BRASIL", "SP"), "ignorar")
            z.writestr(name, buf.getvalue().encode("latin-1"))
        return out.getvalue()

    def test_reads_national_file_and_merges_contratantes(self):
        fields, polls = tse.brasil_csv(self.zip_with("pesquisa_eleitoral_2026_BRASIL.csv",
                                                     [["NR_PROTOCOLO_REGISTRO", "NM_EMPRESA"], ["BR087292026", "QUAEST"]]),
                                       "pesquisa_eleitoral")
        _, contr = tse.brasil_csv(self.zip_with("pesquisa_contratante_2026_BRASIL.csv",
                                                [["NR_PROTOCOLO_REGISTRO", "NM_CONTRATANTE"],
                                                 ["BR087292026", "GLOBO"], ["BR087292026", "EDITORA GLOBO"],
                                                 ["BR087292026", "GLOBO"]]),
                                  "pesquisa_contratante")
        self.assertEqual(fields, ["NR_PROTOCOLO_REGISTRO", "NM_EMPRESA"])
        self.assertEqual(tse.merge(polls, contr)[0]["NM_CONTRATANTE"], "GLOBO / EDITORA GLOBO")


if __name__ == "__main__":
    unittest.main()
