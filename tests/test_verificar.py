import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import cascata, estrutural, visual  # noqa: E402
from test_base import TABELA, base_sintetica, consulta_do_item  # noqa: E402
from test_treinar import montar_cenario  # noqa: E402


def _carregar(nome):
    caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{nome}.py")
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


similaridades = _carregar("similaridades")
treinar = _carregar("treinar")
verificar = _carregar("verificar")


def _detector(b, theta_h=40, tau=0.5, semente=0):
    """Detector com uma regressão logística treinada em dados aleatórios (só para exercitar a cascata)."""
    nomes = cascata.nomes_caracteristicas()
    rng = np.random.default_rng(semente)
    X = rng.uniform(size=(200, len(nomes)))
    y = X[:, 1] + 0.3 * X[:, 0] > 0.8  # cos_small alto → phishing
    modelo = cascata.RegressaoLogistica.treinar(X, y, np.ones(200), nomes)
    info = {"entidades": sorted({it["entidade"] for it in b.itens}),
            "caracteristicas": {"nomes": nomes, "embedding": "small", "hash_bits": 64, "sinais": ["h", "e", "s"]},
            "cascata": {"theta_h": theta_h, "tau": tau}}
    return cascata.Detector(b, modelo, info, TABELA)


class TestDetector(unittest.TestCase):
    def test_decidir_igual_a_cascata_da_tabela(self):
        b = base_sintetica()
        det = _detector(b, theta_h=64, tau=0.3)
        for i in (0, 1):  # duas amostras copiadas dos templates a e b (1366x768)
            consulta = consulta_do_item(b, i)
            url = "http://golpe.test/"
            v = det.decidir(consulta, "1366x768", url, elementos=consulta["s"].contagens["elementos"])
            linha = {"id": f"x{i}", "classe": "1366x768", "phash64": b.itens[i]["phash64"],
                     "phash256": b.itens[i]["phash256"], "rotulo": "phishing", "marca": "", "url": url}
            emb = {m: b.emb[m][i:i + 1] for m in ("small", "large")}
            meta, z = similaridades.calcular_tabela([linha], emb, {f"x{i}": consulta["s"]}, b, TABELA, "phish360")
            sinais = cascata.sinais_da_tabela(z, "1366x768")
            colunas = np.array([b.itens[k]["entidade"] for k in z["1366x768__templates"]])
            X = cascata.caracteristicas(sinais, colunas, det.entidades, np.array([False]), det.nomes)
            d1, t1 = cascata.estagio1(sinais["dist_h64"], colunas, det.entidades)
            legit = cascata.matriz_dominio_legitimo([url], det.entidades, TABELA)
            r = cascata.aplicar_cascata(d1, t1, cascata.pontuar_amostras(det.modelo, X), legit, 64, 0.3)
            self.assertEqual((v.rotulo == "phishing", v.motivo, v.estagio), (bool(r["phishing"][0]), r["motivo"][0],
                                                                              int(r["estagio"][0])))
            self.assertEqual(v.entidade, det.entidades[int(r["entidade"][0])])
            self.assertAlmostEqual(v.escore, float(r["escore"][0]), places=2)  # a tabela guarda float16

    def test_decidir_estagio1_nao_calcula_e_nem_s(self):
        b = base_sintetica()
        det = _detector(b, theta_h=1)
        chamadas = []
        original = b.similaridades
        b.similaridades = lambda c, cl, sinais=("h", "e", "s"): chamadas.append(sinais) or original(c, cl, sinais)
        completar = mock.Mock(return_value={})
        v = det.decidir({"phash64": "0" * 15 + "3"}, "1366x768", "http://x.test/", completar=completar)
        self.assertEqual((v.estagio, v.motivo, v.rotulo), (1, "sem_template_proximo", "legitima"))
        self.assertEqual(chamadas, [("h",)])
        completar.assert_not_called()
        self.assertIn("busca_h", v.tempos_ms)
        self.assertNotIn("classificador", v.tempos_ms)

    def test_decidir_dominio_legitimo_no_estagio1(self):
        b = base_sintetica()
        v = _detector(b).decidir(consulta_do_item(b, 0), "1366x768", "https://www.paypal.com/signin", elementos=40)
        self.assertEqual((v.rotulo, v.motivo, v.entidade), ("legitima", "dominio_legitimo_estagio1", "PayPal"))

    def test_analisar_pagina(self):
        b = base_sintetica()
        det = _detector(b, theta_h=64, tau=0.0)  # tudo chega ao estágio 2 e passa do limiar
        img = Image.new("RGB", (1366, 768), "white")
        ImageDraw.Draw(img).rectangle([400, 200, 900, 500], fill=(0, 90, 200))
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "shot.png")
            img.save(caminho)
            html = "<html><body><div><form><input type=email><input type=password><button>Ok</button></form>" \
                   "</div></body></html>"
            v = det.analisar_pagina(caminho, html, "http://golpe.test/", embedder=visual.Embedder("small", pesos=False))
        self.assertEqual(v.rotulo, "phishing")
        self.assertEqual(v.estagio, 2)
        self.assertEqual(set(v.tempos_ms), {"abrir", "phash", "busca_h", "embedding", "estrutural", "busca_es",
                                            "classificador", "total"})
        self.assertEqual(set(v.escores), {"Netflix", "PayPal"})


