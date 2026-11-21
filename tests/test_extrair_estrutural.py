import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import estrutural  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "extrair_estrutural.py")
_spec = importlib.util.spec_from_file_location("extrair_estrutural", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)

PAGINA = b"<html><body><form><input type='password'></form></body></html>"


def _linha(id_, caminho):
    return {"id": id_, "particao": "test", "rotulo": "phishing", "marca": "", "url": "https://x.com/",
            "caminho_html": caminho, "html_util": "1"}


class TestExtracaoRobusta(unittest.TestCase):
    def test_uma_amostra_ruim_nao_interrompe_as_outras(self):
        with tempfile.TemporaryDirectory() as raiz:
            for nome, conteudo in (("boa1.html", PAGINA), ("vazia.html", b"   "), ("quebra.html", b"<html>x"),
                                   ("boa2.html", PAGINA)):
                with open(os.path.join(raiz, nome), "wb") as f:
                    f.write(conteudo)
            linhas = [_linha("a", "boa1.html"),
                      _linha("b", "sumiu.html"),     # apagada (ex.: quarentena do antivírus) ou bloqueada
                      _linha("c", "vazia.html"),     # sem DOM útil
                      _linha("d", "quebra.html"),    # o extrator lança exceção
                      _linha("e", "boa2.html")]
            extrair_original = estrutural.extrair

            def extrair(conteudo, url=""):
                if conteudo == b"<html>x":
                    raise ValueError("documento inesperado")
                return extrair_original(conteudo, url)

            saida = io.StringIO()
            with mock.patch.object(script.estrutural, "extrair", side_effect=extrair):
                r = script.extrair_linhas(linhas, raiz, saida)

        ids = [json.loads(l)["id"] for l in saida.getvalue().splitlines()]
        self.assertEqual(ids, ["a", "e"])
        self.assertEqual(r["ok"], 2)
        self.assertEqual(r["sem_dom"], ["c"])
        self.assertEqual([f[0] for f in r["erros"]], ["b", "d"])
        self.assertIn("FileNotFoundError", r["erros"][0][1])
        self.assertIn("ValueError", r["erros"][1][1])


if __name__ == "__main__":
    unittest.main()
