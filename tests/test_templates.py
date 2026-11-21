import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import templates  # noqa: E402

CAMINHO_EXEMPLO = os.path.join(os.path.dirname(__file__), "..", "config", "marcas.exemplo.json")


class TestIdentificadores(unittest.TestCase):
    def test_slug(self):
        self.assertEqual(templates.slug("Itaú"), "itau")
        self.assertEqual(templates.slug("Bank of America"), "bank_of_america")
        self.assertEqual(templates.slug("Caixa Econômica Federal"), "caixa_economica_federal")
        # sem "_" repetido nem nas pontas, mesmo com pontuação e espaços sobrando
        self.assertEqual(templates.slug("  Wells Fargo & Company "), "wells_fargo_company")

    def test_id_entrada(self):
        self.assertEqual(templates.id_entrada("Itaú", "pessoal", "2019-06-30"), "itau/pessoal/2019-06-30")
        # a variante também vira slug, para o id servir de caminho de pasta no Windows
        self.assertEqual(templates.id_entrada("Itaú", "Pessoal Física", "ao-vivo"), "itau/pessoal_fisica/ao-vivo")

    def test_ler_marcas_exemplo(self):
        vs = templates.ler_marcas(CAMINHO_EXEMPLO)
        self.assertEqual([(v.entidade, v.variante) for v in vs], [("PayPal", "padrao"), ("Microsoft", "pessoal")])
        self.assertEqual(vs[1].url, "https://login.live.com/login.srf")
        self.assertEqual(vs[0].locale, "en-US")


if __name__ == "__main__":
    unittest.main()
