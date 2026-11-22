"""
Captura ao vivo de uma página (etapa 7, interface): abre a URL no Chromium do Playwright com a janela de uma
classe de tela, espera o formulário de login aparecer e devolve a captura da janela (a primeira dobra), o
DOM renderizado e a URL final. É o equivalente, na demonstração, do que a extensão do navegador fará com a
aba aberta (captureVisibleTab + content script).

Desenho: docs/especificacoes/2026-11-22-interface.md, seção 7.
"""

import re
import time
import urllib.parse
from dataclasses import dataclass

from mhf import templates, visual

IDIOMAS = ("en-US", "pt-BR")
TEMPO_CARREGAR_MS = 30000
TEMPO_CREDENCIAL_MS = 20000  # o login.live.com só monta o formulário depois de ~13 s de JavaScript
TEMPO_REDE_MS = 10000

# "javascript:", "mailto:", "file:" etc.; "dominio.com:8443" não é esquema (dois-pontos seguido de dígito)
_ESQUEMA = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*:(?!\d)")


class ErroCaptura(RuntimeError):
    """A página não pôde ser aberta ou capturada (endereço inexistente, tempo esgotado, navegador ausente)."""


@dataclass
class PaginaCapturada:
    imagem: bytes          # PNG da janela (primeira dobra)
    html: str              # DOM renderizado (page.content())
    url_digitada: str
    url_final: str         # depois de redirecionamentos
    titulo: str
    status: int | None     # código HTTP da resposta principal
    credencial: bool       # o campo de login apareceu dentro do tempo
    tempo_s: float         # abrir + esperar + capturar


def normalizar_url(texto: str) -> str:
    """Endereço digitado → URL http(s) completa. Sem esquema, completa com https://; outro esquema
    (javascript:, file:, mailto:...) ou sem domínio → ValueError com mensagem em português."""
    t = (texto or "").strip()
    if not t:
        raise ValueError("informe um endereço")
    if "://" not in t and not _ESQUEMA.match(t):
        t = "https://" + t
    partes = urllib.parse.urlsplit(t)
    esquema = partes.scheme.lower()
    if esquema not in ("http", "https"):
        raise ValueError(f"só endereços http ou https (recebido: {partes.scheme}:)")
    if not partes.hostname:
        raise ValueError("o endereço não tem domínio")
    return urllib.parse.urlunsplit((esquema, partes.netloc, partes.path or "/", partes.query, partes.fragment))


def esperar_credencial(pagina, seletor, tempo_ms):
    """Espera um campo de credencial VISÍVEL aparecer na página ou em qualquer frame dela (o login de
    algumas marcas fica dentro de um iframe). Devolve True se apareceu dentro do tempo."""
    from playwright.sync_api import Error as ErroPlaywright

    limite = time.monotonic() + tempo_ms / 1000
    while time.monotonic() < limite:
        for quadro in pagina.frames:
            try:
                if any(el.is_visible() for el in quadro.query_selector_all(seletor)):
                    return True
            except ErroPlaywright:
                pass  # frame saindo ou navegando no meio da consulta
        pagina.wait_for_timeout(500)
    return False


def capturar_pagina(navegador, url, classe="1366x768", idioma="en-US", espera_credencial_ms=TEMPO_CREDENCIAL_MS):
    """Abre `url` num contexto novo (sem cookies, downloads bloqueados), com a janela da classe de tela e o
    idioma pedidos, e devolve a PaginaCapturada. `navegador` é um Browser do Playwright."""
    from playwright.sync_api import Error as ErroPlaywright
    from playwright.sync_api import TimeoutError as TempoEsgotado

    if classe not in visual.CLASSES_TELA:
        raise ValueError(f"tamanho de tela desconhecido: {classe} (use {', '.join(visual.CLASSES_TELA)})")
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma desconhecido: {idioma} (use {', '.join(IDIOMAS)})")
    url = normalizar_url(url)
    largura, altura = visual.CLASSES_TELA[classe]
    inicio = time.perf_counter()
    contexto = navegador.new_context(viewport={"width": largura, "height": altura}, locale=idioma,
                                     accept_downloads=False)
    try:
        pagina = contexto.new_page()
        try:
            resposta = pagina.goto(url, wait_until="load", timeout=TEMPO_CARREGAR_MS)
        except ErroPlaywright as erro:
            raise ErroCaptura(f"não foi possível abrir a página: {str(erro).splitlines()[0][:200]}") from erro
        credencial = esperar_credencial(pagina, templates.SELETOR_CREDENCIAL, espera_credencial_ms)
        try:
            pagina.wait_for_load_state("networkidle", timeout=TEMPO_REDE_MS)
        except TempoEsgotado:
            pass  # páginas com requisições contínuas nunca ficam ociosas
        try:
            imagem, html, titulo, url_final = pagina.screenshot(full_page=False), pagina.content(), \
                pagina.title(), pagina.url
        except ErroPlaywright as erro:
            raise ErroCaptura(f"não foi possível capturar a página: {str(erro).splitlines()[0][:200]}") from erro
    finally:
        contexto.close()
    return PaginaCapturada(imagem=imagem, html=html, url_digitada=url, url_final=url_final, titulo=titulo,
                           status=resposta.status if resposta is not None else None, credencial=credencial,
                           tempo_s=time.perf_counter() - inicio)


class NavegadorAoVivo:
    """O Chromium do Playwright, iniciado na primeira captura e mantido aberto até fechar()."""

    def __init__(self):
        self._playwright = self._navegador = None

    def capturar(self, url, classe, idioma):
        if self._navegador is None:
            from playwright.sync_api import Error as ErroPlaywright
            from playwright.sync_api import sync_playwright
            try:
                self._playwright = sync_playwright().start()
                self._navegador = self._playwright.chromium.launch()
            except ErroPlaywright as erro:
                self.fechar()
                raise ErroCaptura("o Chromium do Playwright não abriu (instale com: python -m playwright "
                                  f"install chromium --only-shell): {str(erro).splitlines()[0][:200]}") from erro
        return capturar_pagina(self._navegador, url, classe, idioma)

    def fechar(self):
        for obj, metodo in ((self._navegador, "close"), (self._playwright, "stop")):
            if obj is not None:
                try:
                    getattr(obj, metodo)()
                except Exception:  # noqa: BLE001 — fechando de qualquer jeito
                    pass
        self._playwright = self._navegador = None
