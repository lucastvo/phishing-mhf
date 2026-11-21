"""
Base de templates com vários anos (etapa 2 do plano).

Funções puras usadas pelo script `scripts/capturar_templates.py`: leitura das variantes de login,
identificadores estáveis, escolha de snapshots do Wayback, URLs do Wayback e limpeza do DOM
capturado. Nada aqui acessa a rede ou abre navegador, para que tudo possa ser testado offline.

Desenho: docs/especificacoes/2026-11-20-base-de-templates.md
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class VarianteLogin:
    """Uma página de login de uma entidade de 𝒯 (ex.: Microsoft "pessoal" = login.live.com)."""
    entidade: str
    variante: str
    url: str
    locale: str  # usado só na captura ao vivo (en-US para marcas globais, pt-BR para bancos brasileiros)


def ler_marcas(caminho: str) -> list[VarianteLogin]:
    """Lê a tabela de marcas (lista de entidades, cada uma com `logins`) e achata as variantes."""
    with open(caminho, encoding="utf-8") as f:
        marcas = json.load(f)
    return [VarianteLogin(m["entidade"], login["variante"], login["url"], login["locale"])
            for m in marcas for login in m["logins"]]


def slug(texto: str) -> str:
    """Nome seguro para pasta: sem acentos, minúsculo, só [a-z0-9] separados por "_"."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def id_entrada(entidade: str, variante: str, rotulo: str) -> str:
    """Identificador de uma entrada do plano, que também é o caminho relativo da pasta dela.
    `rotulo` é a data do snapshot (AAAA-MM-DD), "ao-vivo" ou "buraco-<ano>"."""
    return f"{slug(entidade)}/{slug(variante)}/{rotulo}"
