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

from mhf import base, cascata, divisao  # noqa: E402
from test_base import TABELA, base_sintetica  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "medir_latencia.py")
_spec = importlib.util.spec_from_file_location("medir_latencia", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


class TestMedirLatencia(unittest.TestCase):
    def test_main_mede_paginas_brutas(self):
        with tempfile.TemporaryDirectory() as d:
            b = base_sintetica()
            pasta_base = os.path.join(d, "base")
            base.gravar(pasta_base, b.itens, b.emb, {})
            nomes = cascata.nomes_caracteristicas()
            rng = np.random.default_rng(0)
            X = rng.uniform(size=(100, len(nomes)))
            modelo = cascata.Boosting.treinar(X, X[:, 1] > 0.5, np.ones(100), nomes, iteracoes=5)
            pasta_modelo = os.path.join(d, "modelo")
            cascata.salvar_modelo(pasta_modelo, modelo, {
                "cascata": {"theta_h": None, "tau": 0.0}, "entidades": ["Netflix", "PayPal"],
                "caracteristicas": {"nomes": nomes, "embedding": "small", "hash_bits": 64, "sinais": ["h", "e", "s"]}})
            marcas = os.path.join(d, "marcas.json")
            with open(marcas, "w", encoding="utf-8") as f:
                json.dump(TABELA, f)
            linhas_div, args = [], []
            for ds in ("ds_a", "ds_b"):
                raiz = os.path.join(d, ds)
                os.makedirs(raiz)
                indice = os.path.join(d, f"{ds}.csv")
                with open(indice, "w", encoding="utf-8", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=["id", "shot_ok", "caminho_shot", "caminho_html", "html_util", "url"])
                    w.writeheader()
                    for i in range(2):
                        img = Image.new("RGB", (1366, 768), "white")
                        ImageDraw.Draw(img).rectangle([300, 200, 900, 500], fill=(0, 90, 200 - 50 * i))
                        img.save(os.path.join(raiz, f"p{i}.png"))
                        com_html = not (ds == "ds_b" and i == 1)  # uma página sem HTML
                        if com_html:
                            with open(os.path.join(raiz, f"p{i}.html"), "w", encoding="utf-8") as h:
                                h.write("<html><body><div><form><input type=password></form></div></body></html>")
                        w.writerow({"id": f"p{i}", "shot_ok": "1", "caminho_shot": f"p{i}.png",
                                    "caminho_html": f"p{i}.html", "html_util": "1" if com_html else "0",
                                    "url": f"http://golpe{i}.test/"})
                        linhas_div.append({"dataset": ds, "id": f"p{i}", "conjunto": "teste", "dobra": -1,
                                           "grupo": f"a:{ds}:p{i}", "estrato": "PayPal"})
                args += ["--dataset", ds, indice, raiz, "1366x768"]
            caminho_div = os.path.join(d, "divisao.csv")
            divisao.gravar_divisao(caminho_div, linhas_div)
            saida = os.path.join(d, "avaliacao")
            argv = ["medir_latencia.py", *args, "--divisao", caminho_div, "--modelo", pasta_modelo,
                    "--base", pasta_base, "--marcas", marcas, "--por-dataset", "2", "--saida", saida, "--sem-pesos"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()
            with open(os.path.join(saida, "latencia.json"), encoding="utf-8") as f:
                r = json.load(f)
            self.assertEqual(r["paginas"], 4)
            for parte in ("abrir", "phash", "busca_h", "embedding", "estrutural", "busca_es", "classificador", "total"):
                self.assertIn("mediana", r["por_parte"][parte])
                self.assertIn("p95", r["por_parte"][parte])
            self.assertEqual(set(r["por_dataset"]), {"ds_a", "ds_b"})
            self.assertTrue(os.path.exists(os.path.join(saida, "tabelas", "latencia.tex")))
            self.assertTrue(os.path.exists(os.path.join(saida, "figuras", "latencia.pdf")))


class TestRecorteDaDobra(unittest.TestCase):
    def test_pagina_inteira_vira_a_janela(self):
        # o Phishpedia benign guarda a página inteira (até 85 mil px); no navegador, a captura é só a janela
        import io
        with tempfile.TemporaryDirectory() as d:
            raiz = os.path.join(d, "ds")
            os.makedirs(raiz)
            Image.new("RGBA", (1366, 3000), (255, 255, 255, 255)).save(os.path.join(raiz, "p.png"))
            indice = os.path.join(d, "ds.csv")
            with open(indice, "w", encoding="utf-8", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["id", "shot_ok", "caminho_shot", "caminho_html", "html_util", "url"])
                w.writeheader()
                w.writerow({"id": "p", "shot_ok": "1", "caminho_shot": "p.png", "caminho_html": "x", "html_util": "0",
                            "url": ""})
            div = {("ds", "p"): {"conjunto": "teste"}}
            paginas = script.sortear_paginas("ds", indice, raiz, "1366x768", div, 5, np.random.default_rng(0))
        with Image.open(io.BytesIO(paginas[0]["imagem"])) as img:
            self.assertEqual(img.size, (1366, 768))
            self.assertEqual(img.mode, "RGBA")  # a transparência continua indo para a medição
        self.assertIsNone(paginas[0]["html"])
        self.assertEqual(paginas[0]["url"], "p")


if __name__ == "__main__":
    unittest.main()
