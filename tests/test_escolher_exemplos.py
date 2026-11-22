"""Teste do escolher_exemplos.py (etapa 7) num cenário sintético: tabelas e divisão do treino, mais índice CSV
e capturas para os mesmos ids."""

import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import cascata, divisao, exemplos  # noqa: E402
from test_treinar import montar_cenario  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "escolher_exemplos.py")
_spec = importlib.util.spec_from_file_location("escolher_exemplos", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _paginas_brutas(d, prefixo):
    """Índice CSV e capturas PNG para as amostras da tabela sintética."""
    raiz = os.path.join(d, "phish")
    os.makedirs(raiz)
    with open(prefixo + ".jsonl", encoding="utf-8") as f:
        linhas = [json.loads(l) for l in f]
    indice = os.path.join(d, "phishpedia_phish.csv")
    with open(indice, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "rotulo", "marca", "url", "caminho_shot", "caminho_html",
                                          "html_util", "shot_ok"])
        w.writeheader()
        for i, l in enumerate(linhas):
            img = Image.new("RGB", (1366, 768), "white")
            ImageDraw.Draw(img).rectangle([300, 200, 900, 500], fill=(0, (i * 7) % 255, 200))
            img.save(os.path.join(raiz, f"{l['id']}.png"))
            with open(os.path.join(raiz, f"{l['id']}.html"), "w", encoding="utf-8") as h:
                h.write("<html><body><div><form><input type=password></form></div></body></html>")
            w.writerow({"id": l["id"], "rotulo": l["rotulo"], "marca": l["marca"], "url": l["url"],
                        "caminho_shot": f"{l['id']}.png", "caminho_html": f"{l['id']}.html", "html_util": "1",
                        "shot_ok": "1"})
    return indice, raiz


class TestEscolherExemplos(unittest.TestCase):
    def test_escolher_exemplos_main(self):
        with tempfile.TemporaryDirectory() as d:
            c = montar_cenario(d)
            indice, raiz = _paginas_brutas(d, c["prefixo"])
            nomes = cascata.nomes_caracteristicas()
            X = np.random.default_rng(0).uniform(size=(100, len(nomes)))
            modelo = cascata.Boosting.treinar(X, X[:, 1] > 0.5, np.ones(100), nomes, iteracoes=5)
            pasta_modelo = os.path.join(d, "modelo")
            cascata.salvar_modelo(pasta_modelo, modelo, {
                "cascata": {"theta_h": None, "tau": 0.5}, "entidades": ["Netflix", "PayPal"],
                "caracteristicas": {"nomes": nomes, "embedding": "small", "hash_bits": 64, "sinais": ["h", "e", "s"]}})
            saida = os.path.join(d, "interface")
            argv = ["escolher_exemplos.py", "--dataset", "phishpedia_phish", indice, raiz,
                    "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--modelo", pasta_modelo,
                    "--base", c["base"], "--marcas", c["marcas"], "--por-grupo", "2", "--saida", saida, "--sem-pesos"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()

            with open(os.path.join(saida, "candidatos.json"), encoding="utf-8") as f:
                candidatos = json.load(f)
            self.assertTrue(candidatos)
            div = divisao.ler_divisao(c["divisao"])
            for cand in candidatos:
                self.assertEqual(div[(cand["dataset"], cand["id"])]["conjunto"], divisao.TESTE, cand["id"])
                for campo in ("numero", "tipo", "estrato", "marca_dataset", "url", "tabela", "pagina", "concorda"):
                    self.assertIn(campo, cand)
                self.assertEqual(set(cand["pagina"]), {"rotulo", "entidade", "motivo", "escore"})
            self.assertEqual([c_["numero"] for c_ in candidatos], list(range(1, len(candidatos) + 1)))
            for tipo in {c_["tipo"] for c_ in candidatos}:
                self.assertTrue(os.path.exists(os.path.join(saida, f"folha_{tipo}.jpg")), tipo)
            por_grupo = {}
            for c_ in candidatos:
                chave = (c_["tipo"], c_["estrato"], c_["dataset"])
                por_grupo[chave] = por_grupo.get(chave, 0) + 1
            self.assertLessEqual(max(por_grupo.values()), 2)
            ds = exemplos.ler_datasets(os.path.join(saida, "datasets.json"))
            self.assertEqual(ds, {"phishpedia_phish": {"indice": os.path.abspath(indice),
                                                       "raiz": os.path.abspath(raiz), "classe": None}})


if __name__ == "__main__":
    unittest.main()
