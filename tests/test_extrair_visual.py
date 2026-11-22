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
            _salvar(os.path.join(raiz, "e.png"), 1280, 467, (90, 90, 0))       # mais baixa que a dobra
            _salvar(os.path.join(raiz, "f.png"), 1853, 900, (0, 90, 90))       # transbordo numa tela 1366
            itens = [{"id": "a", "caminho": os.path.join(raiz, "a.png"), "rotulo": "benigno"},
                     {"id": "b", "caminho": os.path.join(raiz, "sumiu.png"), "rotulo": "phishing"},
                     {"id": "c", "caminho": os.path.join(raiz, "c.png"), "rotulo": "phishing"},
                     {"id": "d", "caminho": os.path.join(raiz, "d.png"), "rotulo": "phishing"},
                     {"id": "e", "caminho": os.path.join(raiz, "e.png"), "rotulo": "phishing"},
                     {"id": "f", "caminho": os.path.join(raiz, "f.png"), "rotulo": "benigno", "classe": "1366x768"}]
            saida = io.StringIO()
            r = script.extrair_itens(itens, embedders, saida, progresso=0)

            linhas = [json.loads(l) for l in saida.getvalue().splitlines()]
            self.assertEqual([l["id"] for l in linhas], ["a", "c", "d", "e", "f"])
            self.assertEqual(r["ids"], ["a", "c", "d", "e", "f"])
            self.assertEqual([l["classe"] for l in linhas], ["1366x768", "1920x1080", "1280x960", "1280x960",
                                                              "1366x768"])  # f: classe dada pelo item
            self.assertEqual((linhas[0]["largura"], linhas[0]["altura"]), (1366, 3000))  # tamanho original
            self.assertEqual(linhas[0]["rotulo"], "benigno")                             # metadados passam
            self.assertEqual((len(linhas[0]["phash64"]), len(linhas[0]["phash256"])), (16, 64))
            # a leitura do disco é medida à parte; h de 64 e de 256 bits, cada um com o seu tempo
            self.assertEqual(set(linhas[0]["tempos_ms"]), {"ler", "abrir", "phash64", "phash256", "small"})
            self.assertEqual(set(r["tempos"]), {"ler", "abrir", "phash64", "phash256", "small"})
            # contagens do desenho (§5.1 e §5.2): usadas como estão (mais baixas que a dobra), mais
            # estreitas que a classe (ex.: 800x600 na 1280x960) e mais largas (recortadas na janela)
            self.assertEqual(r["contagens"], {"abaixo_da_dobra": 1, "mais_estreita_que_a_classe": 1,
                                              "mais_larga_que_a_classe": 1})
            self.assertEqual([e[0] for e in r["erros"]], ["b"])

            matriz = np.stack(r["emb"]["small"])
            self.assertEqual(matriz.shape, (5, 576))
            # a linha i do .npy é o embedding da amostra i do JSONL
            img_c = visual.primeira_dobra(visual.abrir_imagem(itens[2]["caminho"]), "1920x1080")
            self.assertAlmostEqual(visual.cosseno(matriz[1], embedders["small"].embed(img_c)), 1.0, places=5)

    def test_itens_de_indice_filtra_e_aceita_classe_forcada(self):
        with tempfile.TemporaryDirectory() as pasta:
            indice = os.path.join(pasta, "indice.csv")
            with open(indice, "w", encoding="utf-8", newline="") as f:
                f.write("id,particao,rotulo,marca,url,caminho_shot,shot_ok\n"
                        "x.com,benign,benigno,,http://x.com/,x.com/shot.png,1\n"
                        "y.com,benign,benigno,,http://y.com/,y.com/shot.png,0\n")
            itens = script.itens_de_indice(indice, "raiz")
            self.assertEqual([i["id"] for i in itens], ["x.com"])     # shot_ok=0 fica de fora
            self.assertIsNone(itens[0].get("classe"))                 # classe pela largura da imagem
            self.assertEqual(itens[0]["caminho"], os.path.join("raiz", "x.com/shot.png"))
            # dataset com tamanho de tela conhecido (Phishpedia benign: 1366x768, página inteira)
            forcados = script.itens_de_indice(indice, "raiz", classe="1366x768")
            self.assertEqual(forcados[0]["classe"], "1366x768")
            with self.assertRaises(ValueError):
                script.itens_de_indice(indice, "raiz", classe="1024x768")

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
