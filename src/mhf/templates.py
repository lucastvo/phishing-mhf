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
from datetime import datetime, timedelta

ANOS_PADRAO = range(2019, 2027)    # anos-alvo dos snapshots do Wayback (alvo = 1º de janeiro de cada ano)
TOLERANCIA = timedelta(days=183)   # mais longe que isso do alvo, o ano vira buraco
ANO_AO_VIVO = 2026                 # ano da captura ao vivo (cenário "só 2026" da avaliação)


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


# ---------------------------------------------------------------- plano (fase "planejar")

def escolher_snapshot(capturas: list[tuple[str, int]], alvo: datetime,
                      tolerancia: timedelta = TOLERANCIA) -> tuple[str, int] | None:
    """Entre as linhas da CDX (timestamp de 14 dígitos, status HTTP), escolhe o snapshot mais próximo
    do alvo dentro da tolerância (inclusiva). Prefere status 200; só aceita um redirecionamento (3xx)
    se não houver nenhum 200 na janela. Devolve None se nada couber."""
    def distancia(ts: str) -> timedelta:
        return abs(datetime.strptime(ts, "%Y%m%d%H%M%S") - alvo)

    na_janela = [(ts, st) for ts, st in capturas if distancia(ts) <= tolerancia]
    for aceitos in ((200,), range(300, 400)):
        candidatos = [(distancia(ts), ts, st) for ts, st in na_janela if st in aceitos]
        if candidatos:
            _, ts, st = min(candidatos)
            return ts, st
    return None


def planejar_variante(v: VarianteLogin, capturas: list[tuple[str, int]] | None,
                      anos=ANOS_PADRAO) -> list[dict]:
    """Entradas do plano de uma variante: um snapshot por ano-alvo (anos que caem no mesmo snapshot
    viram uma entrada só), buracos para os anos sem snapshot e, no fim, a captura ao vivo.
    `capturas=None` significa que a consulta à CDX falhou: todos os anos viram buraco "erro_consulta"."""
    def entrada(rotulo: str, **campos) -> dict:
        return {"id": id_entrada(v.entidade, v.variante, rotulo), "entidade": v.entidade,
                "variante": v.variante, "url_login": v.url, "locale": v.locale, **campos,
                "aprovado": None, "motivo": ""}

    entradas, por_timestamp = [], {}
    for ano in anos:
        escolhido = None if capturas is None else escolher_snapshot(capturas, datetime(ano, 1, 1))
        if escolhido is None:
            entradas.append(entrada(f"buraco-{ano}", origem="wayback", timestamp=None, status_cdx=None,
                                    anos_alvo=[ano],
                                    buraco="erro_consulta" if capturas is None else "sem_snapshot"))
        elif escolhido[0] in por_timestamp:
            por_timestamp[escolhido[0]]["anos_alvo"].append(ano)
        else:
            ts, status = escolhido
            e = entrada(f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", origem="wayback", timestamp=ts, status_cdx=status,
                        anos_alvo=[ano], buraco=None)
            por_timestamp[ts] = e
            entradas.append(e)
    entradas.append(entrada("ao-vivo", origem="ao_vivo", timestamp=None, status_cdx=None,
                            anos_alvo=[ANO_AO_VIVO], buraco=None))
    return entradas


def mesclar_plano(novo: list[dict], antigo: list[dict]) -> list[dict]:
    """Plano recém-gerado, mas com `aprovado`/`motivo` herdados das entradas de mesmo id do plano
    anterior, para que rodar "planejar" de novo não apague a revisão já feita."""
    anteriores = {e["id"]: e for e in antigo}
    mescladas = []
    for e in novo:
        anterior = anteriores.get(e["id"])
        if anterior is not None:
            e = {**e, "aprovado": anterior.get("aprovado"), "motivo": anterior.get("motivo", "")}
        mescladas.append(e)
    return mescladas
