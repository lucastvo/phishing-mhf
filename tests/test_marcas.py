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


if __name__ == "__main__":
    unittest.main()
