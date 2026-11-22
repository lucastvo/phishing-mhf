"""Testes do servidor da interface (etapa 7): rotas, erros e o comando interface.py. Usam um detector
sintético, a MobileNetV3 sem pesos e um navegador falso (nada de rede)."""

import contextlib
import http.client
import importlib.util
import io
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import base, cascata, divisao, exemplos, servidor, visual  # noqa: E402
from mhf.captura import ErroCaptura, PaginaCapturada  # noqa: E402
from test_base import DOM_LOGIN, TABELA, base_sintetica  # noqa: E402
from test_exemplos import gravar_config, montar_dataset  # noqa: E402
from test_verificar import _detector  # noqa: E402


def _png(largura, altura):
    img = Image.new("RGB", (largura, altura), "white")
    ImageDraw.Draw(img).rectangle([300, 200, 900, 500], fill=(0, 90, 200))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _NavegadorFalso:
    def __init__(self):
        self.erro, self.url_final, self.chamadas, self.fechado = None, None, [], False

    def capturar(self, url, classe, idioma):
        self.chamadas.append((url, classe, idioma))
        if self.erro:
            raise self.erro
        largura, altura = visual.CLASSES_TELA[classe]
        return PaginaCapturada(imagem=_png(largura, altura), html=DOM_LOGIN, url_digitada=url,
                               url_final=self.url_final or url, titulo="Entrar", status=200, credencial=True,
                               tempo_s=1.24)

    def fechar(self):
        self.fechado = True


