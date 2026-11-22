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
            # dentro de JavaScript/JSON da página, com barras escapadas (visto nos snapshots do PayPal)
            "url:'https:\\/\\/web.archive.org\\/web\\/20190102025722\\/https:\\/\\/www.paypal.com\\/signin'":
                "url:'https:\\/\\/www.paypal.com\\/signin'",
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


# ---------------------------------------------------------------- correções da revisão independente

ARQUIVOS_CAPTURA = ["html_original.html"] + [f"{p}_{r}" for r in ("1280x960", "1366x768")
                                             for p in ("shot", "dom")]


def _captura_completa(raiz, id_, data_captura, url_login="https://x.com/login", timestamp="20200101000000",
                      status="ok"):
    meta = {"url_login": url_login, "timestamp": timestamp, "data_captura": data_captura,
            "resolucoes": {"1280x960": {"status": status}, "1366x768": {"status": status}}}
    _escrever_meta(raiz, id_, meta)


def _entrada(id_, aprovado=None, aprovado_captura=None, url_login="https://x.com/login",
             timestamp="20200101000000", buraco=None, origem="wayback"):
    return {"id": id_, "entidade": "X", "variante": "p", "url_login": url_login, "timestamp": timestamp,
            "origem": origem, "anos_alvo": [2020], "buraco": buraco, "aprovado": aprovado, "motivo": "",
            "aprovado_captura": aprovado_captura}


class TestAprovacaoAmarradaAoConteudo(unittest.TestCase):  # C1
    def test_aprovar_recusa_buraco(self):
        plano = [_entrada("x/p/buraco-2021", buraco="sem_snapshot", timestamp=None)]
        for decisao in (True, False):
            with self.assertRaises(ValueError):
                templates.marcar_aprovacao(plano, "x/p/buraco-2021", decisao, data_captura="2026-11-20T23:00:00")

    def test_aprovar_exige_captura_e_guarda_qual_foi_vista(self):
        plano = [_entrada("x/p/2020-01-01")]
        with self.assertRaises(ValueError):  # aprovar o que ainda não foi capturado
            templates.marcar_aprovacao(plano, "x/p/2020-01-01", True)
        templates.marcar_aprovacao(plano, "x/p/2020-01-01", True, data_captura="2026-11-20T23:00:00")
        self.assertEqual((plano[0]["aprovado"], plano[0]["aprovado_captura"]), (True, "2026-11-20T23:00:00"))

    def test_pendentes_pula_entradas_com_decisao(self):
        # aprovada com status ruim (o revisor viu o screenshot bom) e rejeitada: não são recapturadas
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),
                 _entrada("x/p/2021-01-01", aprovado=False)]
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2020-01-01", "t1", status="sem_formulario")
            self.assertEqual(templates.entradas_pendentes(plano, raiz), [])

    def test_pendentes_captura_de_outra_url_ou_snapshot(self):
        plano = [_entrada("x/p/2020-01-01", url_login="https://x.com/br/login"),
                 _entrada("x/p/2021-01-01", timestamp="20210101000000")]
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2020-01-01", "t1", url_login="https://x.com/login")
            _captura_completa(raiz, "x/p/2021-01-01", "t1", timestamp="20210102000000")
            pendentes = [e["id"] for e in templates.entradas_pendentes(plano, raiz)]
        self.assertEqual(pendentes, ["x/p/2020-01-01", "x/p/2021-01-01"])

    def test_mescla_so_herda_se_o_snapshot_for_o_mesmo(self):
        antigo = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),
                  _entrada("x/p/2021-01-01", aprovado=True, aprovado_captura="t1")]
        novo = [_entrada("x/p/2020-01-01"),                               # mesmo snapshot: herda
                _entrada("x/p/2021-01-01", timestamp="20210101080000")]   # mesmo id, outro snapshot: não herda
        m = {e["id"]: e for e in templates.mesclar_plano(novo, antigo)}
        self.assertEqual((m["x/p/2020-01-01"]["aprovado"], m["x/p/2020-01-01"]["aprovado_captura"]), (True, "t1"))
        self.assertIsNone(m["x/p/2021-01-01"]["aprovado"])

    def test_entradas_aprovadas(self):
        plano = [_entrada("x/p/2019-01-01", aprovado=True, aprovado_captura="t1"),  # vale
                 _entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),  # recapturada depois
                 _entrada("x/p/2021-01-01", aprovado=True, aprovado_captura="t1"),  # arquivos sumiram
                 _entrada("x/p/2022-01-01", aprovado=False),                         # rejeitada
                 _entrada("x/p/2023-01-01")]                                         # não revisada
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2019-01-01", "t1")
            _captura_completa(raiz, "x/p/2020-01-01", "t2")
            _escrever_meta(raiz, "x/p/2021-01-01", {"data_captura": "t1", "url_login": "https://x.com/login",
                                                   "timestamp": "20200101000000", "resolucoes": {}},
                           com_capturas=False)
            for id_ in ("x/p/2022-01-01", "x/p/2023-01-01"):
                _captura_completa(raiz, id_, "t1")
            aprovadas = [e["id"] for e in templates.entradas_aprovadas(plano, raiz)]
        self.assertEqual(aprovadas, ["x/p/2019-01-01"])

    def test_revisao_mostra_aprovacao_vencida(self):
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1")]
        metas = {"x/p/2020-01-01": {"data_captura": "t2", "resolucoes": {"1280x960": {"status": "ok"}}}}
        html = templates.gerar_revisao_html(plano, metas)
        self.assertIn("aprovação vencida", html)
        # o resumo do topo não pode contar a vencida como aprovada
        self.assertIn("0 aprovados", html)
        self.assertIn("1 aprovações vencidas", html)


