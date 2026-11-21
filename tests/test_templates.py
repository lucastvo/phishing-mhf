import json
import os
import sys
import tempfile
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


class TestWayback(unittest.TestCase):
    def test_url_wayback(self):
        self.assertEqual(templates.url_wayback("20200601224504", "https://www.paypal.com/signin"),
                         "https://web.archive.org/web/20200601224504if_/https://www.paypal.com/signin")
        self.assertEqual(templates.url_wayback("20200601224504", "https://x.com/", "id_"),
                         "https://web.archive.org/web/20200601224504id_/https://x.com/")

    def test_remove_prefixos(self):
        casos = {
            'action="https://web.archive.org/web/20200601224504/https://login.live.com/ppsecure/post.srf"':
                'action="https://login.live.com/ppsecure/post.srf"',
            'src="//web.archive.org/web/20200601224504im_/https://x.com/a.png"': 'src="https://x.com/a.png"',
            'src="/web/20200601224504js_/https://x.com/a.js"': 'src="https://x.com/a.js"',
            'href="http://web.archive.org/web/20200601224504if_/http://x.com/"': 'href="http://x.com/"',
            'href="/web/2020/relatorio"': 'href="/web/2020/relatorio"',  # caminho legítimo: intocado
        }
        for entrada, esperado in casos.items():
            with self.subTest(entrada=entrada):
                self.assertEqual(templates.remover_prefixo_wayback(entrada), esperado)

    def test_remove_varios_no_mesmo_documento(self):
        html = ('<form action="/web/20200601224504/https://a.com/post">'
                '<img src="https://web.archive.org/web/20200601224504im_/https://a.com/logo.png"></form>')
        self.assertEqual(templates.remover_prefixo_wayback(html),
                         '<form action="https://a.com/post"><img src="https://a.com/logo.png"></form>')


def _escrever_meta(raiz, id_, conteudo, com_html_original=True, com_capturas=True):
    """Cria a pasta da entrada e grava meta.json (dict vira JSON; str é gravada como está) e, por
    padrão, html_original.html e o screenshot/DOM de cada resolução, como numa captura completa."""
    pasta = os.path.join(raiz, *id_.split("/"))
    os.makedirs(pasta, exist_ok=True)
    with open(os.path.join(pasta, "meta.json"), "w", encoding="utf-8") as f:
        f.write(conteudo if isinstance(conteudo, str) else json.dumps(conteudo))
    arquivos = ["html_original.html"] if com_html_original else []
    if com_capturas:
        arquivos += [f"shot_{r}.png" for r in ("1280x960", "1366x768")]
        arquivos += [f"dom_{r}.html" for r in ("1280x960", "1366x768")]
    for nome in arquivos:
        with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
            f.write("x")


META_OK = {"resolucoes": {"1280x960": {"status": "ok"}, "1366x768": {"status": "ok"}}}


class TestCaptura(unittest.TestCase):
    def test_pendentes(self):
        plano = [{"id": "a/p/2019-07-01", "buraco": None}, {"id": "a/p/2020-01-03", "buraco": None},
                 {"id": "a/p/2021-01-02", "buraco": None}, {"id": "a/p/2023-01-05", "buraco": None},
                 {"id": "a/p/2024-01-03", "buraco": None}, {"id": "a/p/buraco-2022", "buraco": "sem_snapshot"}]
        with tempfile.TemporaryDirectory() as raiz:
            _escrever_meta(raiz, "a/p/2019-07-01", META_OK)
            _escrever_meta(raiz, "a/p/2020-01-03",
                           {"resolucoes": {"1280x960": {"status": "ok"}, "1366x768": {"status": "sem_formulario"}}})
            os.makedirs(os.path.join(raiz, "a", "p", "2021-01-02"))  # captura interrompida: pasta sem meta.json
            _escrever_meta(raiz, "a/p/2023-01-05", '{"resolucoes": {"1280x9')  # meta.json truncado por uma queda
            # renderizou, mas o download do HTML original falhou (conexão derrubada pelo Wayback)
            _escrever_meta(raiz, "a/p/2024-01-03", META_OK, com_html_original=False)
            # status "ok", mas o screenshot/DOM não foi salvo (redirecionamento tardio no meio da gravação)
            _escrever_meta(raiz, "a/p/2025-01-04", META_OK, com_capturas=False)
            plano.insert(-1, {"id": "a/p/2025-01-04", "buraco": None})
            pendentes = [e["id"] for e in templates.entradas_pendentes(plano, raiz)]
        self.assertEqual(pendentes, ["a/p/2020-01-03", "a/p/2021-01-02", "a/p/2023-01-05", "a/p/2024-01-03",
                                     "a/p/2025-01-04"])


class TestRevisao(unittest.TestCase):
    def test_revisao_html(self):
        plano = [{"id": "paypal/padrao/2019-07-01", "entidade": "PayPal", "variante": "padrao", "anos_alvo": [2019],
                  "origem": "wayback", "buraco": None, "aprovado": None, "motivo": ""},
                 {"id": "paypal/padrao/buraco-2021", "entidade": "PayPal", "variante": "padrao", "anos_alvo": [2021],
                  "origem": "wayback", "buraco": "sem_snapshot", "aprovado": None, "motivo": ""}]
        metas = {"paypal/padrao/2019-07-01": {
            "url_snapshot": "https://web.archive.org/web/20190701000000/https://www.paypal.com/signin",
            "resolucoes": {"1280x960": {"status": "ok"}, "1366x768": {"status": "ok"}}}}
        html = templates.gerar_revisao_html(plano, metas)
        for trecho in ("paypal/padrao/2019-07-01/shot_1280x960.png", "sem_snapshot", ">2026<", "ao vivo",
                       "https://web.archive.org/web/20190701000000/https://www.paypal.com/signin"):
            with self.subTest(trecho=trecho):
                self.assertIn(trecho, html)

    def test_revisao_escapa_texto(self):
        plano = [{"id": "a/p/2019-07-01", "entidade": "A", "variante": "p", "anos_alvo": [2019], "origem": "wayback",
                  "buraco": None, "aprovado": False, "motivo": "<b>banner</b> cobre o form"}]
        html = templates.gerar_revisao_html(plano, {})
        self.assertIn("&lt;b&gt;banner&lt;/b&gt; cobre o form", html)
        self.assertNotIn("<b>banner</b>", html)

    def test_marcar_aprovacao(self):
        plano = [{"id": "a/p/2019-07-01", "aprovado": None, "motivo": ""}]
        templates.marcar_aprovacao(plano, "a/p/2019-07-01", False, "banner de cookies cobre o form")
        self.assertEqual((plano[0]["aprovado"], plano[0]["motivo"]), (False, "banner de cookies cobre o form"))
        with self.assertRaises(KeyError):
            templates.marcar_aprovacao(plano, "nao/existe/2019-01-01", True)


if __name__ == "__main__":
    unittest.main()