class TestServidor(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        b = base_sintetica()
        raiz_templates = os.path.join(d, "templates")
        for it in b.itens:
            pasta = os.path.join(raiz_templates, it["id"].split("@")[0])
            os.makedirs(pasta, exist_ok=True)
            largura, altura = visual.CLASSES_TELA[it["classe"]]
            with open(os.path.join(pasta, f"shot_{it['classe']}.png"), "wb") as f:
                f.write(_png(largura, altura))
        linhas = [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.", "estrato": "PayPal",
                   "url": "http://golpe.test/", "html_util": "1"},
                  {"id": "p1", "rotulo": "benigno", "marca": "", "estrato": "benigno", "url": "", "html_util": "0"}]
        indice, raiz, caminho_div = montar_dataset(d, linhas=linhas)
        os.remove(os.path.join(raiz, "p1.png"))  # o antivírus "levou" a captura
        caminho_ds = os.path.join(d, "datasets.json")
        exemplos.gravar_datasets(caminho_ds, {"ds": {"indice": indice, "raiz": raiz, "classe": "1366x768"}})
        config = gravar_config(d, [{"dataset": "ds", "id": "p0", "grupo": "acerto", "titulo": "Clone", "nota": "N"},
                                   {"dataset": "ds", "id": "p1", "grupo": "erro", "titulo": "Sumiu", "nota": "N"}])
        lista, urls = exemplos.ler_exemplos(config, caminho_ds, divisao.ler_divisao(caminho_div))
        cls.nav = _NavegadorFalso()
        cls.app = servidor.Aplicacao(_detector(b, theta_h=None, tau=0.0), visual.Embedder("small", pesos=False),
                                     TABELA, raiz_templates, lista, urls, navegador=cls.nav)
        cls.srv = servidor.criar_servidor(cls.app, porta=0)
        cls.porta = cls.srv.server_address[1]
        cls.thread = threading.Thread(target=cls.srv.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.encerrar()
        cls.tmp.cleanup()
        assert cls.nav.fechado

    def setUp(self):
        self.nav.erro, self.nav.url_final = None, None

    def _pedir(self, metodo, caminho, corpo=None, cru=None):
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=60)
        dados = cru if cru is not None else (json.dumps(corpo).encode() if corpo is not None else None)
        c.request(metodo, caminho, body=dados, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        conteudo = r.read()
        c.close()
        return r.status, r.getheader("Content-Type"), conteudo

    def _json(self, metodo, caminho, corpo=None, cru=None):
        status, _, conteudo = self._pedir(metodo, caminho, corpo, cru)
        return status, json.loads(conteudo)

    def test_estado(self):
        status, e = self._json("GET", "/api/estado")
        self.assertEqual(status, 200)
        self.assertEqual(e["tau"], 0.0)
        self.assertEqual((e["templates"], e["marcas"]), (4, 2))
        self.assertEqual(e["classes"], ["1280x960", "1366x768", "1920x1080"])
        self.assertEqual(e["classe_padrao"], "1366x768")
        self.assertEqual(e["idiomas"], ["en-US", "pt-BR"])
        self.assertEqual([(x["numero"], x["grupo"], x["disponivel"]) for x in e["exemplos"]],
                         [(1, "acerto", True), (2, "erro", False)])
        self.assertIn("p1.png", e["exemplos"][1]["motivo"])
        self.assertEqual(e["urls_sugeridas"], [{"titulo": "X", "url": "https://x.test/"}])
        self.assertTrue(e["navegador"])
        self.assertEqual(e["aviso_url"], "O navegador vai abrir a página de verdade. Não cole links suspeitos "
                                         "reais; para ver phishing, use os exemplos.")

    def test_exemplo(self):
        status, r = self._json("POST", "/api/exemplo", {"numero": 1})
        self.assertEqual(status, 200)
        self.assertEqual(r["real"]["titulo"], "Clone")
        self.assertIn(r["real"]["situacao"], ("acertou", "errou", "marca_errada"))
        self.assertEqual(r["url_analisada"], "http://golpe.test/")
        self.assertFalse(r["dominio_simulado"])

    def test_exemplo_com_dominio_simulado(self):
        status, r = self._json("POST", "/api/exemplo", {"numero": 1, "url_simulada": "paypal-verificacao.test"})
        self.assertEqual(status, 200)
        self.assertEqual(r["url_analisada"], "https://paypal-verificacao.test/")
        self.assertTrue(r["dominio_simulado"])
        self.assertEqual(r["real"]["situacao"], "sem_comparacao")

    def test_exemplo_indisponivel_400(self):
        status, r = self._json("POST", "/api/exemplo", {"numero": 2})
        self.assertEqual(status, 400)
        self.assertIn("p1.png", r["erro"])

    def test_url(self):
        self.nav.url_final = "https://www.paypal.com/signin"
        status, r = self._json("POST", "/api/url", {"url": "paypal.com", "classe": "1920x1080", "idioma": "pt-BR"})
        self.assertEqual(status, 200)
        self.assertEqual(self.nav.chamadas[-1], ("https://paypal.com/", "1920x1080", "pt-BR"))
        self.assertEqual(r["pagina"]["url_final"], "https://www.paypal.com/signin")
        self.assertEqual(r["url_analisada"], "https://www.paypal.com/signin")
        self.assertEqual(r["classe"], "1920x1080")
        self.assertIsNone(r["real"])

    def test_url_com_dominio_simulado(self):
        status, r = self._json("POST", "/api/url", {"url": "https://www.paypal.com/", "classe": "1366x768",
                                                    "idioma": "en-US", "url_simulada": "paypal-verificacao.test"})
        self.assertEqual(status, 200)
        self.assertEqual(r["url_analisada"], "https://paypal-verificacao.test/")
        self.assertEqual(r["pagina"]["url_analisada"], "https://paypal-verificacao.test/")
        self.assertTrue(r["dominio_simulado"])

    def test_url_que_nao_abre_vira_502_e_servidor_segue(self):
        self.nav.erro = ErroCaptura("não foi possível abrir a página: net::ERR_NAME_NOT_RESOLVED")
        status, r = self._json("POST", "/api/url", {"url": "nao-existe.test", "classe": "1366x768", "idioma": "en-US"})
        self.assertEqual(status, 502)
        self.assertIn("não foi possível abrir a página", r["erro"])
        status, _ = self._json("GET", "/api/estado")
        self.assertEqual(status, 200)

    def test_entradas_invalidas_400(self):
        casos = [("/api/url", {"url": "a.test", "classe": "800x600", "idioma": "en-US"}),
                 ("/api/url", {"url": "a.test", "classe": "1366x768", "idioma": "fr-FR"}),
                 ("/api/url", {"url": "javascript:alert(1)", "classe": "1366x768", "idioma": "en-US"}),
                 ("/api/url", {"url": "a.test", "classe": "1366x768", "idioma": "en-US", "url_simulada": "file:///c:/"}),
                 ("/api/exemplo", {"numero": 99}),
                 ("/api/exemplo", {"numero": "um"}),
                 ("/api/exemplo", {})]
        for rota, corpo in casos:
            status, r = self._json("POST", rota, corpo)
            self.assertEqual(status, 400, (rota, corpo))
            self.assertTrue(r["erro"])
        status, r = self._json("POST", "/api/exemplo", cru=b"{quebrado")
        self.assertEqual(status, 400)

    def test_template(self):
        status, tipo, conteudo = self._pedir("GET", "/api/template?id=a%401366x768")
        self.assertEqual((status, tipo), (200, "image/png"))
        with Image.open(io.BytesIO(conteudo)) as img:
            self.assertEqual(img.size, (1366, 768))
        status, _, _ = self._pedir("GET", "/api/template?id=../../config/marcas.json")
        self.assertEqual(status, 400)

    def test_estaticos(self):
        status, tipo, conteudo = self._pedir("GET", "/")
        self.assertEqual(status, 200)
        self.assertTrue(tipo.startswith("text/html"))
        self.assertIn(b"<html", conteudo.lower())
        for caminho in ("/estatico/../README.md", "/estatico/servidor.py", "/nao-existe"):
            self.assertEqual(self._pedir("GET", caminho)[0], 404, caminho)

    def test_conexao_ociosa_nao_trava(self):
        """Revisão: navegadores abrem conexões antes de precisar; com um servidor sem threads, uma conexão
        ociosa prende todas as outras."""
        import socket
        import time
        ociosa = socket.create_connection(("127.0.0.1", self.porta))
        try:
            inicio = time.monotonic()
            c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=5)
            c.request("GET", "/api/estado")
            status = c.getresponse().status
            c.close()
            self.assertEqual(status, 200)
            self.assertLess(time.monotonic() - inicio, 3)
        finally:
            ociosa.close()

    def test_porta_ocupada(self):
        """Revisão: no Windows, SO_REUSEADDR deixaria uma segunda interface ligar na mesma porta sem erro."""
        with self.assertRaises(OSError):
            servidor.criar_servidor(self.app, porta=self.porta)

    def test_pedido_de_outro_host_403(self):
        """Revisão: DNS rebinding — um site de fora que aponte o próprio domínio para 127.0.0.1."""
        for metodo, caminho, corpo in (("GET", "/api/estado", None), ("POST", "/api/exemplo", b'{"numero": 1}')):
            c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
            c.request(metodo, caminho, body=corpo, headers={"Host": f"golpe.test:{self.porta}",
                                                            "Content-Type": "application/json"})
            r = c.getresponse()
            self.assertEqual(r.status, 403, caminho)
            self.assertIn("127.0.0.1", json.loads(r.read())["erro"])
            c.close()
        c = http.client.HTTPConnection("localhost", self.porta, timeout=10)
        c.request("GET", "/api/estado")
        self.assertEqual(c.getresponse().status, 200)
        c.close()

    def test_post_sem_json_415(self):
        """Revisão: um site de fora pode mandar POST "simples" (text/plain) sem permissão do navegador."""
        antes = len(self.nav.chamadas)
        c = http.client.HTTPConnection("127.0.0.1", self.porta, timeout=10)
        c.request("POST", "/api/url", body=b'{"url": "a.test"}', headers={"Content-Type": "text/plain"})
        r = c.getresponse()
        self.assertEqual(r.status, 415)
        self.assertIn("JSON", json.loads(r.read())["erro"])
        c.close()
        self.assertEqual(len(self.nav.chamadas), antes)  # o navegador não foi chamado

    def test_sem_navegador_400(self):
        app = servidor.Aplicacao(self.app.detector, self.app.embedder, TABELA, self.app.raiz_templates, [], [],
                                 navegador=None)
        with self.assertRaises(ValueError) as cm:
            app.analisar_url("a.test", "1366x768", "en-US")
        self.assertIn("--sem-navegador", str(cm.exception))
        self.assertFalse(app.estado()["navegador"])