class TestCdxForaDoAr(unittest.TestCase):  # I1
    def test_mescla_mantem_a_variante_quando_a_consulta_falhou(self):
        antigo = templates.planejar_variante(PAYPAL, [("20200101192011", 200)], anos=range(2020, 2021))
        templates.marcar_aprovacao(antigo, "paypal/padrao/2020-01-01", True, data_captura="t1")
        novo = templates.planejar_variante(PAYPAL, None, anos=range(2020, 2021))  # CDX fora do ar
        mesclado = templates.mesclar_plano(novo, antigo)
        self.assertEqual(mesclado, antigo)

    def test_sem_plano_antigo_os_buracos_ficam(self):
        novo = templates.planejar_variante(PAYPAL, None, anos=range(2020, 2021))
        self.assertEqual(templates.mesclar_plano(novo, []), novo)


class TestInjecoesWayback(unittest.TestCase):  # I2
    def test_limpar_injecoes(self):
        # Trechos reais de um DOM capturado (PayPal 2019) + um script e um CSS legítimos da página.
        html = ('<html lang="en" class=" js " style="--wm-toolbar-height: 67px;"><head>'
                '<script src="https://web-static.archive.org/_static/js/athena.js" type="text/javascript"></script>'
                '<script type="text/javascript" src="https://web-static.archive.org/_static/js/wombat.js?v=o9P2E1FK" '
                'charset="utf-8"></script>'
                '<script type="text/javascript">\n    __wm.init("https://web.archive.org/web");\n</script>'
                '<link rel="stylesheet" type="text/css" href="https://web-static.archive.org/_static/css/banner-styles.css?v=1utQkbB3">'
                '<script type="text/javascript">window.addEventListener(\'DOMContentLoaded\',function(){'
                'var v=archive_analytics.values;});</script>'
                '<!-- End Wayback Rewrite JS Include -->'
                '<script src="https://www.paypalobjects.com/web/res/app.js"></script>'
                '<link rel="stylesheet" href="https://www.paypalobjects.com/web/res/app.css">'
                '</head><body><form action="https://www.paypal.com/signin"></form>'
                '<script>__wm.rw(0);</script>'
                '<script type="text/javascript">//<![CDATA[\n__wm.bt(775,27,25,2,"web");\n//]]></script>'
                '</body></html>')
        limpo = templates.limpar_injecoes_wayback(html)
        for residuo in ("archive.org", "__wm", "archive_analytics", "--wm-toolbar-height"):
            with self.subTest(residuo=residuo):
                self.assertNotIn(residuo, limpo)
        for legitimo in ('<script src="https://www.paypalobjects.com/web/res/app.js"></script>',
                         '<link rel="stylesheet" href="https://www.paypalobjects.com/web/res/app.css">',
                         '<form action="https://www.paypal.com/signin"></form>'):
            with self.subTest(legitimo=legitimo):
                self.assertIn(legitimo, limpo)
        self.assertEqual(templates.residuos_wayback(limpo), 0)
        self.assertGreater(templates.residuos_wayback(html), 0)