class TestVerificarMain(unittest.TestCase):
    def _treinar(self, d):
        c = montar_cenario(d)
        saida = os.path.join(d, "modelos")
        argv = ["treinar.py", "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--base", c["base"],
                "--marcas", c["marcas"], "--saida", saida, "--arvores", "10", "--n-jobs", "1", "--modelos", "regressao"]
        with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
            treinar.main()
        return c, os.path.join(saida, "regressao")

    def test_verificar_main_tabela(self):
        with tempfile.TemporaryDirectory() as d:
            c, modelo = self._treinar(d)
            with open(c["divisao"], encoding="utf-8") as f:
                linhas_div = [l for l in f.read().splitlines()[1:] if ",desenvolvimento," in l]
            ids = [l.split(",")[1] for l in linhas_div[:2]]
            argv = ["verificar.py", "--modelo", modelo, "--base", c["base"], "--marcas", c["marcas"],
                    "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--ids", *ids]
            saida = io.StringIO()
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(saida):
                verificar.main()
        texto = saida.getvalue()
        for id_ in ids:
            self.assertIn(id_, texto)
        self.assertIn("| Estágio |", texto)
        self.assertIn("phishing de PayPal", texto)

    def test_verificar_recusa_teste_sem_flag(self):
        with tempfile.TemporaryDirectory() as d:
            c, modelo = self._treinar(d)
            argv = ["verificar.py", "--modelo", modelo, "--base", c["base"], "--marcas", c["marcas"],
                    "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--conjunto", "teste", "--amostras", "3"]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit):
                verificar.main()


if __name__ == "__main__":
    unittest.main()


class TestDetectorRevisao(unittest.TestCase):
    """Correções da revisão final: hash de 256 bits, φ incompleta e elementos derivados do s."""

    def test_detector_hash_256_chega_ao_estagio2(self):
        b = base_sintetica()
        nomes = cascata.nomes_caracteristicas(hash_bits=256)
        rng = np.random.default_rng(0)
        X = rng.uniform(size=(200, len(nomes)))
        modelo = cascata.RegressaoLogistica.treinar(X, X[:, 1] > 0.5, np.ones(200), nomes)
        info = {"entidades": ["Netflix", "PayPal"], "cascata": {"theta_h": 64, "tau": 0.0},
                "caracteristicas": {"nomes": nomes, "embedding": "small", "hash_bits": 256, "sinais": ["h", "e", "s"]}}
        det = cascata.Detector(b, modelo, info, TABELA)
        img = Image.new("RGB", (1366, 768), "white")
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "shot.png")
            img.save(caminho)
            v = det.analisar_pagina(caminho, "<html><body><div><p>x</p></div></body></html>", "http://golpe.test/",
                                    embedder=visual.Embedder("small", pesos=False))
        self.assertEqual((v.estagio, v.rotulo), (2, "phishing"))
        self.assertIsNotNone(v.escores)

    def test_decidir_sem_sinal_do_modelo_levanta(self):
        b = base_sintetica()
        with self.assertRaisesRegex(ValueError, "cos_small"):
            _detector(b, theta_h=64).decidir({"phash64": "0" * 16}, "1366x768", "http://golpe.test/")

    def test_decidir_deriva_elementos_do_s(self):
        b = base_sintetica()
        det = _detector(b, theta_h=64, tau=0.3)
        consulta = consulta_do_item(b, 0)
        com = det.decidir(consulta, "1366x768", "http://golpe.test/", elementos=consulta["s"].contagens["elementos"])
        sem = det.decidir(consulta, "1366x768", "http://golpe.test/")
        self.assertEqual((sem.rotulo, sem.entidade, sem.motivo), (com.rotulo, com.entidade, com.motivo))
        self.assertAlmostEqual(sem.escore, com.escore, places=9)

    def test_decidir_sem_s_igual_a_tabela(self):
        b = base_sintetica()
        det = _detector(b, theta_h=64, tau=0.3)
        consulta = {**consulta_do_item(b, 0), "s": None}
        url = "http://golpe.test/"
        v = det.decidir(consulta, "1366x768", url)
        linha = {"id": "x", "classe": "1366x768", "phash64": b.itens[0]["phash64"], "phash256": b.itens[0]["phash256"],
                 "rotulo": "phishing", "marca": "", "url": url}
        _, z = similaridades.calcular_tabela([linha], {m: b.emb[m][:1] for m in ("small", "large")}, {}, b, TABELA,
                                             "phish360")
        sinais = cascata.sinais_da_tabela(z, "1366x768")
        colunas = np.array([b.itens[k]["entidade"] for k in z["1366x768__templates"]])
        X = cascata.caracteristicas(sinais, colunas, det.entidades, np.array([True]), det.nomes)
        self.assertAlmostEqual(v.escore, float(np.nanmax(cascata.pontuar_amostras(det.modelo, X))), places=2)
