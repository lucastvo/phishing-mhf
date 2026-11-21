import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import marcas  # noqa: E402


class TestDominioRegistravel(unittest.TestCase):
    def test_dominio_registravel(self):
        casos = {
            "https://www.itau.com.br/": "itau.com.br",                 # sufixo composto (o bug do .com.br)
            "https://secure07c.chase.com/web/auth/dashboard": "chase.com",
            "https://www.amazon.co.jp/ap/signin": "amazon.co.jp",
            "http://bbc.co.uk": "bbc.co.uk",
            "signin.ebay.de": "ebay.de",                               # sem esquema
            "https://WWW.PayPal.COM:443/signin": "paypal.com",          # maiúsculas e porta
            "https://paypal.com./signin": "paypal.com",                 # ponto final no host
            "http://paypal.com@evil.net/login": "evil.net",             # usuário antes do @: o host real é evil.net
            "http://192.168.0.10/login": "192.168.0.10",                # IP é devolvido como está
            "": "",
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                self.assertEqual(marcas.dominio_registravel(url), esperado)


TABELA_TESTE = os.path.join(os.path.dirname(__file__), "dados", "marcas_teste.json")


class TestTabela(unittest.TestCase):
    def setUp(self):
        self.t = marcas.ler_tabela(TABELA_TESTE)

    def test_entidade_do_rotulo(self):
        self.assertEqual(marcas.entidade_do_rotulo(self.t, "phishpedia", "Hotmail"), "Microsoft")
        self.assertEqual(marcas.entidade_do_rotulo(self.t, "phishpedia", "PayPal Inc."), "PayPal")
        self.assertEqual(marcas.entidade_do_rotulo(self.t, "phish360", "OFFICE"), "Microsoft")  # sem diferenciar maiúsculas
        for fora in ("Caixa Geral de Depositos", "CaixaBank", "AOL Inc.", "Instagram", "paypal inc."):
            with self.subTest(fora=fora):  # Phishpedia: comparação exata
                self.assertIsNone(marcas.entidade_do_rotulo(self.t, "phishpedia", fora))
        self.assertIsNone(marcas.entidade_do_rotulo(self.t, "phish360", "mic"))  # Made-in-China, não Microsoft
        with self.assertRaises(ValueError):
            marcas.entidade_do_rotulo(self.t, "visualphish", "paypal")

    def test_dominio_legitimo(self):
        self.assertTrue(marcas.dominio_legitimo(self.t, "PayPal", "https://www.paypal.com/signin"))
        self.assertTrue(marcas.dominio_legitimo(self.t, "Microsoft",
                                                "https://login.microsoftonline.com/common/oauth2/authorize"))
        self.assertTrue(marcas.dominio_legitimo(self.t, "Caixa", "https://internetbanking.caixa.gov.br/"))
        for falso in ("https://paypal.com.conta-segura.net/", "https://paypal-login.com/",
                      "https://secure-paypal.com.br/", "http://paypal.com@evil.net/", "", "about:blank"):
            with self.subTest(falso=falso):
                self.assertFalse(marcas.dominio_legitimo(self.t, "PayPal", falso))
        with self.assertRaises(KeyError):
            marcas.dominio_legitimo(self.t, "Nubank", "https://nubank.com.br/")


TABELA_REAL = os.path.join(os.path.dirname(__file__), "..", "config", "marcas.json")


class TestTabelaReal(unittest.TestCase):
    """Confere a própria config/marcas.json: um erro de digitação nela estragaria a captura e a avaliação."""

    def setUp(self):
        self.t = marcas.ler_tabela(TABELA_REAL)

    def test_vinte_entidades_completas(self):
        self.assertEqual(len(self.t), 20)
        self.assertEqual(len({e["entidade"] for e in self.t}), 20)
        for e in self.t:
            with self.subTest(entidade=e["entidade"]):
                self.assertTrue(e["logins"] and e["dominios"])
                self.assertTrue(e["nomes_phishpedia"] or e["nomes_phish360"])

    def test_url_de_login_esta_nos_dominios_da_propria_marca(self):
        for e in self.t:
            for login in e["logins"]:
                with self.subTest(entidade=e["entidade"], variante=login["variante"]):
                    self.assertIn(marcas.dominio_registravel(login["url"]), e["dominios"])

    def test_dominios_ja_sao_registraveis(self):
        # "www.paypal.com" na lista nunca casaria: a checagem compara domínios registráveis
        for e in self.t:
            for d in e["dominios"]:
                with self.subTest(dominio=d):
                    self.assertEqual(marcas.dominio_registravel(d), d)

    def test_rotulo_e_dominio_em_uma_marca_so(self):
        for campo in ("nomes_phishpedia", "nomes_phish360", "dominios"):
            vistos = {}
            for e in self.t:
                for n in e[campo]:
                    chave = n.lower() if campo != "nomes_phishpedia" else n
                    with self.subTest(campo=campo, valor=n):
                        self.assertNotIn(chave, vistos, f"também em {vistos.get(chave)}")
                    vistos[chave] = e["entidade"]

    def test_lida_pela_captura_com_ids_unicos(self):
        from mhf import templates
        variantes = templates.ler_marcas(TABELA_REAL)
        ids = [templates.id_entrada(v.entidade, v.variante, "x") for v in variantes]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(v.locale for v in variantes))


if __name__ == "__main__":
    unittest.main()
