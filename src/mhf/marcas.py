"""
Tabela de marcas protegidas (𝒯) e checagem de domínio (etapa 1 do plano).

`config/marcas.json` diz, para cada entidade de 𝒯, quais rótulos dos datasets são dela, quais domínios
são legítimos e quais páginas de login servem de referência (lidas pela captura de templates). Este
módulo faz o mapeamento rótulo → entidade e a checagem de domínio usada pela cascata (monografia §2.9).

Desenho: docs/especificacoes/2026-11-21-tabela-de-marcas.md
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

import tldextract

# Public Suffix List embutida no pacote (sem rede, sem cache em disco): o resultado não muda entre
# rodadas nem depende de quando o script roda, o que mantém a avaliação reproduzível.
_EXTRATOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


def _host(url_ou_host: str) -> str:
    """Host em minúsculas, sem porta, sem usuário e sem ponto final ("" se não houver)."""
    texto = url_ou_host.strip()
    if not texto:
        return ""
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
