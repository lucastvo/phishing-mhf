"""
Servidor local da interface (etapa 7): junta o detector, os exemplos, a captura ao vivo e a apresentação, e
atende a página em src/mhf/web/. Só em 127.0.0.1.

Cada conexão tem sua thread (os navegadores abrem conexões antes de precisar; num servidor sem threads, uma
conexão ociosa prenderia as outras), mas toda chamada à Aplicação passa por um único trabalhador: as análises
saem uma por vez, e o Playwright, cuja API síncrona fica presa à thread que o iniciou, é sempre usado na mesma.

Desenho: docs/especificacoes/2026-11-22-interface.md, seções 5 e 15.
"""

import io
import json
import os
import sys
import traceback
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from mhf import apresentacao, captura, exemplos, visual

AVISO_URL = ("O navegador vai abrir a página de verdade. Não cole links suspeitos reais; para ver phishing, "
             "use os exemplos.")
CLASSE_PADRAO = "1366x768"
RAIZ_WEB = os.path.join(os.path.dirname(__file__), "web")
ESTATICOS = {"index.html": "text/html; charset=utf-8", "estilo.css": "text/css; charset=utf-8",
             "app.js": "text/javascript; charset=utf-8"}
NOMES_MODELOS = {"boosting": "gradient boosting", "floresta": "Random Forest", "regressao": "regressão logística"}


class Aplicacao:
    """O que a interface faz, sem HTTP: estado, análise de exemplo, análise de URL e imagens dos templates."""

    def __init__(self, detector, embedder, tabela, raiz_templates, exemplos_, urls_sugeridas, navegador=None):
        self.detector, self.embedder, self.tabela = detector, embedder, tabela
        self.raiz_templates, self.exemplos, self.urls_sugeridas = raiz_templates, exemplos_, urls_sugeridas
        self.navegador = navegador
        self._itens = {it["id"]: it for it in detector.base.itens}

    def estado(self) -> dict:
        tipo = getattr(self.detector.modelo, "tipo", "")
        return {"modelo": NOMES_MODELOS.get(tipo, tipo), "tau": float(self.detector.tau),
                "templates": len(self.detector.base.itens),
                "marcas": len({it["entidade"] for it in self.detector.base.itens}),
                "classes": list(visual.CLASSES_TELA), "classe_padrao": CLASSE_PADRAO, "idiomas": list(captura.IDIOMAS),
                "exemplos": [{"numero": e.numero, "grupo": e.grupo, "titulo": e.titulo, "disponivel": e.disponivel,
                              "motivo": e.motivo} for e in self.exemplos],
                "urls_sugeridas": self.urls_sugeridas, "navegador": self.navegador is not None,
                "aviso_url": AVISO_URL}

    def _analisar(self, imagem, html, url, classe, simulado, exemplo=None, pagina=None):
        v = self.detector.analisar_pagina(io.BytesIO(imagem), html, url, classe=classe, embedder=self.embedder,
                                          detalhes=True)
        return apresentacao.montar_resultado(v, self.detector.tau, self.detector.base, self.tabela, url, simulado,
                                             exemplo=exemplo, pagina=pagina)

    def analisar_exemplo(self, numero, url_simulada=None) -> dict:
        if isinstance(numero, bool) or not isinstance(numero, int):
            raise ValueError("informe o número do exemplo")
        e = next((x for x in self.exemplos if x.numero == numero), None)
        if e is None:
            raise ValueError(f"não há exemplo {numero}")
        if not e.disponivel:
            raise ValueError(f"o exemplo {numero} não está disponível: {e.motivo}")
        url_sim = captura.normalizar_url(url_simulada) if url_simulada else None
        try:
            p = exemplos.ler_pagina_do_dataset(e.linha, e.raiz, e.classe)
        except OSError as erro:
            raise ValueError(f"não foi possível ler o exemplo {numero} (quarentena do antivírus?): {erro}") from erro
        return self._analisar(p["imagem"], p["html"], url_sim or p["url"], e.classe, bool(url_sim), exemplo=e)

    def analisar_url(self, url, classe, idioma, url_simulada=None) -> dict:
        if self.navegador is None:
            raise ValueError("a análise por URL está desligada (--sem-navegador)")
        if classe not in visual.CLASSES_TELA:
            raise ValueError(f"tamanho de tela desconhecido: {classe}")
        if idioma not in captura.IDIOMAS:
            raise ValueError(f"idioma desconhecido: {idioma}")
        url = captura.normalizar_url(url)
        url_sim = captura.normalizar_url(url_simulada) if url_simulada else None
        p = self.navegador.capturar(url, classe, idioma)
        url_analisada = url_sim or p.url_final
        return self._analisar(p.imagem, p.html, url_analisada, classe, bool(url_sim), pagina=p)

    def imagem_template(self, id_template) -> bytes:
        item = self._itens.get(id_template)
        if item is None:
            raise ValueError("template desconhecido")
        caminho = os.path.join(self.raiz_templates, *item["id"].split("@")[0].split("/"), f"shot_{item['classe']}.png")
        try:
            with open(caminho, "rb") as f:
                return f.read()
        except OSError as erro:
            raise ValueError(f"captura do template não encontrada: {caminho}") from erro

    def fechar(self):
        if self.navegador is not None:
            self.navegador.fechar()