class TestTela(unittest.TestCase):
    def test_tela_sem_recursos_externos(self):
        import re
        externo = re.compile(r"""(?:src|href)\s*=\s*["']?\s*(?:https?:)?//|url\(\s*["']?\s*(?:https?:)?//|@import""", re.I)
        for nome in ("index.html", "estilo.css", "app.js"):
            caminho = os.path.join(servidor.RAIZ_WEB, nome)
            self.assertTrue(os.path.exists(caminho), nome)
            with open(caminho, encoding="utf-8") as f:
                conteudo = f.read()
            self.assertIsNone(externo.search(conteudo), nome)


def _carregar_script(nome):
    caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{nome}.py")
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestInterfaceMain(unittest.TestCase):
    def test_main_sobe_e_fecha(self):
        script = _carregar_script("interface")
        with tempfile.TemporaryDirectory() as d:
            b = base_sintetica()
            pasta_base = os.path.join(d, "base")
            base.gravar(pasta_base, b.itens, b.emb, {})
            nomes = cascata.nomes_caracteristicas()
            X = np.random.default_rng(0).uniform(size=(100, len(nomes)))
            modelo = cascata.Boosting.treinar(X, X[:, 1] > 0.5, np.ones(100), nomes, iteracoes=5)
            pasta_modelo = os.path.join(d, "modelo")
            cascata.salvar_modelo(pasta_modelo, modelo, {
                "cascata": {"theta_h": None, "tau": 0.5}, "entidades": ["Netflix", "PayPal"],
                "caracteristicas": {"nomes": nomes, "embedding": "small", "hash_bits": 64, "sinais": ["h", "e", "s"]}})
            marcas = os.path.join(d, "marcas.json")
            with open(marcas, "w", encoding="utf-8") as f:
                json.dump(TABELA, f)
            argv = ["interface.py", "--modelo", pasta_modelo, "--base", pasta_base, "--marcas", marcas,
                    "--templates", d, "--exemplos", os.path.join(d, "nao_existe.json"),
                    "--datasets", os.path.join(d, "nao_existe2.json"), "--divisao", os.path.join(d, "x.csv"),
                    "--porta", "0", "--nao-abrir", "--sem-navegador", "--sem-pesos"]
            saida = io.StringIO()
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch("http.server.HTTPServer.serve_forever", side_effect=KeyboardInterrupt), \
                    contextlib.redirect_stdout(saida):
                script.main()
            self.assertIn("Pronto: http://127.0.0.1:", saida.getvalue())


if __name__ == "__main__":
    unittest.main()
