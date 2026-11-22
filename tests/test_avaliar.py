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


def _preparar(d):
    """Cenário com datas, modelos treinados e o JSONL estrutural; devolve (cenário, pasta dos modelos, estrutural)."""
    c = montar_cenario(d, com_datas=True)
    modelos = os.path.join(d, "modelos")
    argv = ["treinar.py", "--tabelas", c["prefixo"], "--divisao", c["divisao"], "--base", c["base"],
            "--marcas", c["marcas"], "--saida", modelos, "--arvores", "10", "--iteracoes", "20", "--n-jobs", "1"]
    with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
        treinar.main()
    estrutural = os.path.join(d, "estrutural_phishpedia_phish.jsonl")
    with open(c["prefixo"] + ".jsonl", encoding="utf-8") as f, open(estrutural, "w", encoding="utf-8") as g:
        for i, l in enumerate(map(json.loads, f)):
            g.write(json.dumps({"id": l["id"], "contagens": {"campos_senha": i % 2}}) + "\n")
    return c, modelos, estrutural


def _argv(c, modelos, estrutural, saida, *extra):
    return ["avaliar.py", "--tabelas", c["prefixo"], "--estrutural", estrutural, "--divisao", c["divisao"],
            "--base", c["base"], "--marcas", c["marcas"], "--plano", c["plano"], "--modelos", modelos,
            "--saida", saida, "--bootstrap", "20", "--iteracoes", "20", "--arvores", "10", "--n-jobs", "1", *extra]


class TestAvaliarRevisao(unittest.TestCase):
    """Correções da revisão feita antes da rodada no teste."""

    def test_temporal_ensaio_mesclagem_e_registro(self):
        with tempfile.TemporaryDirectory() as d:
            c, modelos, estrutural = _preparar(d)
            saida = os.path.join(d, "avaliacao")
            with mock.patch.object(sys, "argv", _argv(c, modelos, estrutural, saida, "--experimentos", "E0,E4a,E4b")),                     mock.patch("builtins.print"):
                avaliar.main()
            with mock.patch.object(sys, "argv", _argv(c, modelos, estrutural, saida, "--experimentos", "E5")),                     mock.patch("builtins.print"):
                avaliar.main()
            with open(os.path.join(saida, "resultados.json"), encoding="utf-8") as f:
                r = json.load(f)
            # E5 rodou depois, sem apagar E0 e E4
            self.assertTrue({"E0", "E4a", "E4b", "E5"} <= set(r))
            # base de 2026 pelo ano-alvo do plano: o template de 31/12/2025 da Netflix entra; nenhuma marca falta
            self.assertEqual(r["E4a"]["marcas_sem_template_2026"], [])
            self.assertIn("base_2026", r["E4a"])
            # base da época: amostras com data, templates até a data (os de 2019)
            self.assertIn("epoca", r["E4b"])
            with open(os.path.join(saida, "relatorio.md"), encoding="utf-8") as f:
                md = f.read()
            self.assertIn("Defasagem temporal", md)
            self.assertIn("Marcas que o classificador não viu", md)
            with open(os.path.join(saida, "registro.jsonl"), encoding="utf-8") as f:
                registro = [json.loads(l) for l in f]
            self.assertEqual([x["status"] for x in registro], ["iniciado", "concluido", "iniciado", "concluido"])
            # ensaio: uma dobra do desenvolvimento no papel do teste, em outra pasta, marcado como ensaio
            ensaio = os.path.join(d, "ensaio")
            with mock.patch.object(sys, "argv", _argv(c, modelos, estrutural, ensaio, "--ensaio")),                     mock.patch("builtins.print"):
                avaliar.main()
            with open(os.path.join(ensaio, "resultados.json"), encoding="utf-8") as f:
                re_ = json.load(f)
            self.assertTrue(re_["_ensaio"])
            self.assertTrue({"E0", "E1", "E1b", "E2", "E3", "E4a", "E4b", "E5"} <= set(re_))

    def test_estrutural_casado_pelo_nome(self):
        with tempfile.TemporaryDirectory() as d:
            c, modelos, estrutural = _preparar(d)
            errado = os.path.join(d, "estrutural_outro.jsonl")
            os.rename(estrutural, errado)
            argv = _argv(c, modelos, errado, os.path.join(d, "s"), "--experimentos", "E0")
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"),                     mock.patch("sys.stderr"), self.assertRaises(SystemExit):
                avaliar.main()


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
                    "--base", c["base"], "--marcas", c["marcas"], "--plano", c["plano"], "--modelos", modelos,
                    "--saida", saida, "--bootstrap", "20", "--iteracoes", "20", "--arvores", "10", "--n-jobs", "1"]
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
            self.assertEqual(len(registro), 4)  # iniciado + concluido, duas vezes
            self.assertEqual(registro[3]["experimentos"], ["E0"])
            self.assertIn("divisao_sha256", registro[0])


if __name__ == "__main__":
    unittest.main()
