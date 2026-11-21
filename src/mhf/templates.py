"""
Base de templates com vários anos (etapa 2 do plano).

Funções puras usadas pelo script `scripts/capturar_templates.py`: leitura das variantes de login,
identificadores estáveis, escolha de snapshots do Wayback, URLs do Wayback e limpeza do DOM
capturado. Nada aqui acessa a rede ou abre navegador, para que tudo possa ser testado offline.

Desenho: docs/especificacoes/2026-11-20-base-de-templates.md
"""

from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta

ANOS_PADRAO = range(2019, 2027)    # anos-alvo dos snapshots do Wayback (alvo = 1º de janeiro de cada ano)
TOLERANCIA = timedelta(days=183)   # mais longe que isso do alvo, o ano vira buraco
ANO_AO_VIVO = 2026                 # ano da captura ao vivo (cenário "só 2026" da avaliação)

# Resoluções dos datasets: 1280x960 (Phish360) e 1366x768 (Phishpedia, primeira dobra).
RESOLUCOES = {"1280x960": (1280, 960), "1366x768": (1366, 768)}

# Campo que indica que o formulário de login já apareceu (a captura espera por ele, não por um tempo fixo).
SELETOR_CREDENCIAL = ('input[type=password], input[type=email], input[name*=user i], '
                      'input[name*=login i], input[name*=email i], input[id*=user i]')

# Barra e banners que o Wayback injeta na página arquivada (modo comum); são removidos antes do
# screenshot e do DOM. Medido em 20/11/2026: com eles removidos, o screenshot fica idêntico (0 pixels
# diferentes) ao do modo if_ — que não é usado porque quebra o teste de cookies do login da Microsoft.
SELETOR_BARRA_WAYBACK = "#wm-ipp-base, #wm-ipp-print, #donato, #wm-ipp"

# Prefixo que o Wayback põe nas URLs da página arquivada, em qualquer das formas: absoluta, sem esquema
# (//web.archive.org) ou relativa (/web/...), com ou sem modificador (if_, im_, js_, cs_...). Só é
# removido quando vem seguido de uma URL com esquema, para não tocar em caminhos legítimos como /web/2020/.
_PREFIXO_WAYBACK = re.compile(r"(?:(?:https?:)?//web\.archive\.org)?/web/\d{1,14}(?:[a-z]{2}_)?/(?=https?:)")


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


# ---------------------------------------------------------------- Wayback (fase "capturar")

def url_wayback(timestamp: str, url: str, modo: str = "if_") -> str:
    """URL de um snapshot. `modo=""` é o modo comum (página com os recursos da época e a barra do
    Wayback, que a captura remove); `if_` renderiza sem a barra; `id_` devolve o HTML original como
    foi arquivado, sem reescrita."""
    return f"https://web.archive.org/web/{timestamp}{modo}/{url}"


def remover_prefixo_wayback(html: str) -> str:
    """Desfaz a reescrita de URLs do Wayback no DOM capturado. Sem isso, toda `action` de formulário
    apontaria para web.archive.org e a contagem forms_action_externa do componente s ficaria errada."""
    return _PREFIXO_WAYBACK.sub("", html)


def pasta_entrada(raiz: str, id_: str) -> str:
    """Pasta onde ficam os arquivos de uma entrada (o id usa "/" como separador)."""
    return os.path.join(raiz, *id_.split("/"))


def entradas_pendentes(plano: list[dict], raiz: str) -> list[dict]:
    """Entradas que ainda precisam ser capturadas: não são buraco e não têm meta.json com status "ok"
    nas duas resoluções, ou ficaram sem o html_original.html (download que falhou). Pasta sem
    meta.json (captura interrompida) ou meta.json ilegível contam como pendentes, porque o meta.json
    é gravado por último e marca a entrada como concluída."""
    pendentes = []
    for e in plano:
        if e.get("buraco"):
            continue
        pasta = pasta_entrada(raiz, e["id"])
        try:
            with open(os.path.join(pasta, "meta.json"), encoding="utf-8") as f:
                resolucoes = json.load(f)["resolucoes"]
            concluida = (all(resolucoes[r]["status"] == "ok" for r in RESOLUCOES)
                         and os.path.exists(os.path.join(pasta, "html_original.html")))
        except (OSError, ValueError, KeyError, TypeError):
            concluida = False
        if not concluida:
            pendentes.append(e)
    return pendentes
