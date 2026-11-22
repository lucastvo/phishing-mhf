"""Testes dos exemplos da interface (etapa 7): rótulo real, páginas dos datasets e tipos de candidato."""

import csv
import io
import json
import os
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import divisao, exemplos  # noqa: E402

CAMPOS_INDICE = ["id", "rotulo", "marca", "url", "caminho_shot", "caminho_html", "html_util", "shot_ok"]


def montar_dataset(d, nome="ds", linhas=None, conjunto="teste"):
    """Índice CSV, capturas e HTMLs sintéticos + divisão. Devolve (indice, raiz, caminho_divisao)."""
    raiz = os.path.join(d, nome)
    os.makedirs(raiz, exist_ok=True)
    linhas = linhas or [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.", "estrato": "PayPal",
                         "url": "http://golpe.test/", "html_util": "1"}]
    indice = os.path.join(d, f"{nome}.csv")
    div = []
    with open(indice, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INDICE)
        w.writeheader()
        for l in linhas:
            Image.new("RGB", (1366, 3000), "white").save(os.path.join(raiz, f"{l['id']}.png"))
            if l["html_util"] == "1":
                with open(os.path.join(raiz, f"{l['id']}.html"), "w", encoding="utf-8") as h:
                    h.write("<html><body><form><input type=password></form></body></html>")
            w.writerow({"id": l["id"], "rotulo": l["rotulo"], "marca": l["marca"], "url": l["url"],
                        "caminho_shot": f"{l['id']}.png", "caminho_html": f"{l['id']}.html",
                        "html_util": l["html_util"], "shot_ok": "1"})
            div.append({"dataset": nome, "id": l["id"], "conjunto": l.get("conjunto", conjunto), "dobra": -1,
                        "grupo": f"a:{nome}:{l['id']}", "estrato": l["estrato"]})
    caminho_div = os.path.join(d, "divisao.csv")
    divisao.gravar_divisao(caminho_div, div)
    return indice, raiz, caminho_div


def gravar_config(d, itens):
    caminho = os.path.join(d, "exemplos.json")
    with open(caminho, "w", encoding="utf-8") as f:
        json.dump({"exemplos": itens, "urls_sugeridas": [{"titulo": "X", "url": "https://x.test/"}]}, f)
    return caminho


class TestRotuloReal(unittest.TestCase):
    def test_situacao_real(self):
        casos = [("Microsoft", "phishing", "Microsoft", False, "acertou"),
                 ("Microsoft", "phishing", "PayPal", False, "marca_errada"),
                 ("Microsoft", "legitima", "Microsoft", False, "errou"),
                 ("benigno", "legitima", "PayPal", False, "acertou"),
                 ("benigno", "phishing", "PayPal", False, "errou"),
                 ("sem_marca", "phishing", "PayPal", False, "marca_desconhecida"),
                 ("fora", "phishing", "PayPal", False, "marca_desconhecida"),
                 ("fora", "legitima", "PayPal", False, "errou"),
                 ("sem_marca", "legitima", None, False, "errou"),
                 ("Microsoft", "phishing", "Microsoft", True, "sem_comparacao"),
                 ("benigno", "legitima", "PayPal", True, "sem_comparacao")]
        for estrato, rotulo, entidade, simulado, esperado in casos:
            self.assertEqual(exemplos.situacao_real(estrato, rotulo, entidade, simulado), esperado,
                             (estrato, rotulo, entidade, simulado))

    def test_texto_e_frase(self):
        self.assertEqual(exemplos.texto_real("Microsoft", "Microsoft OneDrive"),
                         "phishing de Microsoft (rótulo do dataset: Microsoft OneDrive)")
        self.assertEqual(exemplos.texto_real("PayPal", "PayPal"), "phishing de PayPal")
        self.assertEqual(exemplos.texto_real("fora", "AT&T"), "phishing de marca fora da base (AT&T)")
        self.assertEqual(exemplos.texto_real("sem_marca", ""), "phishing (o dataset não informa a marca)")
        self.assertEqual(exemplos.texto_real("benigno", ""), "legítima")
        self.assertEqual(exemplos.frase_situacao("acertou", "PayPal", "PayPal"), "✓ acertou")
        self.assertEqual(exemplos.frase_situacao("errou", "benigno", None), "✗ errou: alerta falso")
        self.assertEqual(exemplos.frase_situacao("errou", "PayPal", "PayPal"), "✗ errou: phishing não detectado")
        self.assertEqual(exemplos.frase_situacao("marca_errada", "Microsoft", "Microsoft"),
                         "✗ detectou o phishing, mas errou a marca (real: Microsoft)")
        self.assertEqual(exemplos.frase_situacao("marca_desconhecida", "sem_marca", None),
                         "detectado como phishing; o dataset não informa a marca")
        self.assertEqual(exemplos.frase_situacao("marca_desconhecida", "fora", None),
                         "detectado como phishing; a marca real está fora da base")
        self.assertEqual(exemplos.frase_situacao("sem_comparacao", "PayPal", "PayPal"),
                         "domínio simulado: a página foi tirada do lugar dela, então não há rótulo real para comparar")


