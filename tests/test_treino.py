import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import base, cascata, divisao, treino  # noqa: E402
from mhf.conjuntos import carregar_conjunto  # noqa: E402
from test_treinar import TABELA, montar_cenario  # noqa: E402


def _conjunto(d, filtro=None):
    c = montar_cenario(d)
    b = base.Base.carregar(c["base"])
    return carregar_conjunto([c["prefixo"]], divisao.ler_divisao(c["divisao"]), b, TABELA, None,
                             cascata.nomes_caracteristicas(), filtro_templates=filtro), b


class TestTreino(unittest.TestCase):
    def test_marcas_excluidas_saem_dos_pares(self):
        with tempfile.TemporaryDirectory() as d:
            conj, _ = _conjunto(d)
        todos = np.ones(len(conj["d1"]), dtype=bool)
        X, y, _ = treino.pares_de_treino(conj, todos)
        Xe, ye, _ = treino.pares_de_treino(conj, todos, entidades_excluidas=("Netflix",))
        # sem a Netflix: só os pares com o PayPal (menos o par de domínio próprio), e os positivos são só PayPal
        self.assertEqual(len(Xe), len(conj["d1"]) - 1)
        self.assertEqual(int(ye.sum()), 40)
        self.assertGreater(len(X), len(Xe))

    def test_escores_fora_da_dobra_sem_a_marca(self):
        with tempfile.TemporaryDirectory() as d:
            conj, _ = _conjunto(d)
        oof = treino.escores_fora_da_dobra(conj, "regressao", progresso=lambda s: None,
                                           entidades_excluidas=("Netflix",))
        # a marca excluída continua sendo pontuada (é o "marca nova"): o modelo só não a viu no treino
        dev = conj["dobra"] >= 0
        self.assertFalse(np.isnan(oof[dev]).all(axis=0).any())

    def test_filtro_de_templates_tira_a_marca(self):
        def so_paypal(meta, itens):
            return np.array([it["entidade"] == "PayPal" for it in itens])
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            conj, _ = _conjunto(d1, filtro=so_paypal)
            completo, _ = _conjunto(d2)
        i_net = conj["entidades"].index("Netflix")
        self.assertTrue(np.isnan(conj["X"][:, i_net, :]).all())   # Netflix fora da disputa, não similaridade 0
        self.assertFalse(np.isnan(conj["X"][:, 1 - i_net, :]).any())
        # d₁ só com os templates permitidos: nunca menor que o d₁ com a base completa
        self.assertTrue((conj["d1"] >= completo["d1"]).all())
        self.assertTrue((conj["d1"] > completo["d1"]).any())

    def test_metricas_com_acuracia(self):
        with tempfile.TemporaryDirectory() as d:
            conj, _ = _conjunto(d)
        escores = np.where(np.isnan(conj["X"][:, :, 1]), np.nan, conj["X"][:, :, 1])  # cosseno como escore
        m = treino.metricas_cascata(conj, escores, None, 0.8)
        self.assertIn("acuracia", m["por_amostra"])
        self.assertTrue(0 <= m["por_amostra"]["acuracia"] <= 1)


if __name__ == "__main__":
    unittest.main()
