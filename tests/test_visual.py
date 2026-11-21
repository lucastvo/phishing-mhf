import os
import sys
import tempfile
import unittest

from PIL import Image, ImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import visual  # noqa: E402


def _pagina(largura, altura, cor=(255, 255, 255), caixa=(0, 90, 200)):
    """Imagem sintética: fundo, um cabeçalho e uma "caixa de login" centralizada."""
    img = Image.new("RGB", (largura, altura), cor)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, largura, altura // 10], fill=(30, 30, 30))
    d.rectangle([largura // 3, altura // 4, 2 * largura // 3, altura // 2], fill=caixa)
    return img


class TestClasseDeTela(unittest.TestCase):
    def test_classe_de_tela(self):
        casos = {1280: "1280x960", 1366: "1366x768", 1920: "1920x1080",
                 800: "1280x960",    # 800x600 do Phishpedia: 4:3, sem template desse tamanho
                 997: "1280x960", 1374: "1366x768", 1381: "1366x768", 1600: "1366x768", 1700: "1920x1080"}
        for largura, esperado in casos.items():
            with self.subTest(largura=largura):
                self.assertEqual(visual.classe_de_tela(largura), esperado)


class TestPrimeiraDobra(unittest.TestCase):
    def test_primeira_dobra_pagina_inteira(self):
        img = Image.new("RGB", (1366, 85000), "white")  # captura de página inteira do Phishpedia benign
        self.assertEqual(visual.primeira_dobra(img, "1366x768").size, (1366, 768))

    def test_primeira_dobra_proporcional_a_largura(self):
        # largura fora do padrão: a altura segue a proporção da classe
        self.assertEqual(visual.primeira_dobra(Image.new("RGB", (1374, 3000)), "1366x768").size, (1374, 772))  # 772,497
        self.assertEqual(visual.primeira_dobra(Image.new("RGB", (800, 600)), "1280x960").size, (800, 600))

    def test_primeira_dobra_imagem_menor(self):
        img = Image.new("RGB", (1280, 467))  # mais baixa que a dobra: usada como está
        self.assertEqual(visual.primeira_dobra(img, "1280x960").size, (1280, 467))


class TestHashPerceptual(unittest.TestCase):
    def test_phash_tamanhos_e_identidade(self):
        img = _pagina(1366, 768)
        h64, h256 = visual.phash(img), visual.phash(img, bits=256)
        self.assertEqual((len(h64), len(h256)), (16, 64))  # hexadecimal
        self.assertEqual(visual.sim_hash(h64, visual.phash(img.copy())), 1.0)
        with self.assertRaises(ValueError):
            visual.phash(img, bits=100)

    def test_sim_hash_ordena_por_semelhanca(self):
        base = _pagina(1366, 768)
        parecida = _pagina(1366, 768, caixa=(0, 100, 210))    # mesma página, cor um pouco diferente
        diferente = Image.new("RGB", (1366, 768), (20, 20, 20))
        ImageDraw.Draw(diferente).ellipse([100, 300, 600, 700], fill=(250, 250, 0))
        h = visual.phash(base)
        self.assertGreater(visual.sim_hash(h, visual.phash(parecida)), visual.sim_hash(h, visual.phash(diferente)))
        with self.assertRaises(ValueError):  # hashes de tamanhos diferentes não se comparam
            visual.sim_hash(h, visual.phash(base, bits=256))


class TestEmbedder(unittest.TestCase):
    # pesos=False: rede com pesos aleatórios (semente fixa), para testar sem rede e sem baixar pesos
    def test_embedding_dimensao_e_norma(self):
        import numpy as np
        for modelo, dim in (("small", 576), ("large", 960)):
            with self.subTest(modelo=modelo):
                emb = visual.Embedder(modelo, pesos=False)
                v = emb.embed(_pagina(1366, 768))
                self.assertEqual((emb.dim, v.shape, v.dtype), (dim, (dim,), np.float32))
                self.assertAlmostEqual(float(np.linalg.norm(v)), 1.0, places=5)

    def test_embedding_deterministico(self):
        img = _pagina(1280, 960)
        a = visual.Embedder("small", pesos=False).embed(img)
        b = visual.Embedder("small", pesos=False).embed(img)  # outra instância, mesma semente
        self.assertAlmostEqual(visual.cosseno(a, b), 1.0, places=5)
        self.assertAlmostEqual(visual.cosseno(a, a), 1.0, places=5)

    def test_modelo_desconhecido(self):
        with self.assertRaises(ValueError):
            visual.Embedder("medium", pesos=False)


class TestAbrirImagem(unittest.TestCase):
    def test_png_truncado_abre(self):
        with tempfile.TemporaryDirectory() as pasta:
            caminho = os.path.join(pasta, "shot.png")
            _pagina(400, 300).save(caminho)
            with open(caminho, "rb") as f:
                dados = f.read()
            with open(caminho, "wb") as f:  # bloco final corrompido, como em alguns PNGs do Phish360
                f.write(dados[: len(dados) - 40])
            img = visual.abrir_imagem(caminho)
            self.assertEqual((img.mode, img.size), ("RGB", (400, 300)))

    def test_transparencia_composta_sobre_branco(self):
        # Capturas RGBA do Phishpedia têm áreas transparentes com RGB = 0. Descartar o alfa deixaria essas
        # áreas pretas; o navegador mostra a página sobre fundo branco.
        rgba = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
        ImageDraw.Draw(rgba).rectangle([0, 0, 49, 49], fill=(255, 0, 0, 255))
        ImageDraw.Draw(rgba).rectangle([50, 0, 74, 49], fill=(0, 0, 0, 128))  # meio transparente
        paleta = Image.new("P", (20, 20), 0)
        paleta.putpalette([0, 0, 0, 0, 0, 255] + [0] * 762)
        ImageDraw.Draw(paleta).rectangle([0, 0, 9, 19], fill=1)
        with tempfile.TemporaryDirectory() as pasta:
            rgba.save(os.path.join(pasta, "rgba.png"))
            paleta.save(os.path.join(pasta, "p.png"), transparency=0)  # índice 0 transparente
            img = visual.abrir_imagem(os.path.join(pasta, "rgba.png"))
            self.assertEqual(img.mode, "RGB")
            self.assertEqual(img.getpixel((10, 10)), (255, 0, 0))       # opaco: intacto
            self.assertEqual(img.getpixel((90, 10)), (255, 255, 255))   # transparente: branco, não preto
            self.assertTrue(all(120 <= c <= 135 for c in img.getpixel((60, 10))))  # meio a meio
            img_p = visual.abrir_imagem(os.path.join(pasta, "p.png"))
            self.assertEqual((img_p.getpixel((5, 5)), img_p.getpixel((15, 5))), ((0, 0, 255), (255, 255, 255)))


class TestComparar(unittest.TestCase):
    def test_comparar_devolve_componentes_separados(self):
        import numpy as np
        v1 = {"h": "0" * 16, "e": np.array([1.0, 0.0], np.float32)}
        v2 = {"h": "0" * 15 + "f", "e": np.array([0.0, 1.0], np.float32)}
        self.assertEqual(visual.comparar(v1, v1), {"sim_h": 1.0, "cos_e": 1.0})
        r = visual.comparar(v1, v2)
        self.assertEqual(r["sim_h"], 1 - 4 / 64)   # 4 bits diferentes em 64
        self.assertAlmostEqual(r["cos_e"], 0.0)


if __name__ == "__main__":
    unittest.main()