class ServidorInterface(ThreadingHTTPServer):
    """Uma thread por conexão; as chamadas à Aplicação vão para um único trabalhador (executar)."""
    daemon_threads = True
    allow_reuse_address = False  # no Windows, SO_REUSEADDR deixaria duas interfaces na mesma porta sem erro

    def __init__(self, endereco, manipulador, app):
        super().__init__(endereco, manipulador)
        self.app = app
        self.trabalhador = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mhf-analise")

    def executar(self, funcao):
        return self.trabalhador.submit(funcao).result()

    def encerrar(self):
        """Fecha o navegador automatizado (na thread que o abriu), o trabalhador e o socket."""
        try:
            self.executar(self.app.fechar)
        finally:
            self.trabalhador.shutdown(wait=True)
            self.server_close()


def criar_servidor(app, porta=8000, host="127.0.0.1"):
    """ServidorInterface com as rotas da interface. Porta ocupada → OSError."""

    class Manipulador(BaseHTTPRequestHandler):
        timeout = 30  # conexão ociosa é fechada depois disso (cada uma tem sua thread)

        def log_message(self, formato, *args):  # silencioso: o terminal fica para os avisos
            pass

        def _responder(self, status, corpo, tipo):
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(corpo)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(corpo)

        def _json(self, status, dados):
            self._responder(status, json.dumps(dados, ensure_ascii=False, allow_nan=False).encode("utf-8"),
                            "application/json; charset=utf-8")

        def _tratar(self, funcao):
            """Executa `funcao` no trabalhador único e responde com o JSON dela, ou com o erro."""
            try:
                self._json(200, self.server.executar(funcao))
            except captura.ErroCaptura as erro:
                self._json(502, {"erro": str(erro)})
            except ValueError as erro:
                self._json(400, {"erro": str(erro)})
            except Exception as erro:  # noqa: BLE001 — a demonstração não pode cair por uma página
                traceback.print_exc(file=sys.stderr)
                self._json(500, {"erro": f"erro interno: {erro}"})

        def _estatico(self, nome):
            if nome not in ESTATICOS:
                self._responder(404, "não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
                return
            with open(os.path.join(RAIZ_WEB, nome), "rb") as f:
                self._responder(200, f.read(), ESTATICOS[nome])

        def do_GET(self):
            u = urllib.parse.urlsplit(self.path)
            if u.path == "/":
                self._estatico("index.html")
            elif u.path.startswith("/estatico/"):
                self._estatico(u.path[len("/estatico/"):])
            elif u.path == "/api/estado":
                self._tratar(app.estado)
            elif u.path == "/api/template":
                id_template = urllib.parse.parse_qs(u.query).get("id", [""])[0]
                try:
                    self._responder(200, self.server.executar(lambda: app.imagem_template(id_template)), "image/png")
                except ValueError as erro:
                    self._json(400, {"erro": str(erro)})
            else:
                self._responder(404, "não encontrado".encode("utf-8"), "text/plain; charset=utf-8")

        def do_POST(self):
            u = urllib.parse.urlsplit(self.path)
            rotas = {"/api/exemplo": lambda d: app.analisar_exemplo(d.get("numero"), d.get("url_simulada")),
                     "/api/url": lambda d: app.analisar_url(d.get("url", ""), d.get("classe", CLASSE_PADRAO),
                                                            d.get("idioma", "en-US"), d.get("url_simulada"))}
            if u.path not in rotas:
                self._responder(404, "não encontrado".encode("utf-8"), "text/plain; charset=utf-8")
                return

            tamanho = int(self.headers.get("Content-Length") or 0)
            try:
                dados = json.loads(self.rfile.read(tamanho) or b"{}")
            except ValueError:
                dados = None
            if not isinstance(dados, dict):
                self._json(400, {"erro": "pedido inválido (JSON)"})
                return
            self._tratar(lambda: rotas[u.path](dados))

    return ServidorInterface((host, porta), Manipulador, app)
