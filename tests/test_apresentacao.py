"""Testes da apresentação do veredito na interface (etapa 7). Os vereditos são montados à mão."""

import json
import math
import os
import sys
import unittest

from PIL import Image

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import apresentacao, cascata  # noqa: E402
from mhf.captura import PaginaCapturada  # noqa: E402
from mhf.exemplos import Exemplo  # noqa: E402
from test_base import TABELA, base_sintetica  # noqa: E402

TAU = 0.9413769794242893
NAN = float("nan")


def _caracteristicas(**kw):
    c = {"sim_h64": 0.859375, "cos_small": 0.97, "jaccard_caminhos": 0.91, "jaccard_criticos": 1.0,
         "sim_contagens": 0.8, "hash_igual": 0.0, "s_ausente": 0.0}
    c.update(kw)
    return c


def _veredito(rotulo="phishing", entidade="PayPal", motivo="phishing", escore=0.991, dominio="golpe.test",
              caracteristicas=None, escores=None):
    return cascata.Veredito(
        rotulo=rotulo, entidade=entidade, estagio=2, motivo=motivo, escore=escore, d1=9,
        entidade_proxima_h="PayPal", template_proximo_h="a@1366x768", dominio=dominio,
        tempos_ms={"abrir": 16.7, "phash": 7.4, "embedding": 28.9, "total": 81.6},
        escores=escores if escores is not None else {"PayPal": escore, "Netflix": 0.02},
        detalhes={"caracteristicas": {"PayPal": caracteristicas or _caracteristicas(),
                                      "Netflix": _caracteristicas(cos_small=0.3)},
                  "melhor_template": {"PayPal": {"indice": 1, "id": "b@1366x768", "cosseno": 0.97}},
                  "s_ausente": False, "elementos": 40,
                  "dobra": Image.new("RGB", (1366, 768), "white"), "classe": "1366x768"})


def _exemplo(estrato="PayPal", marca="PayPal Inc."):
    return Exemplo(numero=1, dataset="phishpedia_phish", id="x", grupo="acerto", titulo="Clone do PayPal",
                   nota="Cópia do login.", estrato=estrato, marca_dataset=marca, linha={}, raiz="r",
                   classe=None, disponivel=True, motivo="")


class TestTextos(unittest.TestCase):
    def test_numero(self):
        self.assertEqual(apresentacao.numero(0.8491), "0,849")
        self.assertEqual(apresentacao.numero(0.5, casas=1), "0,5")
        self.assertEqual(apresentacao.numero(NAN), "—")
        self.assertEqual(apresentacao.numero(None), "—")

    def test_frase_de_cada_motivo(self):
        f = apresentacao.frase_do_motivo
        self.assertEqual(f(_veredito(), TAU),
                         "Parece PayPal (escore 0,991, limiar 0,941) e o domínio golpe.test não é de PayPal.")
        self.assertEqual(f(_veredito(rotulo="legitima", motivo="dominio_legitimo_estagio2", dominio="paypal.com"), TAU),
                         "Parece PayPal, mas está num domínio oficial de PayPal (paypal.com).")
        self.assertEqual(f(_veredito(rotulo="legitima", motivo="abaixo_do_limiar", escore=0.412), TAU),
                         "Não se parece o bastante com nenhuma marca protegida (mais próxima: PayPal, "
                         "escore 0,412 < 0,941).")
        self.assertEqual(f(_veredito(rotulo="legitima", motivo="sem_template_proximo", escore=None), TAU),
                         "Nenhum template visualmente parecido (pHash).")
        self.assertEqual(f(_veredito(rotulo="legitima", motivo="dominio_legitimo_estagio1", escore=None,
                                     dominio="paypal.com"), TAU),
                         "O template mais parecido pelo pHash é de PayPal, e o domínio paypal.com é oficial de PayPal.")


class TestSinais(unittest.TestCase):
    def test_sinais_legiveis(self):
        s = apresentacao.sinais_legiveis(_caracteristicas(hash_igual=1.0, sim_contagens=NAN))
        self.assertEqual([x["nome"] for x in s], ["sim_h64", "cos_small", "jaccard_caminhos", "jaccard_criticos",
                                                  "sim_contagens", "hash_igual", "s_ausente"])
        self.assertEqual([x["rotulo"] for x in s], [
            "Semelhança do pHash", "Cosseno do embedding (MobileNetV3)", "Caminhos do DOM em comum (Jaccard)",
            "Elementos críticos em comum (formulário, senha, envio)", "Semelhança das contagens do DOM",
            "DOM idêntico a um template", "DOM ausente ou com até 5 elementos"])
        textos = {x["nome"]: x["texto"] for x in s}
        self.assertEqual(textos["sim_h64"], "0,859 (9 de 64 bits diferentes)")
        self.assertEqual(textos["cos_small"], "0,970")
        self.assertEqual(textos["sim_contagens"], "—")
        self.assertEqual(textos["hash_igual"], "sim")
        self.assertEqual(textos["s_ausente"], "não")
        self.assertIsNone({x["nome"]: x["valor"] for x in s}["sim_contagens"])

    def test_sinais_dom_vazio(self):
        s = apresentacao.sinais_legiveis(_caracteristicas(jaccard_caminhos=NAN, jaccard_criticos=NAN,
                                                          sim_contagens=NAN, hash_igual=NAN, s_ausente=1.0))
        textos = {x["nome"]: x["texto"] for x in s}
        self.assertEqual([textos[k] for k in ("jaccard_caminhos", "jaccard_criticos", "sim_contagens")],
                         ["—", "—", "—"])
        self.assertEqual(textos["s_ausente"], "sim")


