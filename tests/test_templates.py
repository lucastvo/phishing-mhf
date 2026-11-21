import os
import sys
import unittest
from datetime import datetime

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


PAYPAL = templates.VarianteLogin("PayPal", "padrao", "https://www.paypal.com/signin", "en-US")


class TestPlano(unittest.TestCase):
    def test_prefere_200_mais_proximo(self):
        # o 302 está mais perto (4 dias), mas um 200 a 12 dias ganha
        caps = [("20181220000000", 200), ("20190105000000", 302), ("20190301000000", 200)]
        self.assertEqual(templates.escolher_snapshot(caps, datetime(2019, 1, 1)), ("20181220000000", 200))

    def test_aceita_3xx_sem_200(self):
        self.assertEqual(templates.escolher_snapshot([("20190105000000", 301)], datetime(2019, 1, 1)),
                         ("20190105000000", 301))

    def test_fora_da_tolerancia(self):
        self.assertIsNone(templates.escolher_snapshot([("20190720000000", 200)], datetime(2019, 1, 1)))  # 200 dias

    def test_planejar_deduplica_buraco_e_ao_vivo(self):
        caps = [("20190702000000", 200), ("20220110000000", 200)]  # 182 e 183 dias de 2019 e 2020: os dois caem no mesmo
        plano = templates.planejar_variante(PAYPAL, caps, anos=range(2019, 2023))
        ids = {e["id"]: e for e in plano}
        self.assertEqual(ids["paypal/padrao/2019-07-02"]["anos_alvo"], [2019, 2020])
        self.assertEqual(ids["paypal/padrao/2019-07-02"]["timestamp"], "20190702000000")
        self.assertEqual(ids["paypal/padrao/buraco-2021"]["buraco"], "sem_snapshot")
        self.assertEqual(ids["paypal/padrao/2022-01-10"]["anos_alvo"], [2022])
        self.assertEqual(ids["paypal/padrao/ao-vivo"]["origem"], "ao_vivo")
        self.assertEqual(len(plano), 4)  # 2019+2020 juntos, buraco 2021, 2022, ao vivo
        self.assertEqual(plano[-1]["id"], "paypal/padrao/ao-vivo")

    def test_planejar_erro_consulta(self):
        plano = templates.planejar_variante(PAYPAL, None, anos=range(2019, 2021))
        self.assertEqual(sorted(e["buraco"] for e in plano if e["buraco"]), ["erro_consulta", "erro_consulta"])

    def test_mescla_preserva_aprovacao(self):
        antigo = [{"id": "x/y/2019-07-01", "aprovado": True, "motivo": "ok"}]
        novo = [{"id": "x/y/2019-07-01", "aprovado": None, "motivo": ""},
                {"id": "x/y/ao-vivo", "aprovado": None, "motivo": ""}]
        m = {e["id"]: e for e in templates.mesclar_plano(novo, antigo)}
        self.assertEqual((m["x/y/2019-07-01"]["aprovado"], m["x/y/2019-07-01"]["motivo"]), (True, "ok"))
        self.assertIsNone(m["x/y/ao-vivo"]["aprovado"])


if __name__ == "__main__":
    unittest.main()