class TestDataEfetiva(unittest.TestCase):  # I3
    def test_timestamp_efetivo(self):
        casos = {
            "https://web.archive.org/web/20190102025722/https://www.paypal.com/signin": "20190102025722",
            "https://web.archive.org/web/20200101131509/https://login.live.com/cookiesDisabled.srf?x=1": "20200101131509",
            "about:blank": None,
            "https://www.paypal.com/signin": None,
        }
        for url, esperado in casos.items():
            with self.subTest(url=url):
                self.assertEqual(templates.timestamp_efetivo(url), esperado)

    def test_fora_da_janela(self):
        self.assertFalse(templates.fora_da_janela("20190102025722", [2019]))
        self.assertTrue(templates.fora_da_janela("20210615000000", [2019]))       # redirecionou 2,5 anos
        self.assertFalse(templates.fora_da_janela("20190702000000", [2019, 2020]))  # 182 e 183 dias
        self.assertTrue(templates.fora_da_janela("20190702000000", [2019, 2021]))

    def test_revisao_alerta_data_efetiva_fora_da_janela(self):
        plano = [_entrada("x/p/2020-01-01")]
        metas = {"x/p/2020-01-01": {"data_captura": "t1", "resolucoes": {
            "1280x960": {"status": "ok", "timestamp_efetivo": "20221005000000"},
            "1366x768": {"status": "ok", "timestamp_efetivo": "20221005000000"}}}}
        self.assertIn("fora da janela", templates.gerar_revisao_html(plano, metas))


class TestRevisaoDuasResolucoes(unittest.TestCase):  # I4
    def test_mostra_as_duas_miniaturas_e_destaca_falha(self):
        plano = [_entrada("x/p/2020-01-01")]
        metas = {"x/p/2020-01-01": {"data_captura": "t1", "resolucoes": {
            "1280x960": {"status": "ok"}, "1366x768": {"status": "sem_formulario"}}}}
        html = templates.gerar_revisao_html(plano, metas)
        self.assertIn("x/p/2020-01-01/shot_1280x960.png", html)
        self.assertIn("x/p/2020-01-01/shot_1366x768.png", html)
        self.assertIn('class="falha"', html)


class TestSeletorPorVariante(unittest.TestCase):  # I5
    def test_seletor_opcional(self):
        marcas = [{"entidade": "Itaú", "logins": [
            {"variante": "pessoal", "url": "https://www.itau.com.br/", "locale": "pt-BR", "seletor": "#agencia"}]}]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "marcas.json")
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(marcas, f)
            v = templates.ler_marcas(caminho)[0]
        self.assertEqual(v.seletor, "#agencia")
        self.assertIsNone(templates.ler_marcas(CAMINHO_EXEMPLO)[0].seletor)
        plano = templates.planejar_variante(v, [("20200101000000", 200)], anos=range(2020, 2021))
        self.assertEqual({e["seletor"] for e in plano}, {"#agencia"})


# Variante buscada por prefixo (ex.: Amazon): o Wayback não tem uma URL única com vários anos, só milhares
# de URLs de sessão (/ap/signin/<sessão>?openid...), e parte dos snapshots é a tela de CAPTCHA.
AMAZON = templates.VarianteLogin("Amazon", "login", "https://www.amazon.com/ap/signin", "en-US",
                                 busca="prefixo", evitar=("captcha",), exigir=("ap_email",))