class TestCandidatos(unittest.TestCase):
    def test_tipo_do_candidato(self):
        t = exemplos.tipo_do_candidato
        self.assertEqual(t("PayPal", "phishing", "PayPal", "phishing", False), "phishing_marca_certa")
        self.assertEqual(t("PayPal", "phishing", "Netflix", "phishing", False), "phishing_marca_errada")
        self.assertEqual(t("PayPal", "legitima", "PayPal", "abaixo_do_limiar", True), "phishing_nao_detectado_sem_dom")
        self.assertEqual(t("sem_marca", "legitima", "PayPal", "abaixo_do_limiar", True), "phishing_nao_detectado_sem_dom")
        self.assertEqual(t("PayPal", "legitima", "PayPal", "abaixo_do_limiar", False), "phishing_nao_detectado")
        self.assertEqual(t("fora", "legitima", "PayPal", "abaixo_do_limiar", False), "phishing_sem_marca_nao_detectado")
        self.assertEqual(t("sem_marca", "phishing", "PayPal", "phishing", False), "phishing_sem_marca_detectado")
        self.assertEqual(t("benigno", "legitima", "PayPal", "dominio_legitimo_estagio2", False),
                         "legitima_dominio_oficial")
        self.assertEqual(t("benigno", "legitima", "PayPal", "abaixo_do_limiar", True), "legitima_sem_dom")
        self.assertEqual(t("benigno", "legitima", "PayPal", "abaixo_do_limiar", False), "legitima_comum")
        self.assertEqual(t("benigno", "phishing", "PayPal", "phishing", False), "alerta_falso")

    def test_folha_de_contato(self):
        itens = []
        for tam in ((1366, 768), (1280, 960), (1920, 1080)):
            buf = io.BytesIO()
            Image.new("RGB", tam, "white").save(buf, format="PNG")
            itens.append({"imagem": buf.getvalue(), "legenda": "1 · phishing de PayPal (0,991)"})
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "folha.jpg")
            exemplos.folha_de_contato(itens, saida)
            with Image.open(saida) as img:
                self.assertEqual(img.format, "JPEG")
                self.assertEqual(img.width, 4 * 400)


