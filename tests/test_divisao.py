import csv
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from collections import defaultdict
from unittest import mock

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import divisao  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "dividir.py")
_spec = importlib.util.spec_from_file_location("dividir", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _a(dataset, id_, rotulo="phishing", entidade="PayPal", marca="paypal", elementos=50, hash_="h", particao=""):
    return {"dataset": dataset, "id": id_, "particao": particao, "rotulo": rotulo, "entidade": entidade,
            "marca": marca, "elementos": elementos, "hash": hash_}


def _muitas(n=300, semente=1):
    """Amostras só do Phishpedia, com grupos repetidos (kits copiados) e três estratos."""
    rng = np.random.default_rng(semente)
    amostras = []
    for i in range(n):
        tipo = i % 3
        grupo = int(rng.integers(0, n // 4))
        if tipo == 0:
            amostras.append(_a("phishpedia_phish", f"p{i}", hash_=f"k{grupo}"))
        elif tipo == 1:
            amostras.append(_a("phishpedia_phish", f"n{i}", entidade="Netflix", marca="Netflix", hash_=f"m{grupo}"))
        else:
            amostras.append(_a("phishpedia_benign", f"b{i}", rotulo="benigno", entidade=None, marca="",
                               hash_=f"b{i}"))
    return amostras


class TestGrupoEstrato(unittest.TestCase):
    def test_grupo_e_estrato(self):
        self.assertEqual(divisao.grupo_da_amostra(_a("x", "1", hash_="abc")), "h:abc")
        self.assertEqual(divisao.grupo_da_amostra(_a("x", "1", elementos=5)), "a:x:1")  # DOM degenerado
        self.assertEqual(divisao.grupo_da_amostra(_a("x", "1", elementos=None, hash_=None)), "a:x:1")  # sem HTML
        self.assertTrue(divisao.s_util(6) and not divisao.s_util(5) and not divisao.s_util(None))
        self.assertEqual(divisao.estrato(_a("x", "1")), "PayPal")
        self.assertEqual(divisao.estrato(_a("x", "1", entidade=None, marca="Instagram")), "fora")
        self.assertEqual(divisao.estrato(_a("x", "1", entidade=None, marca="")), "sem_marca")
        self.assertEqual(divisao.estrato(_a("x", "1", rotulo="benigno", entidade=None, marca="")), "benigno")


class TestDividir(unittest.TestCase):
    def test_grupo_do_test_do_phish360_vai_inteiro_para_o_teste(self):
        amostras = _muitas() + [_a("phish360", "test\\P1", hash_="comum", particao="test", entidade=None, marca=""),
                                _a("phish360", "trainval\\P2", hash_="comum", particao="trainval"),
                                _a("phishpedia_phish", "kit", hash_="comum")]
        linhas = divisao.dividir(amostras)
        self.assertEqual([l["conjunto"] for l in linhas[-3:]], ["teste"] * 3)
        self.assertEqual([l["dobra"] for l in linhas[-3:]], [-1] * 3)

    def test_trainval_fica_no_desenvolvimento(self):
        amostras = _muitas() + [_a("phish360", "trainval\\P9", hash_="so_trainval", particao="trainval"),
                                _a("phishpedia_phish", "kit2", hash_="so_trainval")]
        linhas = divisao.dividir(amostras)
        self.assertEqual([l["conjunto"] for l in linhas[-2:]], ["desenvolvimento"] * 2)

    def test_nenhum_grupo_atravessa_conjuntos_ou_dobras(self):
        linhas = divisao.dividir(_muitas())
        destinos = defaultdict(set)
        for l in linhas:
            destinos[l["grupo"]].add((l["conjunto"], l["dobra"]))
        self.assertTrue(all(len(d) == 1 for d in destinos.values()))

    def test_fracao_do_teste_no_phishpedia(self):
        linhas = divisao.dividir(_muitas(600))
        frac = np.mean([l["conjunto"] == "teste" for l in linhas])
        self.assertTrue(0.2 <= frac <= 0.4, frac)

    def test_dobras_de_0_a_4_so_no_desenvolvimento(self):
        linhas = divisao.dividir(_muitas())
        self.assertEqual({l["dobra"] for l in linhas if l["conjunto"] == "desenvolvimento"}, {0, 1, 2, 3, 4})
        self.assertEqual({l["dobra"] for l in linhas if l["conjunto"] == "teste"}, {-1})

    def test_deterministico(self):
        self.assertEqual(divisao.dividir(_muitas()), divisao.dividir(_muitas()))

    def test_pesos_por_estrutura(self):
        linhas = [{"grupo": "g", "conjunto": "teste"}] * 4 + [{"grupo": "g", "conjunto": "desenvolvimento"},
                                                              {"grupo": "u", "conjunto": "teste"}]
        np.testing.assert_allclose(divisao.pesos_por_estrutura(linhas), [0.25] * 4 + [1.0, 1.0])


class TestMainDividir(unittest.TestCase):
    def test_main_grava_csv(self):
        with tempfile.TemporaryDirectory() as d:
            amostras = _muitas(120)
            for ds in ("phishpedia_phish", "phishpedia_benign"):
                with open(os.path.join(d, f"similaridades_{ds}.jsonl"), "w", encoding="utf-8") as f:
                    for a in amostras:
                        if a["dataset"] == ds:
                            f.write(json.dumps({"id": a["id"], "particao": "", "rotulo": a["rotulo"],
                                                "marca": a["marca"], "entidade": a["entidade"],
                                                "elementos": a["elementos"]}) + "\n")
                with open(os.path.join(d, f"estrutural_{ds}.jsonl"), "w", encoding="utf-8") as f:
                    for a in amostras:
                        if a["dataset"] == ds:
                            f.write(json.dumps({"id": a["id"], "hash_canonico": a["hash"]}) + "\n")
            excl = os.path.join(d, "exclusoes.json")
            with open(excl, "w", encoding="utf-8") as f:
                json.dump({"exclusoes": [{"dataset": "phishpedia_phish", "id": "p0", "motivo": "teste"}]}, f)
            saida = os.path.join(d, "divisao.csv")
            argv = ["dividir.py", "--tabelas", os.path.join(d, "similaridades_phishpedia_phish"),
                    os.path.join(d, "similaridades_phishpedia_benign"),
                    "--estrutural", os.path.join(d, "estrutural_phishpedia_phish.jsonl"),
                    os.path.join(d, "estrutural_phishpedia_benign.jsonl"), "--exclusoes", excl, "--saida", saida]
            with mock.patch.object(sys, "argv", argv), mock.patch("builtins.print"):
                script.main()
            with open(saida, encoding="utf-8") as f:
                linhas = list(csv.DictReader(f))
            self.assertEqual(len(linhas), 119)  # p0 excluída
            self.assertNotIn("p0", {l["id"] for l in linhas})
            self.assertEqual(set(linhas[0]), {"dataset", "id", "conjunto", "dobra", "grupo", "estrato"})
            lida = divisao.ler_divisao(saida)
            self.assertIsInstance(lida[("phishpedia_phish", "p3")]["dobra"], int)


if __name__ == "__main__":
    unittest.main()
