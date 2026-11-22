import json
import math
import os
import sys
import tempfile
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import base, estrutural, templates  # noqa: E402

TABELA = [{"entidade": "PayPal", "dominios": ["paypal.com"], "nomes_phish360": ["paypal"], "nomes_phishpedia": []},
          {"entidade": "Netflix", "dominios": ["netflix.com"], "nomes_phish360": ["netflix"], "nomes_phishpedia": []}]

DOM_LOGIN = ("<html><body><div><form action='/login'><input type='email'><input type='password'>"
             "<button>Entrar</button></form></div></body></html>")
DOM_INICIAL = "<html><body><div><nav><a href='/'>x</a></nav><div><img src='a.png'><p>oi</p></div></div></body></html>"


def _entrada(entidade, variante, rotulo):
    return {"id": templates.id_entrada(entidade, variante, rotulo), "entidade": entidade, "variante": variante,
            "origem": "wayback", "timestamp": rotulo.replace("-", "") + "000000",
            "url_login": f"https://www.{entidade.lower()}.com/{variante}"}


def _vetor(dim, semente):
    v = np.random.default_rng(semente).normal(size=dim).astype(np.float32)
    return v / np.linalg.norm(v)


def _gravar_dom(raiz, entrada, resolucao, html):
    pasta = templates.pasta_entrada(raiz, entrada["id"])
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, f"dom_{resolucao}.html"), "w", encoding="utf-8") as f:
        f.write(html)


def _cenario(raiz):
    """Dois templates (PayPal login, Netflix login) em 1366x768 e 1920x1080; visual em outra ordem."""
    paypal = _entrada("PayPal", "login", "2021-01-01")
    netflix = _entrada("Netflix", "login", "2021-01-01")
    pares = [(paypal, "1366x768"), (netflix, "1366x768"), (paypal, "1920x1080")]
    for e, r in pares:
        _gravar_dom(raiz, e, r, DOM_LOGIN if e is paypal else DOM_INICIAL)
    ids = [f"{e['id']}@{r}" for e, r in pares]
    ordem_visual = [2, 0, 1]  # o JSONL visual não está na ordem dos pares
    linhas = [{"id": ids[i], "classe": pares[i][1], "phash64": f"{i:016x}", "phash256": f"{i:064x}"}
              for i in ordem_visual]
    emb = {"small": np.stack([_vetor(576, i) for i in ordem_visual]),
           "large": np.stack([_vetor(960, 10 + i) for i in ordem_visual])}
    return pares, ids, linhas, emb


class TestConstrucao(unittest.TestCase):
    def test_itens_na_ordem_dos_pares_com_embeddings_alinhados(self):
        with tempfile.TemporaryDirectory() as raiz:
            pares, ids, linhas, emb = _cenario(raiz)
            itens, emb_base = base.construir_itens(pares, raiz, linhas, emb, TABELA)
        self.assertEqual([i["id"] for i in itens], ids)
        self.assertEqual([i["classe"] for i in itens], ["1366x768", "1366x768", "1920x1080"])
        for i in range(3):  # a linha i dos embeddings da base é a do template i
            np.testing.assert_allclose(emb_base["small"][i], _vetor(576, i))
            np.testing.assert_allclose(emb_base["large"][i], _vetor(960, 10 + i))
        self.assertEqual(itens[0]["phash64"], f"{0:016x}")
        self.assertEqual((itens[0]["entidade"], itens[0]["dominios"]), ("PayPal", ["paypal.com"]))
        self.assertEqual((itens[0]["origem"], itens[0]["timestamp"]), ("wayback", "20210101000000"))
        self.assertEqual(itens[0]["s"]["contagens"]["campos_senha"], 1)
        self.assertEqual(itens[1]["s"]["contagens"]["campos_senha"], 0)

    def test_template_sem_linha_visual_falha_listando_ids(self):
        with tempfile.TemporaryDirectory() as raiz:
            pares, ids, linhas, emb = _cenario(raiz)
            sem_ultimo = [l for l in linhas if l["id"] != ids[2]]
            keep = [i for i, l in enumerate(linhas) if l["id"] != ids[2]]
            emb_cortado = {m: v[keep] for m, v in emb.items()}
            with self.assertRaisesRegex(ValueError, "paypal/login/2021-01-01@1920x1080"):
                base.construir_itens(pares, raiz, sem_ultimo, emb_cortado, TABELA)

    def test_dom_ausente_deixa_s_nulo(self):
        with tempfile.TemporaryDirectory() as raiz:
            pares, ids, linhas, emb = _cenario(raiz)
            os.remove(os.path.join(templates.pasta_entrada(raiz, pares[2][0]["id"]), "dom_1920x1080.html"))
            itens, _ = base.construir_itens(pares, raiz, linhas, emb, TABELA)
        self.assertIsNone(itens[2]["s"])
        self.assertEqual(len(itens), 3)  # o item continua na base

    def test_gravar_e_carregar(self):
        with tempfile.TemporaryDirectory() as raiz:
            pares, ids, linhas, emb = _cenario(raiz)
            itens, emb_base = base.construir_itens(pares, raiz, linhas, emb, TABELA)
            pasta = os.path.join(raiz, "base")
            base.gravar(pasta, itens, emb_base, {"teste": True})
            b = base.Base.carregar(pasta)
            self.assertTrue(os.path.exists(os.path.join(pasta, "base_meta.json")))
        self.assertEqual(b.itens, itens)
        for m in base.MODELOS:
            np.testing.assert_allclose(b.emb[m], emb_base[m])
        self.assertEqual(list(b.indices("1366x768")), [0, 1])
        self.assertEqual(list(b.indices("1920x1080")), [2])

    def test_carregar_recusa_npy_desalinhado(self):
        with tempfile.TemporaryDirectory() as raiz:
            pares, ids, linhas, emb = _cenario(raiz)
            itens, emb_base = base.construir_itens(pares, raiz, linhas, emb, TABELA)
            pasta = os.path.join(raiz, "base")
            base.gravar(pasta, itens, emb_base, {})
            np.save(os.path.join(pasta, "base_small.npy"), emb_base["small"][:2])
            with self.assertRaises(ValueError):
                base.Base.carregar(pasta)


if __name__ == "__main__":
    unittest.main()
