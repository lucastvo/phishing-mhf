import importlib.util
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from test_base import base_sintetica  # noqa: E402

_CAMINHO = os.path.join(os.path.dirname(__file__), "..", "scripts", "medir_busca.py")
_spec = importlib.util.spec_from_file_location("medir_busca", _CAMINHO)
script = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(script)


def _consultas(n, semente=0):
    rng = np.random.default_rng(semente)
    def normalizados(d):
        v = rng.normal(size=(n, d)).astype(np.float32)
        return v / np.linalg.norm(v, axis=1, keepdims=True)
    return {"phash64": [f"{int(x):016x}" for x in rng.integers(0, 2**63, size=n, dtype=np.int64)],
            "small": normalizados(576), "large": normalizados(960)}


class TestMedirBusca(unittest.TestCase):
    def test_faiss_e_exaustiva_concordam(self):
        b = base_sintetica()
        consultas = _consultas(20)
        for sinal in ("h64", "small", "large"):
            idx_e, sim_e = script.topo_exaustivo(b, "1366x768", consultas, sinal)
            idx_f, sim_f = script.topo_faiss(b, "1366x768", consultas, sinal)
            self.assertEqual(sim_e.shape, (20,))
            self.assertTrue(set(idx_e) <= {0, 1, 2} and set(idx_f) <= {0, 1, 2})  # só a classe pedida
            self.assertEqual(script.concordancia(sim_e, sim_f), 1.0, sinal)

    def test_exaustiva_usa_base_vizinhos(self):
        # a busca exaustiva medida é a do código (Base.vizinhos), não uma cópia do núcleo numpy
        b = base_sintetica()
        chamadas = []
        original = b.vizinhos
        b.vizinhos = lambda *a, **k: chamadas.append(a[2]) or original(*a, **k)
        script.topo_exaustivo(b, "1366x768", _consultas(3), "small")
        self.assertEqual(chamadas, ["small"] * 3)

    def test_empate_real_concorda(self):
        b = base_sintetica()
        consultas = _consultas(1)
        consultas["phash64"] = ["0" * 15 + "3"]  # 2 bits de distância de dois templates: empate
        _, sim_e = script.topo_exaustivo(b, "1366x768", consultas, "h64")
        _, sim_f = script.topo_faiss(b, "1366x768", consultas, "h64")
        self.assertAlmostEqual(float(sim_e[0]), 1 - 2 / 64)
        self.assertEqual(script.concordancia(sim_e, sim_f), 1.0)

    def test_concordancia_com_empate(self):
        # índices diferentes com a mesma similaridade (empate) contam como concordância
        self.assertEqual(script.concordancia(np.array([0.5, 0.75]), np.array([0.5, 0.75])), 1.0)
        self.assertEqual(script.concordancia(np.array([0.5, 0.75]), np.array([0.5, 0.70])), 0.5)


if __name__ == "__main__":
    unittest.main()