class TestSinaisSemDom(unittest.TestCase):
    """Revisão: com o s ausente, o Detector entrega 0,0 (não NaN) nos sinais do DOM; a tela mostra "—"."""

    DOM = ("jaccard_caminhos", "jaccard_criticos", "sim_contagens", "hash_igual")

    def test_sinais_dom_ausente_com_zeros(self):
        s = apresentacao.sinais_legiveis(_caracteristicas(jaccard_caminhos=0.0, jaccard_criticos=0.0,
                                                          sim_contagens=0.0, hash_igual=0.0, s_ausente=1.0))
        textos = {x["nome"]: x["texto"] for x in s}
        self.assertEqual([textos[k] for k in self.DOM], ["—"] * 4)
        self.assertEqual(textos["s_ausente"], "sim")
        self.assertEqual(textos["cos_small"], "0,970")

    def test_caminho_real_pagina_sem_dom(self):
        from test_verificar import _detector
        from mhf import visual
        b = base_sintetica()
        det = _detector(b, theta_h=None, tau=0.0)
        img = Image.new("RGB", (1366, 768), "white")
        import io as _io
        buf = _io.BytesIO()
        img.save(buf, format="PNG")
        v = det.analisar_pagina(_io.BytesIO(buf.getvalue()), "<html><body></body></html>", "http://x.test/",
                                embedder=visual.Embedder("small", pesos=False), detalhes=True)
        r = apresentacao.montar_resultado(v, 0.0, b, TABELA, "http://x.test/", False)
        textos = {x["nome"]: x["texto"] for x in r["sinais"]}
        self.assertEqual([textos[k] for k in self.DOM], ["—"] * 4)
        self.assertEqual(textos["s_ausente"], "sim")


class TestResultado(unittest.TestCase):
    def setUp(self):
        self.b = base_sintetica()

    def test_template_exibido(self):
        t = apresentacao.template_exibido(_veredito(), self.b)
        self.assertEqual(t, {"id": "b@1366x768", "marca": "PayPal", "variante": "login", "ano": "2021",
                             "origem": "Wayback", "cosseno": 0.97, "url": "/api/template?id=b%401366x768"})
        self.assertIsNone(apresentacao.template_exibido(_veredito(entidade="Netflix"), self.b))

    def test_resultado_exemplo(self):
        r = apresentacao.montar_resultado(_veredito(), TAU, self.b, TABELA, "http://golpe.test/", False,
                                          exemplo=_exemplo())
        self.assertEqual(r["veredito"]["titulo"], "PHISHING — imita PayPal")
        self.assertEqual(r["veredito"]["rotulo"], "phishing")
        self.assertEqual(r["marca"], "PayPal")
        self.assertEqual(r["escores"], [{"marca": "PayPal", "escore": 0.991}, {"marca": "Netflix", "escore": 0.02}])
        self.assertEqual(r["dominios_oficiais"], ["paypal.com"])
        self.assertEqual(r["tempos_ms"], {"abrir": 17, "phash": 7, "embedding": 29, "total": 82})
        self.assertTrue(r["captura"].startswith("data:image/"))
        self.assertEqual(r["classe"], "1366x768")
        self.assertEqual(r["real"]["situacao"], "acertou")
        self.assertEqual(r["real"]["frase"], "✓ acertou")
        self.assertEqual(r["real"]["texto"], "phishing de PayPal (rótulo do dataset: PayPal Inc.)")
        self.assertEqual(r["real"]["nota"], "Cópia do login.")
        self.assertIsNone(r["pagina"])
        self.assertFalse(r["dominio_simulado"])
        self.assertEqual(r["legenda_template"], "O classificador usa o melhor valor de cada sinal entre todos os "
                                                "templates da marca; esta é a imagem mais parecida.")

    def test_resultado_legitima(self):
        r = apresentacao.montar_resultado(_veredito(rotulo="legitima", motivo="abaixo_do_limiar", escore=0.4),
                                          TAU, self.b, TABELA, "http://site.test/", False,
                                          exemplo=_exemplo(estrato="benigno", marca=""))
        self.assertEqual(r["veredito"]["titulo"], "Legítima")
        self.assertEqual(r["real"]["situacao"], "acertou")

    def test_resultado_simulado(self):
        r = apresentacao.montar_resultado(_veredito(), TAU, self.b, TABELA, "https://paypal-verificacao.test/",
                                          True, exemplo=_exemplo())
        self.assertTrue(r["dominio_simulado"])
        self.assertEqual(r["real"]["situacao"], "sem_comparacao")

    def test_resultado_url(self):
        p = PaginaCapturada(imagem=b"", html="", url_digitada="https://paypal.com/", url_final="https://www.paypal.com/signin",
                            titulo="Entrar", status=200, credencial=True, tempo_s=4.26)
        r = apresentacao.montar_resultado(_veredito(), TAU, self.b, TABELA, "https://www.paypal.com/signin",
                                          False, pagina=p)
        self.assertIsNone(r["real"])
        self.assertEqual(r["pagina"], {"url_digitada": "https://paypal.com/", "url_final": "https://www.paypal.com/signin",
                                       "url_analisada": "https://www.paypal.com/signin", "titulo": "Entrar",
                                       "status": 200, "credencial": True, "tempo_abrir_s": 4.3})

    def test_resultado_e_json(self):
        v = _veredito(caracteristicas=_caracteristicas(sim_contagens=NAN), escore=None, rotulo="legitima",
                      motivo="sem_template_proximo", escores={})
        r = apresentacao.montar_resultado(v, TAU, self.b, TABELA, "http://x.test/", False)
        texto = json.dumps(r, allow_nan=False)
        self.assertFalse(math.isnan(json.loads(texto)["tau"]))


if __name__ == "__main__":
    unittest.main()
