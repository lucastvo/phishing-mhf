"""Testes da captura ao vivo (etapa 7). Usam um navegador falso; o teste com o Chromium real só roda com
MHF_TESTE_NAVEGADOR=1."""

import io
import os
import sys
import unittest

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import captura  # noqa: E402
from playwright.sync_api import Error as ErroPlaywright  # noqa: E402


def _png(largura=1366, altura=768):
    buf = io.BytesIO()
    Image.new("RGB", (largura, altura), "white").save(buf, format="PNG")
    return buf.getvalue()


class _Elemento:
    def __init__(self, visivel):
        self.visivel = visivel

    def is_visible(self):
        return self.visivel


class _Quadro:
    def __init__(self, campos):
        self.campos = campos

    def query_selector_all(self, seletor):
        return [_Elemento(True)] * self.campos


class _Resposta:
    def __init__(self, status):
        self.status = status


class _Pagina:
    def __init__(self, registro, url_final=None, campos=1, erro_goto=None, status=200):
        self.registro, self.url_final, self.campos, self.erro_goto, self.status = \
            registro, url_final, campos, erro_goto, status
        self.url = "about:blank"

    def goto(self, url, wait_until=None, timeout=None):
        self.registro.update(goto=url, wait_until=wait_until, timeout=timeout)
        if self.erro_goto:
            raise self.erro_goto
        self.url = self.url_final or url
        return _Resposta(self.status)

    @property
    def frames(self):
        return [_Quadro(self.campos)]

    def wait_for_load_state(self, estado, timeout=None):
        self.registro["load_state"] = (estado, timeout)

    def wait_for_timeout(self, ms):
        pass

    def screenshot(self, full_page=None):
        self.registro["full_page"] = full_page
        return _png()

    def content(self):
        return "<html><body><form><input type=password></form></body></html>"

    def title(self):
        return "Entrar"


class _Contexto:
    def __init__(self, registro, pagina):
        self.registro, self.pagina = registro, pagina

    def new_page(self):
        return self.pagina

    def close(self):
        self.registro["fechado"] = True


class _Navegador:
    def __init__(self, **kw_pagina):
        self.registro = {}
        self.kw_pagina = kw_pagina

    def new_context(self, **kw):
        self.registro["contexto"] = kw
        return _Contexto(self.registro, _Pagina(self.registro, **self.kw_pagina))


class TestNormalizarUrl(unittest.TestCase):
    def test_normalizar_url(self):
        self.assertEqual(captura.normalizar_url("microsoft-verificacao.test"), "https://microsoft-verificacao.test/")
        self.assertEqual(captura.normalizar_url(" https://a.com/x "), "https://a.com/x")
        self.assertEqual(captura.normalizar_url("http://a.com"), "http://a.com/")
        self.assertEqual(captura.normalizar_url("exemplo.com:8443/login"), "https://exemplo.com:8443/login")
        for ruim in ("javascript:alert(1)", "file:///c:/", "https://", "", "   ", "mailto:a@b.com"):
            with self.assertRaises(ValueError, msg=ruim):
                captura.normalizar_url(ruim)


class TestCaptura(unittest.TestCase):
    def test_captura_usa_url_final(self):
        nav = _Navegador(url_final="https://login.microsoftonline.com/x")
        p = captura.capturar_pagina(nav, "https://microsoft.com/", espera_credencial_ms=50)
        self.assertEqual(p.url_digitada, "https://microsoft.com/")
        self.assertEqual(p.url_final, "https://login.microsoftonline.com/x")
        self.assertEqual(p.titulo, "Entrar")
        self.assertEqual(p.status, 200)
        self.assertTrue(p.credencial)
        self.assertIn("<form>", p.html)
        with Image.open(io.BytesIO(p.imagem)) as img:
            self.assertEqual(img.size, (1366, 768))
        self.assertGreaterEqual(p.tempo_s, 0)

    def test_captura_parametros_do_contexto(self):
        nav = _Navegador()
        captura.capturar_pagina(nav, "https://a.test/", classe="1920x1080", idioma="pt-BR", espera_credencial_ms=50)
        r = nav.registro
        self.assertEqual(r["contexto"], {"viewport": {"width": 1920, "height": 1080}, "locale": "pt-BR",
                                         "accept_downloads": False})
        self.assertEqual((r["wait_until"], r["timeout"]), ("load", 30000))
        self.assertEqual(r["load_state"], ("networkidle", 10000))
        self.assertIs(r["full_page"], False)
        self.assertTrue(r["fechado"])

    def test_captura_sem_credencial_segue(self):
        nav = _Navegador(campos=0)
        p = captura.capturar_pagina(nav, "https://a.test/", espera_credencial_ms=50)
        self.assertFalse(p.credencial)
        self.assertTrue(p.imagem)

    def test_erro_de_navegacao_vira_erro_captura(self):
        nav = _Navegador(erro_goto=ErroPlaywright("net::ERR_NAME_NOT_RESOLVED at https://nao-existe.test/"))
        with self.assertRaises(captura.ErroCaptura) as cm:
            captura.capturar_pagina(nav, "https://nao-existe.test/", espera_credencial_ms=50)
        self.assertIn("não foi possível abrir a página", str(cm.exception))
        self.assertTrue(nav.registro["fechado"])

    def test_classe_e_idioma_invalidos(self):
        with self.assertRaises(ValueError):
            captura.capturar_pagina(_Navegador(), "https://a.test/", classe="800x600")
        with self.assertRaises(ValueError):
            captura.capturar_pagina(_Navegador(), "https://a.test/", idioma="fr-FR")


@unittest.skipUnless(os.environ.get("MHF_TESTE_NAVEGADOR") == "1", "só com MHF_TESTE_NAVEGADOR=1 (abre o Chromium)")
class TestCapturaReal(unittest.TestCase):
    def test_captura_real(self):
        nav = captura.NavegadorAoVivo()
        try:
            p = nav.capturar("https://example.com/", "1366x768", "en-US")
        finally:
            nav.fechar()
        with Image.open(io.BytesIO(p.imagem)) as img:
            self.assertEqual(img.size, (1366, 768))
        self.assertIn("<body", p.html)


if __name__ == "__main__":
    unittest.main()
