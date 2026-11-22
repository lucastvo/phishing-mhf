import importlib.util
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import estrutural  # noqa: E402
from test_base import TABELA, base_sintetica  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "similaridades.py")
_spec = importlib.util.spec_from_file_location("similaridades", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _cenario():
    """4 amostras: x1 = cópia do template 0 (1366x768, PayPal), x2 = cópia do template 2 sem s,
    x3 = cópia do template 3 (1920x1080), x4 numa classe sem templates (1280x960)."""
    b = base_sintetica()
    copias = {"x1": 0, "x2": 2, "x3": 3}
    linhas, small, large = [], [], []
    for id_, classe, rotulo, marca, origem in (("x1", "1366x768", "phishing", "paypal", 0),
                                               ("x2", "1366x768", "benigno", "", 2),
                                               ("x3", "1920x1080", "phishing", "netflix", 3),
                                               ("x4", "1280x960", "phishing", "outra", None)):
        it = b.itens[origem] if origem is not None else b.itens[0]
        linhas.append({"id": id_, "classe": classe, "phash64": it["phash64"], "phash256": it["phash256"],
                       "rotulo": rotulo, "marca": marca, "particao": "trainval", "url": f"http://{id_}.test/"})
        small.append(b.emb["small"][origem if origem is not None else 1])
        large.append(b.emb["large"][origem if origem is not None else 1])
    s_por_id = {id_: estrutural.ImpressaoEstrutural.de_dict(b.itens[i]["s"])
                for id_, i in copias.items() if b.itens[i]["s"]}
    s_por_id["fantasma"] = s_por_id["x1"]  # s sem linha visual: ignorado
    emb = {"small": np.stack(small), "large": np.stack(large)}
    return b, linhas, emb, s_por_id


class TestTabela(unittest.TestCase):
    def setUp(self):
        self.b, self.linhas, self.emb, self.s = _cenario()
        self.meta, self.m = script.calcular_tabela(self.linhas, self.emb, self.s, self.b, TABELA, "phish360")

    def test_agrupa_por_classe_e_mapeia_linhas(self):
        self.assertEqual([l["id"] for l in self.meta], ["x1", "x2", "x3", "x4"])  # ordem do JSONL visual
        self.assertEqual([(l["classe"], l["linha_na_classe"]) for l in self.meta],
                         [("1366x768", 0), ("1366x768", 1), ("1920x1080", 0), ("1280x960", 0)])
        self.assertEqual(self.m["1366x768__cos_small"].shape, (2, 3))
        self.assertEqual(list(self.m["1366x768__templates"]), [0, 1, 2])
        # x1 é cópia do template 0 → cosseno ≈ 1 na coluna dele
        coluna = list(self.m["1366x768__templates"]).index(0)
        self.assertAlmostEqual(float(self.m["1366x768__cos_small"][0, coluna]), 1.0, places=2)
        self.assertEqual(int(self.m["1366x768__dist_h64"][0, coluna]), 0)
        self.assertEqual(float(self.m["1366x768__jaccard_caminhos"][0, coluna]), 1.0)

    def test_classe_sem_templates_grava_matriz_vazia(self):
        self.assertEqual(self.m["1280x960__cos_small"].shape, (1, 0))
        self.assertEqual(self.m["1280x960__templates"].shape, (0,))

    def test_amostra_sem_s_fica_nan(self):
        self.assertTrue(np.isnan(self.m["1366x768__jaccard_caminhos"][1]).all())
        self.assertIsNone(self.meta[1]["elementos"])
        self.assertEqual(self.meta[0]["elementos"], self.s["x1"].contagens["elementos"])

    def test_s_sem_visual_e_ignorado(self):
        self.assertNotIn("fantasma", [l["id"] for l in self.meta])

    def test_tipos(self):
        self.assertEqual(self.m["1366x768__dist_h64"].dtype, np.uint8)
        self.assertEqual(self.m["1366x768__dist_h256"].dtype, np.uint16)
        self.assertEqual(self.m["1366x768__cos_small"].dtype, np.float16)
        self.assertEqual(self.m["1366x768__hash_igual"].dtype, np.float16)
        self.assertNotIn("1366x768__sim_h64", self.m)  # derivável da distância

    def test_entidade_da_amostra(self):
        self.assertEqual([l["entidade"] for l in self.meta], ["PayPal", None, "Netflix", None])

    def test_conferir_alinhamento(self):
        script.conferir_alinhamento(self.linhas, self.emb)
        with self.assertRaises(ValueError):
            script.conferir_alinhamento(self.linhas, {"small": self.emb["small"][:3], "large": self.emb["large"]})


if __name__ == "__main__":
    unittest.main()