class TestPaginasDosDatasets(unittest.TestCase):
    def test_ler_pagina_recorta_a_dobra(self):
        with tempfile.TemporaryDirectory() as d:
            indice, raiz, _ = montar_dataset(d, linhas=[
                {"id": "p0", "rotulo": "benigno", "marca": "", "estrato": "benigno", "url": "", "html_util": "0"}])
            with open(indice, encoding="utf-8") as f:
                linha = next(csv.DictReader(f))
            p = exemplos.ler_pagina_do_dataset(linha, raiz, "1366x768")
            with Image.open(io.BytesIO(p["imagem"])) as img:
                self.assertEqual(img.size, (1366, 768))
            self.assertIsNone(p["html"])
            self.assertEqual(p["url"], "p0")  # sem URL no índice: o id (o domínio, no Phishpedia benign)
            self.assertEqual(p["classe"], "1366x768")

    def test_datasets_ida_e_volta(self):
        with tempfile.TemporaryDirectory() as d:
            caminho = os.path.join(d, "sub", "datasets.json")
            ds = {"phish360": {"indice": "a.csv", "raiz": "r", "classe": None}}
            exemplos.gravar_datasets(caminho, ds)
            self.assertEqual(exemplos.ler_datasets(caminho), ds)

    def _ler(self, d, linhas, itens=None, apagar=None):
        indice, raiz, caminho_div = montar_dataset(d, linhas=linhas)
        if apagar:
            os.remove(os.path.join(raiz, apagar))
        caminho_ds = os.path.join(d, "datasets.json")
        exemplos.gravar_datasets(caminho_ds, {"ds": {"indice": indice, "raiz": raiz, "classe": "1366x768"}})
        itens = itens or [{"dataset": "ds", "id": l["id"], "grupo": "acerto", "titulo": "T", "nota": "N"}
                          for l in linhas]
        return exemplos.ler_exemplos(gravar_config(d, itens), caminho_ds, divisao.ler_divisao(caminho_div))

    def test_exemplo_disponivel(self):
        with tempfile.TemporaryDirectory() as d:
            lista, urls = self._ler(d, [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.",
                                         "estrato": "PayPal", "url": "http://golpe.test/", "html_util": "1"}])
            self.assertEqual(urls, [{"titulo": "X", "url": "https://x.test/"}])
            e = lista[0]
            self.assertEqual((e.numero, e.dataset, e.id, e.grupo, e.estrato, e.marca_dataset, e.classe),
                             (1, "ds", "p0", "acerto", "PayPal", "PayPal Inc.", "1366x768"))
            self.assertTrue(e.disponivel, e.motivo)

    def test_exemplo_indisponivel_quando_arquivo_some(self):
        with tempfile.TemporaryDirectory() as d:
            lista, _ = self._ler(d, [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.", "estrato": "PayPal",
                                      "url": "http://golpe.test/", "html_util": "1"}], apagar="p0.png")
            self.assertFalse(lista[0].disponivel)
            self.assertIn("p0.png", lista[0].motivo)

    def test_exemplo_sem_html_quando_deveria_ter(self):
        with tempfile.TemporaryDirectory() as d:
            lista, _ = self._ler(d, [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.", "estrato": "PayPal",
                                      "url": "http://golpe.test/", "html_util": "1"}], apagar="p0.html")
            self.assertFalse(lista[0].disponivel)
            self.assertIn("p0.html", lista[0].motivo)

    def test_exemplo_fora_do_teste_indisponivel(self):
        with tempfile.TemporaryDirectory() as d:
            lista, _ = self._ler(d, [{"id": "p0", "rotulo": "phishing", "marca": "PayPal Inc.", "estrato": "PayPal",
                                      "url": "http://golpe.test/", "html_util": "1",
                                      "conjunto": "desenvolvimento"}])
            self.assertFalse(lista[0].disponivel)
            self.assertIn("teste", lista[0].motivo)

    def test_exemplo_id_desconhecido(self):
        with tempfile.TemporaryDirectory() as d:
            linhas = [{"id": "p0", "rotulo": "benigno", "marca": "", "estrato": "benigno", "url": "",
                       "html_util": "0"}]
            lista, _ = self._ler(d, linhas, itens=[{"dataset": "ds", "id": "nao_existe", "grupo": "erro",
                                                    "titulo": "T", "nota": "N"},
                                                   {"dataset": "outro", "id": "p0", "grupo": "erro",
                                                    "titulo": "T", "nota": "N"}])
            self.assertFalse(lista[0].disponivel)
            self.assertIn("nao_existe", lista[0].motivo)
            self.assertFalse(lista[1].disponivel)
            self.assertIn("outro", lista[1].motivo)

    def test_sem_datasets_json(self):
        with tempfile.TemporaryDirectory() as d:
            config = gravar_config(d, [{"dataset": "ds", "id": "p0", "grupo": "acerto", "titulo": "T", "nota": "N"}])
            lista, _ = exemplos.ler_exemplos(config, os.path.join(d, "nao_existe.json"), {})
            self.assertFalse(lista[0].disponivel)
            self.assertEqual(lista[0].motivo, "data/interface/datasets.json não existe; gere com "
                                              "scripts/escolher_exemplos.py (README, passo 7)")


if __name__ == "__main__":
    unittest.main()
