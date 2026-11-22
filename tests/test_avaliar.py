import importlib.util
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from test_treinar import montar_cenario  # noqa: E402


def _carregar(nome):
    caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", f"{nome}.py")
    spec = importlib.util.spec_from_file_location(nome, caminho)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


treinar = _carregar("treinar")
avaliar = _carregar("avaliar")


class TestAvaliar(unittest.TestCase):
    def test_main_gera_saidas(self):
        with tempfile.TemporaryDirectory() as d:
            c = montar_cenario(d)
            modelos = os.path.join(d, "modelos")
            argv = ["treinar.py", "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--base", c["base"],
                    "--marcas", c["marcas"], "--saida", modelos, "--arvores", "10", "--iteracoes", "20",
                    "--n-jobs", "1"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                treinar.main()
            estrutural = os.path.join(d, "estrutural_phishpedia_phish.jsonl")
            with open(c["prefixo"] + ".jsonl", encoding="utf-8") as f, open(estrutural, "w", encoding="utf-8") as g:
                for i, l in enumerate(map(json.loads, f)):
                    g.write(json.dumps({"id": l["id"], "contagens": {"campos_senha": i % 2}}) + "\n")
            saida = os.path.join(d, "avaliacao")
            argv = ["avaliar.py", "--tabelas", c["prefixo"], "--estrutural", estrutural, "--divisao", c["divisao"],
                    "--base", c["base"], "--marcas", c["marcas"], "--modelos", modelos, "--saida", saida,
                    "--bootstrap", "20", "--iteracoes", "20", "--arvores", "10", "--n-jobs", "1"]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                avaliar.main()
            with open(os.path.join(saida, "resultados.json"), encoding="utf-8") as f:
                r = json.load(f)
            for chave in ("E0", "E1", "E1b", "E2", "E3", "E4a", "E4b", "E5"):
                self.assertIn(chave, r)
            e0 = r["E0"]
            self.assertIn("ic", e0["geral"]["por_amostra"])
            self.assertEqual(set(e0["fpr_grupos"]), {"todas", "phish360", "phishpedia_benign", "paginas_das_marcas",
                                                    "mais_parecidas"})
            self.assertEqual(len(r["E1"]), 7)  # todas as combinações de h, e e s
            self.assertTrue(r["E4b"].get("sem_amostras_com_data"))  # o cenário sintético não tem datas
            self.assertTrue(os.listdir(os.path.join(saida, "tabelas")))
            self.assertTrue(any(f.endswith(".pdf") for f in os.listdir(os.path.join(saida, "figuras"))))
            with open(os.path.join(saida, "tabelas", "principal.tex"), encoding="utf-8") as f:
                self.assertIn("\\toprule", f.read())
            # segunda execução (só E0): o registro guarda as duas
            with mock.patch.object(sys, "argv", argv + ["--experimentos", "E0"]), mock.patch("builtins.print"):
                avaliar.main()
            with open(os.path.join(saida, "registro.jsonl"), encoding="utf-8") as f:
                registro = [json.loads(l) for l in f]
            self.assertEqual(len(registro), 2)
            self.assertEqual(registro[1]["experimentos"], ["E0"])
            self.assertIn("divisao_sha256", registro[0])


if __name__ == "__main__":
    unittest.main()
