"""
Tabela de marcas protegidas (𝒯) e checagem de domínio (etapa 1 do plano).

`config/marcas.json` diz, para cada entidade de 𝒯, quais rótulos dos datasets são dela, quais domínios
são legítimos e quais páginas de login servem de referência (lidas pela captura de templates). Este
módulo faz o mapeamento rótulo → entidade e a checagem de domínio usada pela cascata (monografia §2.9).

Desenho: docs/especificacoes/2026-11-21-tabela-de-marcas.md
"""

from __future__ import annotations

import ipaddress
import json
import re
from urllib.parse import urlsplit

import tldextract

# Public Suffix List embutida no pacote (sem rede, sem cache em disco; versão do tldextract fixada no
# requirements.txt): o resultado não muda entre rodadas, o que mantém a avaliação reproduzível.
# Inclui a seção PRIVADA da lista (hospedagem compartilhada: blob.core.windows.net, github.io,
# appspot.com…), para que cada cliente desses serviços conte como um dono diferente.
_EXTRATOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None, include_psl_private_domains=True)

# Esquemas em que o navegador trata "\" como "/" (padrão WHATWG). Sem esquema também tratamos assim.
_ESQUEMA = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*):")
_ESQUEMAS_ESPECIAIS = {"http", "https", "ws", "wss", "ftp"}

# Campo da tabela com os rótulos de cada dataset.
_CAMPO_ROTULOS = {"phishpedia": "nomes_phishpedia", "phish360": "nomes_phish360"}


def ler_tabela(caminho: str) -> list[dict]:
    """Lê a tabela de marcas (config/marcas.json): uma lista de entidades."""
    with open(caminho, encoding="utf-8") as f:
        return json.load(f)


def entidade_do_rotulo(tabela: list[dict], dataset: str, rotulo: str) -> str | None:
    """Entidade de 𝒯 a que pertence o rótulo de marca de uma amostra, ou None (fora de 𝒯).
    Phishpedia: comparação exata (os nomes são de empresa, ex.: "PayPal Inc."); Phish360: sem
    diferenciar maiúsculas (os rótulos vêm do nome da pasta, ex.: "paypal")."""
    if dataset not in _CAMPO_ROTULOS:
        raise ValueError(f"dataset desconhecido: {dataset!r} (use {sorted(_CAMPO_ROTULOS)})")
    campo = _CAMPO_ROTULOS[dataset]
    for e in tabela:
        nomes = e.get(campo, [])
        if dataset == "phish360":
            if rotulo.lower() in (n.lower() for n in nomes):
                return e["entidade"]
        elif rotulo in nomes:
            return e["entidade"]
    return None


def dominio_legitimo(tabela: list[dict], entidade: str, url: str) -> bool:
    """O domínio registrável da URL é um dos domínios legítimos da entidade? É a checagem de domínio da
    cascata: páginas como paypal.com.conta-segura.net ou paypal-login.com não passam. Entidade fora da
    tabela lança KeyError."""
    for e in tabela:
        if e["entidade"] == entidade:
            dominio = dominio_registravel(url)
            return bool(dominio) and dominio in {d.lower() for d in e["dominios"]}
    raise KeyError(entidade)


def _host(url_ou_host: str) -> str:
    """Host em minúsculas, sem porta, sem usuário e sem ponto final ("" se não houver)."""
    texto = url_ou_host.strip()
    if not texto:
        return ""
    esquema = _ESQUEMA.match(texto)
    if esquema is None or esquema.group(1).lower() in _ESQUEMAS_ESPECIAIS:
        # Como no navegador: em http://evil.net\@paypal.com/ o host é evil.net, não paypal.com.
        texto = texto.replace("\\", "/")
    if "://" not in texto:
        texto = "//" + texto  # sem esquema: o urlsplit só reconhece o host depois de "//"
    try:
        host = urlsplit(texto).hostname or ""
    except ValueError:
        return ""
    return host.rstrip(".").lower()


def dominio_registravel(url_ou_host: str) -> str:
    """Domínio "de verdade" de uma URL, segundo a Public Suffix List: www.itau.com.br → itau.com.br,
    secure07c.chase.com → chase.com. Em http://paypal.com@evil.net/ o host é evil.net (o que vem antes
    do @ é usuário). IP é devolvido como está."""
    host = _host(url_ou_host)
    if not host:
        return ""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    partes = _EXTRATOR(host)
    dominio = getattr(partes, "top_domain_under_public_suffix", None)
    if dominio is None:  # versões antigas do tldextract
        dominio = partes.registered_domain
    return dominio or host  # sem sufixo público conhecido (ex.: "localhost"): o próprio host
