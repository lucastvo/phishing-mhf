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


def _item(id_, entidade, classe, h64, s_html, sem_s=False):
    s = None if sem_s else estrutural.extrair(s_html, f"https://www.{entidade.lower()}.com/").para_dict()
    return {"id": id_, "entidade": entidade, "variante": "login", "origem": "wayback", "timestamp": "20210101000000",
            "classe": classe, "phash64": h64, "phash256": h64 * 4, "dominios": [f"{entidade.lower()}.com"], "s": s}


def base_sintetica():
    """4 itens: 3 em 1366x768 (PayPal, PayPal, Netflix sem s) e 1 em 1920x1080."""
    itens = [_item("a@1366x768", "PayPal", "1366x768", "0" * 16, DOM_LOGIN),
             _item("b@1366x768", "PayPal", "1366x768", "0" * 15 + "f", DOM_LOGIN),
             _item("c@1366x768", "Netflix", "1366x768", "f" * 16, DOM_INICIAL, sem_s=True),
             _item("d@1920x1080", "PayPal", "1920x1080", "0" * 16, DOM_LOGIN)]
    emb = {"small": np.stack([_vetor(576, i) for i in range(4)]),
           "large": np.stack([_vetor(960, 10 + i) for i in range(4)])}
    return base.Base(itens, emb)


def consulta_do_item(b, i, com_s=True):
    it = b.itens[i]
    return {"phash64": it["phash64"], "phash256": it["phash256"], "small": b.emb["small"][i],
            "large": b.emb["large"][i],
            "s": estrutural.ImpressaoEstrutural.de_dict(it["s"]) if com_s and it["s"] else None}


class TestBusca(unittest.TestCase):
    def test_palavras_do_hash_com_zeros_a_esquerda(self):
        self.assertEqual(list(base.palavras_do_hash("00000000000000ff")), [255])
        p256 = base.palavras_do_hash("0" * 63 + "1")
        self.assertEqual((len(p256), int(p256[-1]), int(p256[0])), (4, 1, 0))
        d = np.bitwise_count(base.palavras_do_hash("0" * 16) ^ base.palavras_do_hash("0" * 15 + "f")).sum()
        self.assertEqual(int(d), 4)
        with self.assertRaises(ValueError):
            base.palavras_do_hash("abc")

    def test_so_templates_da_classe(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0), "1366x768")
        self.assertEqual(list(r["indices"]), [0, 1, 2])
        self.assertEqual(r["cos_small"].shape, (3,))

    def test_consulta_igual_a_um_template(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0), "1366x768")
        self.assertEqual(list(r["dist_h64"]), [0, 4, 64])
        self.assertEqual(list(r["dist_h256"]), [0, 16, 256])
        self.assertAlmostEqual(float(r["sim_h64"][1]), 1 - 4 / 64)
        self.assertAlmostEqual(float(r["cos_small"][0]), 1.0, places=5)
        self.assertAlmostEqual(float(r["cos_large"][0]), 1.0, places=5)
        self.assertEqual((r["jaccard_caminhos"][0], r["hash_igual"][0]), (1.0, 1.0))
        self.assertEqual(r["sim_contagens"][1], 1.0)  # mesmo DOM

    def test_sem_s_na_consulta_da_nan(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0, com_s=False), "1366x768")
        for k in base.SINAIS_S:
            self.assertTrue(np.isnan(r[k]).all(), k)
        self.assertEqual(r["dist_h64"][0], 0)  # h e e continuam

    def test_template_sem_s_da_nan_na_coluna(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0), "1366x768")
        self.assertTrue(math.isnan(r["jaccard_caminhos"][2]))
        self.assertFalse(np.isnan(r["jaccard_caminhos"][:2]).any())

    def test_campos_ausentes_na_consulta(self):
        b = base_sintetica()
        r = b.similaridades({"small": b.emb["small"][0]}, "1366x768")
        self.assertEqual(list(r["dist_h64"]), [-1, -1, -1])
        self.assertTrue(np.isnan(r["sim_h64"]).all() and np.isnan(r["cos_large"]).all())
        self.assertAlmostEqual(float(r["cos_small"][0]), 1.0, places=5)

    def test_sinais_restringe_as_chaves(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0), "1366x768", sinais=("h",))
        self.assertEqual(set(r), {"indices", "dist_h64", "dist_h256", "sim_h64", "sim_h256"})
        with self.assertRaises(ValueError):
            b.similaridades(consulta_do_item(b, 0), "1366x768", sinais=("x",))

    def test_classe_sem_templates_devolve_vazio(self):
        b = base_sintetica()
        r = b.similaridades(consulta_do_item(b, 0), "1280x960")
        self.assertEqual(len(r["indices"]), 0)
        self.assertEqual(r["cos_small"].shape, (0,))
        self.assertEqual(r["jaccard_caminhos"].shape, (0,))
        self.assertEqual(b.vizinhos(consulta_do_item(b, 0), "1280x960", "small"), [])

    def test_classe_desconhecida(self):
        b = base_sintetica()
        with self.assertRaises(ValueError):
            b.similaridades(consulta_do_item(b, 0), "1024x768")

    def test_vizinhos_ordem_k_e_empate(self):
        b = base_sintetica()
        consulta = {"phash64": "0" * 15 + "3"}  # 2 bits de a e 2 de b: empate
        viz = b.vizinhos(consulta, "1366x768", "h64", k=2)
        self.assertEqual([i for i, _ in viz], [0, 1])
        self.assertAlmostEqual(viz[0][1], 1 - 2 / 64)
        self.assertEqual([i for i, _ in b.vizinhos(consulta_do_item(b, 1), "1366x768", "small", k=1)], [1])
        self.assertEqual([i for i, _ in b.vizinhos(consulta_do_item(b, 0), "1366x768", "caminhos", k=3)][:2],
                         [0, 1])  # c (sem s) por último
        self.assertEqual(len(b.vizinhos(consulta_do_item(b, 0), "1366x768", "large", k=10)), 3)
        with self.assertRaises(ValueError):
            b.vizinhos(consulta, "1366x768", "xyz")


if __name__ == "__main__":
    unittest.main()
