import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import visual  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "extrair_visual.py")
_spec = importlib.util.spec_from_file_location("extrair_visual", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _salvar(caminho, largura, altura, cor):
    img = Image.new("RGB", (largura, altura), "white")
    ImageDraw.Draw(img).rectangle([largura // 4, 50, 3 * largura // 4, 300], fill=cor)
    img.save(caminho)


class TestExtracaoVisual(unittest.TestCase):
    def test_alinhamento_jsonl_npy_e_erros(self):
        embedders = {"small": visual.Embedder("small", pesos=False)}
        with tempfile.TemporaryDirectory() as raiz:
            _salvar(os.path.join(raiz, "a.png"), 1366, 3000, (200, 0, 0))   # página inteira: recorta a dobra
            _salvar(os.path.join(raiz, "c.png"), 1920, 1080, (0, 0, 200))
            _salvar(os.path.join(raiz, "d.png"), 800, 600, (0, 150, 0))
            itens = [{"id": "a", "caminho": os.path.join(raiz, "a.png"), "rotulo": "benigno"},
                     {"id": "b", "caminho": os.path.join(raiz, "sumiu.png"), "rotulo": "phishing"},
                     {"id": "c", "caminho": os.path.join(raiz, "c.png"), "rotulo": "phishing"},
                     {"id": "d", "caminho": os.path.join(raiz, "d.png"), "rotulo": "phishing"}]
            saida = io.StringIO()
            r = script.extrair_itens(itens, embedders, saida, progresso=0)

            linhas = [json.loads(l) for l in saida.getvalue().splitlines()]
            self.assertEqual([l["id"] for l in linhas], ["a", "c", "d"])
            self.assertEqual(r["ids"], ["a", "c", "d"])
            self.assertEqual([l["classe"] for l in linhas], ["1366x768", "1920x1080", "1280x960"])
            self.assertEqual((linhas[0]["largura"], linhas[0]["altura"]), (1366, 3000))  # tamanho original
            self.assertEqual(linhas[0]["rotulo"], "benigno")                             # metadados passam
            self.assertEqual((len(linhas[0]["phash64"]), len(linhas[0]["phash256"])), (16, 64))
            self.assertEqual(set(linhas[0]["tempos_ms"]), {"abrir", "phash", "small"})
            self.assertEqual([e[0] for e in r["erros"]], ["b"])

            matriz = np.stack(r["emb"]["small"])
            self.assertEqual(matriz.shape, (3, 576))
            # a linha i do .npy é o embedding da amostra i do JSONL
            img_c = visual.primeira_dobra(visual.abrir_imagem(itens[2]["caminho"]), "1920x1080")
            self.assertAlmostEqual(visual.cosseno(matriz[1], embedders["small"].embed(img_c)), 1.0, places=5)

    def test_itens_de_templates(self):
        # cada par (entrada aprovada, resolução) vira um item, com a classe = resolução
        entrada = {"id": "paypal/login/2021-01-01", "entidade": "PayPal", "variante": "login",
                   "origem": "wayback", "timestamp": "20210101000000"}
        itens = script.itens_de_pares([(entrada, "1366x768"), (entrada, "1920x1080")], "data/templates")
        self.assertEqual([i["id"] for i in itens], ["paypal/login/2021-01-01@1366x768",
                                                    "paypal/login/2021-01-01@1920x1080"])
        self.assertEqual(itens[1]["classe"], "1920x1080")
        self.assertTrue(itens[1]["caminho"].replace("\\", "/").endswith("paypal/login/2021-01-01/shot_1920x1080.png"))
        self.assertEqual((itens[0]["entidade"], itens[0]["timestamp"]), ("PayPal", "20210101000000"))


if __name__ == "__main__":
    unittest.main()