U1 = "https://www.amazon.com/ap/signin/111?openid.return_to=a"
U2 = "https://www.amazon.com/ap/signin/222?openid.return_to=b"


class TestBuscaPorPrefixo(unittest.TestCase):
    def test_ler_marcas_campos_de_busca(self):
        marcas = [{"entidade": "Amazon", "logins": [
            {"variante": "login", "url": "https://www.amazon.com/ap/signin", "locale": "en-US",
             "busca": "prefixo", "evitar": ["captcha"], "exigir": ["ap_email", "name=\"email\""]}]}]
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "marcas.json")
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(marcas, f)
            v = templates.ler_marcas(caminho)[0]
        self.assertEqual((v.busca, v.evitar, v.exigir), ("prefixo", ("captcha",), ("ap_email", 'name="email"')))
        padrao = templates.ler_marcas(CAMINHO_EXEMPLO)[0]  # sem os campos: busca exata, sem filtro de conteúdo
        self.assertEqual((padrao.busca, padrao.evitar, padrao.exigir), ("exata", (), ()))

    def test_ler_marcas_recusa_busca_desconhecida(self):
        marcas = [{"entidade": "X", "logins": [{"variante": "p", "url": "https://x.com/", "locale": "en-US",
                                                "busca": "prefix"}]}]  # erro de digitação na tabela
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "marcas.json")
            with open(caminho, "w", encoding="utf-8") as f:
                json.dump(marcas, f)
            with self.assertRaises(ValueError):
                templates.ler_marcas(caminho)

    def test_html_aceitavel(self):
        ok = templates.html_aceitavel
        self.assertTrue(ok("<input id=ap_email>", evitar=("captcha",), exigir=("ap_email",)))
        self.assertFalse(ok("<input id=ap_email><img id=auth-CAPTCHA-image>", ("captcha",), ("ap_email",)))  # sem caixa
        self.assertFalse(ok("<p>Looking for something?</p>", ("captcha",), ("ap_email",)))  # falta o exigido
        self.assertTrue(ok("<input name=\"email\">", (), ("ap_email", 'name="email"')))  # basta um dos exigidos
        self.assertTrue(ok("qualquer coisa", (), ()))
        self.assertFalse(ok(None, (), ()))  # download falhou: não dá para conferir

    def test_escolhe_o_mais_proximo_que_passa_no_conteudo(self):
        caps = [("20200102000000", 200, U1), ("20200110000000", 200, U2), ("20191201000000", 200, U2)]
        vistos = []

        def aceitar(ts, url):
            vistos.append((ts, url))
            return ts != "20200102000000"  # o mais próximo é a tela de CAPTCHA

        plano = templates.planejar_variante(AMAZON, caps, anos=range(2020, 2021), aceitar=aceitar)
        e = plano[0]
        self.assertEqual((e["id"], e["timestamp"], e["url_arquivada"]), ("amazon/login/2020-01-10", "20200110000000", U2))
        self.assertEqual(e["url_login"], "https://www.amazon.com/ap/signin")  # a variante continua identificada
        self.assertEqual(vistos, [("20200102000000", U1), ("20200110000000", U2)])  # do mais próximo para o mais longe
        self.assertNotIn("url_arquivada", plano[-1])  # ao vivo usa a URL da variante

    def test_limite_de_verificacoes_vira_buraco(self):
        caps = [(f"202001{d:02d}000000", 200, U1) for d in range(1, 21)]
        chamadas = []
        plano = templates.planejar_variante(AMAZON, caps, anos=range(2020, 2021),
                                            aceitar=lambda ts, url: chamadas.append(ts) or False)
        self.assertEqual(plano[0]["buraco"], "sem_snapshot_valido")
        self.assertEqual(len(chamadas), templates.MAX_VERIFICACOES_CONTEUDO)

    def test_variante_exata_nao_muda(self):
        # o plano já revisado não pode mudar: sem url_arquivada e sem filtro de conteúdo nas variantes exatas
        plano = templates.planejar_variante(PAYPAL, [("20200101000000", 200)], anos=range(2020, 2021),
                                            aceitar=lambda ts, url: False)
        self.assertEqual(plano[0]["id"], "paypal/padrao/2020-01-01")
        self.assertNotIn("url_arquivada", plano[0])

    def test_rotulo_unico_quando_dois_snapshots_caem_no_mesmo_dia(self):
        # 2/jul/2021 fica a ~182,5 dias dos dois alvos: o das 10h é o mais próximo de 2021, o das 11h, de 2022
        caps = [("20210702100000", 200, U1), ("20210702110000", 200, U2)]
        plano = templates.planejar_variante(AMAZON, caps, anos=range(2021, 2023),
                                            aceitar=lambda ts, url: True)
        ids = [e["id"] for e in plano if e["origem"] == "wayback"]
        self.assertEqual(ids, ["amazon/login/2021-07-02", "amazon/login/2021-07-02-1100"])

    def test_mescla_e_pendentes_comparam_a_url_arquivada(self):
        antiga = {**_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"), "url_arquivada": U1}
        nova = {**_entrada("x/p/2020-01-01"), "url_arquivada": U2}  # mesmo dia e timestamp, outra URL de sessão
        self.assertIsNone(templates.mesclar_plano([nova], [antiga])[0]["aprovado"])
        with tempfile.TemporaryDirectory() as raiz:
            _escrever_meta(raiz, "x/p/2020-01-01", {**META_OK, "url_login": "https://x.com/login",
                                                    "timestamp": "20200101000000", "url_arquivada": U1})
            self.assertEqual([e["id"] for e in templates.entradas_pendentes([nova], raiz)], ["x/p/2020-01-01"])
            self.assertEqual(templates.entradas_pendentes([{**nova, "url_arquivada": U1}], raiz), [])

    def test_url_da_captura(self):
        self.assertEqual(templates.url_da_captura({"url_login": "https://a.com/x", "url_arquivada": U1}), U1)
        self.assertEqual(templates.url_da_captura({"url_login": "https://a.com/x"}), "https://a.com/x")


class TestAchadosDaRevisaoPrefixo(unittest.TestCase):
    def test_erro_de_download_nao_e_conteudo_ruim(self):
        # aceitar devolve None quando o download falhou: o ano não pode trocar em silêncio de snapshot
        caps = [("20200102000000", 200, U1), ("20200110000000", 200, U2)]
        plano = templates.planejar_variante(AMAZON, caps, anos=range(2020, 2021), aceitar=lambda ts, url: None)
        self.assertEqual(plano[0]["buraco"], "erro_conferencia")

    def test_mescla_mantem_a_variante_quando_a_conferencia_falhou(self):
        antigo = [{**_entrada("amazon/login/2020-01-02", aprovado=True, aprovado_captura="t1"),
                   "entidade": "Amazon", "variante": "login", "url_arquivada": U1}]
        novo = templates.planejar_variante(AMAZON, [("20200102000000", 200, U1), ("20210105000000", 200, U2)],
                                           anos=range(2020, 2022),
                                           aceitar=lambda ts, url: None if ts.startswith("2020") else True)
        self.assertEqual(templates.mesclar_plano(novo, antigo), antigo)

    def test_limpar_pasta_da_captura(self):
        with tempfile.TemporaryDirectory() as raiz:
            _escrever_meta(raiz, "x/p/2020-01-01", META_OK)
            pasta = templates.pasta_entrada(raiz, "x/p/2020-01-01")
            with open(os.path.join(pasta, "outro.txt"), "w") as f:
                f.write("x")
            templates.limpar_pasta_captura(pasta)
            self.assertEqual(os.listdir(pasta), ["outro.txt"])  # só os arquivos da captura saem
            templates.limpar_pasta_captura(os.path.join(raiz, "nao", "existe"))  # pasta nova: nada a fazer

    def test_ler_marcas_valida_evitar_e_exigir(self):
        casos = [{"busca": "prefixo", "exigir": "ap_email"},        # string em vez de lista: aceitaria tudo
                 {"busca": "prefixo", "evitar": [1]},               # não é texto
                 {"evitar": ["captcha"]}]                           # filtro numa busca exata seria ignorado
        for extra in casos:
            marcas = [{"entidade": "X", "logins": [{"variante": "p", "url": "https://x.com/", "locale": "en-US",
                                                    **extra}]}]
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as pasta:
                caminho = os.path.join(pasta, "marcas.json")
                with open(caminho, "w", encoding="utf-8") as f:
                    json.dump(marcas, f)
                with self.assertRaises(ValueError):
                    templates.ler_marcas(caminho)

    def test_data_da_captura_so_se_for_deste_snapshot(self):
        e = {**_entrada("x/p/2020-01-01"), "url_arquivada": U2}
        with tempfile.TemporaryDirectory() as raiz:
            _escrever_meta(raiz, "x/p/2020-01-01", {**META_OK, "url_login": "https://x.com/login",
                                                    "timestamp": "20200101000000", "url_arquivada": U1,
                                                    "data_captura": "t1"})
            self.assertIsNone(templates.data_captura_valida(raiz, e))  # meta de outra URL de sessão
            self.assertEqual(templates.data_captura_valida(raiz, {**e, "url_arquivada": U1}), "t1")


def _extra_completo(raiz, id_, data_captura, resolucao="1920x1080", status="ok", url_login="https://x.com/login",
                    timestamp="20200101000000", com_arquivos=True):
    """Grava extra_<resolucao>.json (e, por padrão, o screenshot e o DOM dessa resolução)."""
    pasta = os.path.join(raiz, *id_.split("/"))
    os.makedirs(pasta, exist_ok=True)
    meta = {"url_login": url_login, "timestamp": timestamp, "data_captura": data_captura, "status": status}
    with open(templates.meta_extra_caminho(raiz, id_, resolucao), "w", encoding="utf-8") as f:
        json.dump(meta, f)
    for nome in (templates.arquivos_extra(resolucao) if com_arquivos else []):
        with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
            f.write("x")


class TestResolucoesExtras(unittest.TestCase):
    R = "1920x1080"

    def test_extras_nao_mexem_nas_aprovacoes_existentes(self):
        # a resolução nova não entra na captura principal: as aprovações de hoje continuam válidas
        self.assertNotIn(self.R, templates.RESOLUCOES)
        self.assertIn(self.R, templates.RESOLUCOES_EXTRAS)
        self.assertNotIn(f"shot_{self.R}.png", templates.ARQUIVOS_CAPTURA)
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1")]
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2020-01-01", "t1")
            self.assertEqual(len(templates.entradas_aprovadas(plano, raiz)), 1)
            self.assertEqual(templates.entradas_pendentes(plano, raiz), [])

    def test_extras_pendentes_so_de_aprovadas(self):
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),   # sem extra: pendente
                 _entrada("x/p/2021-01-01", aprovado=True, aprovado_captura="t1",
                          timestamp="20210101000000"),                                # extra ok: não
                 _entrada("x/p/2022-01-01", aprovado=True, aprovado_captura="t1",
                          timestamp="20220101000000"),                                # extra sem_formulario: sim
                 _entrada("x/p/2023-01-01", aprovado=False),                          # rejeitada: não
                 _entrada("x/p/2024-01-01", aprovado=None)]                           # a revisar: não
        with tempfile.TemporaryDirectory() as raiz:
            for id_, ts in (("x/p/2020-01-01", "20200101000000"), ("x/p/2021-01-01", "20210101000000"),
                            ("x/p/2022-01-01", "20220101000000")):
                _captura_completa(raiz, id_, "t1", timestamp=ts)
            _extra_completo(raiz, "x/p/2021-01-01", "t2", timestamp="20210101000000")
            _extra_completo(raiz, "x/p/2022-01-01", "t2", timestamp="20220101000000", status="sem_formulario")
            pendentes = [e["id"] for e in templates.extras_pendentes(plano, raiz, self.R)]
            self.assertEqual(pendentes, ["x/p/2020-01-01", "x/p/2022-01-01"])
            # com decisão na resolução extra, não é recapturada
            templates.marcar_aprovacao_extra(plano, "x/p/2022-01-01", self.R, False, "layout quebrado")
            self.assertEqual([e["id"] for e in templates.extras_pendentes(plano, raiz, self.R)], ["x/p/2020-01-01"])

    def test_aprovacao_extra_presa_a_captura(self):
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1")]
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2020-01-01", "t1")
            _extra_completo(raiz, "x/p/2020-01-01", "t2")
            self.assertEqual(templates.data_captura_extra_valida(raiz, plano[0], self.R), "t2")
            templates.marcar_aprovacao_extra(plano, "x/p/2020-01-01", self.R, True, data_captura="t2")
            self.assertIn((plano[0]["id"], self.R), [(e["id"], r) for e, r in templates.templates_aprovados(plano, raiz)])
            _extra_completo(raiz, "x/p/2020-01-01", "t3")  # recapturada depois da aprovação
            self.assertNotIn(self.R, [r for _, r in templates.templates_aprovados(plano, raiz)])
            # extra de outro snapshot não conta como vista
            _extra_completo(raiz, "x/p/2020-01-01", "t4", timestamp="20200105000000")
            self.assertIsNone(templates.data_captura_extra_valida(raiz, plano[0], self.R))

    def test_templates_aprovados_pares(self):
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),
                 _entrada("x/p/2021-01-01", aprovado=True, aprovado_captura="t1", timestamp="20210101000000"),
                 _entrada("x/p/2022-01-01", aprovado=False)]
        with tempfile.TemporaryDirectory() as raiz:
            _captura_completa(raiz, "x/p/2020-01-01", "t1")
            _captura_completa(raiz, "x/p/2021-01-01", "t1", timestamp="20210101000000")
            _extra_completo(raiz, "x/p/2020-01-01", "t2")
            _extra_completo(raiz, "x/p/2021-01-01", "t2", timestamp="20210101000000")
            templates.marcar_aprovacao_extra(plano, "x/p/2020-01-01", self.R, True, data_captura="t2")
            templates.marcar_aprovacao_extra(plano, "x/p/2021-01-01", self.R, False, "layout quebrado", "t2")
            pares = sorted((e["id"], r) for e, r in templates.templates_aprovados(plano, raiz))
        self.assertEqual(pares, [("x/p/2020-01-01", "1280x960"), ("x/p/2020-01-01", "1366x768"),
                                 ("x/p/2020-01-01", self.R),
                                 ("x/p/2021-01-01", "1280x960"), ("x/p/2021-01-01", "1366x768")])

    def test_mescla_herda_extras_so_no_mesmo_snapshot(self):
        extras = {self.R: {"aprovado": True, "motivo": "", "aprovado_captura": "t2"}}
        antigo = [{**_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"), "extras": extras},
                  {**_entrada("x/p/2021-01-01", aprovado=True, aprovado_captura="t1"), "extras": extras}]
        novo = [_entrada("x/p/2020-01-01"), _entrada("x/p/2021-01-01", timestamp="20210102000000")]
        m = {e["id"]: e for e in templates.mesclar_plano(novo, antigo)}
        self.assertEqual(m["x/p/2020-01-01"]["extras"], extras)
        self.assertNotIn("extras", m["x/p/2021-01-01"])

    def test_revisao_extra_html(self):
        plano = [{**_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"),
                  "extras": {self.R: {"aprovado": False, "motivo": "layout <quebrado>", "aprovado_captura": "t2"}}},
                 _entrada("x/p/2021-01-01", aprovado=False, timestamp="20210101000000")]
        plano[1]["anos_alvo"] = [2021]
        metas = {"x/p/2020-01-01": {"status": "sem_formulario", "data_captura": "t2"}}
        html = templates.gerar_revisao_extra_html(plano, metas, self.R)
        self.assertIn(f"x/p/2020-01-01/shot_{self.R}.png", html)
        self.assertIn("sem_formulario", html)
        self.assertIn("layout &lt;quebrado&gt;", html)           # motivo escapado
        self.assertNotIn(f"x/p/2021-01-01/shot_{self.R}", html)  # entrada não aprovada: sem resolução extra
        self.assertIn("rejeitar --resolucao", html)

    def test_marcar_extra_recusas(self):
        plano = [_entrada("x/p/2020-01-01", aprovado=True, aprovado_captura="t1"), _entrada("x/p/2021-01-01"),
                 _entrada("x/p/buraco-2022", buraco="sem_snapshot", timestamp=None)]
        with self.assertRaises(ValueError):  # resolução que não é extra
            templates.marcar_aprovacao_extra(plano, "x/p/2020-01-01", "1366x768", True, data_captura="t2")
        with self.assertRaises(ValueError):  # aprovar o que não foi capturado
            templates.marcar_aprovacao_extra(plano, "x/p/2020-01-01", self.R, True)
        with self.assertRaises(ValueError):  # a entrada principal ainda não foi aprovada
            templates.marcar_aprovacao_extra(plano, "x/p/2021-01-01", self.R, True, data_captura="t2")
        with self.assertRaises(ValueError):
            templates.marcar_aprovacao_extra(plano, "x/p/buraco-2022", self.R, False, "x")
        with self.assertRaises(KeyError):
            templates.marcar_aprovacao_extra(plano, "x/p/2099-01-01", self.R, False, "x")


class TestLinhaDeComandoExtras(unittest.TestCase):
    def test_subcomandos_da_resolucao_extra(self):
        import importlib.util
        caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", "capturar_templates.py")
        spec = importlib.util.spec_from_file_location("capturar_templates_cli", caminho)
        modulo = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(modulo)
        p = modulo.criar_parser()
        base = ["--plano", "p.json", "--raiz", "r"]
        a = p.parse_args(["capturar-extra", *base, "--resolucao", "1920x1080", "--so", "x/p/2020-01-01"])
        self.assertEqual((a.func, a.resolucao, a.so), (modulo.cmd_capturar_extra, "1920x1080", ["x/p/2020-01-01"]))
        self.assertEqual(p.parse_args(["revisar", *base, "--resolucao", "1920x1080"]).resolucao, "1920x1080")
        self.assertIsNone(p.parse_args(["revisar", *base]).resolucao)  # sem a opção: revisão principal
        self.assertEqual(p.parse_args(["aprovar", *base, "--resolucao", "1920x1080", "a", "b"]).ids, ["a", "b"])
        a = p.parse_args(["rejeitar", *base, "--resolucao", "1920x1080", "a", "--motivo", "m"])
        self.assertEqual((a.resolucao, a.motivo), ("1920x1080", "m"))
        with self.assertRaises(SystemExit):  # só resoluções extras
            p.parse_args(["capturar-extra", *base, "--resolucao", "1366x768"])


class TestDownloadComMuitosCabecalhos(unittest.TestCase):
    def test_limite_de_cabecalhos_aumentado(self):
        # Algumas respostas do Wayback (ex.: facebook.com/index.php de 2022) trazem mais de 100 cabeçalhos;
        # o http.client recusa acima de 100 ("got more than 100 headers") e o HTML original não era salvo.
        import http.client
        import importlib.util
        caminho = os.path.join(os.path.dirname(__file__), "..", "scripts", "capturar_templates.py")
        spec = importlib.util.spec_from_file_location("capturar_templates", caminho)
        spec.loader.exec_module(importlib.util.module_from_spec(spec))
        self.assertGreaterEqual(http.client._MAXHEADERS, 1000)


if __name__ == "__main__":
    unittest.main()
