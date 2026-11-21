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
from html import escape

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
    nas duas resoluções, ou ficaram sem algum arquivo (html_original.html de um download que falhou,
    screenshot/DOM que não chegou a ser salvo). Pasta sem meta.json (captura interrompida) ou meta.json
    ilegível contam como pendentes, porque o meta.json é gravado por último e marca a entrada como
    concluída."""
    pendentes = []
    for e in plano:
        if e.get("buraco"):
            continue
        pasta = pasta_entrada(raiz, e["id"])
        arquivos = ["html_original.html"] + [f"{p}_{r}.{ext}" for r in RESOLUCOES
                                             for p, ext in (("shot", "png"), ("dom", "html"))]
        try:
            with open(os.path.join(pasta, "meta.json"), encoding="utf-8") as f:
                resolucoes = json.load(f)["resolucoes"]
            concluida = (all(resolucoes[r]["status"] == "ok" for r in RESOLUCOES)
                         and all(os.path.exists(os.path.join(pasta, a)) for a in arquivos))
        except (OSError, ValueError, KeyError, TypeError):
            concluida = False
        if not concluida:
            pendentes.append(e)
    return pendentes


# ---------------------------------------------------------------- revisão (fase "revisar")

def marcar_aprovacao(plano: list[dict], id_: str, aprovado: bool, motivo: str = "") -> None:
    """Registra no plano a decisão do revisor sobre uma entrada. Id desconhecido lança KeyError."""
    for e in plano:
        if e["id"] == id_:
            e["aprovado"], e["motivo"] = aprovado, motivo
            return
    raise KeyError(id_)


def _celula_revisao(e: dict, meta: dict | None) -> str:
    if e.get("buraco"):
        return f'<td class="buraco">buraco: {escape(e["buraco"])}</td>'
    partes = []
    if meta is None:
        partes.append('<div class="status">não capturado</div>')
    else:
        shot = f'{escape(e["id"])}/shot_1280x960.png'
        partes.append(f'<a href="{shot}"><img src="{shot}" width="220" alt=""></a>')
        status = " · ".join(f"{r}: {escape(str(v.get('status', '?')))}"
                            for r, v in meta.get("resolucoes", {}).items())
        partes.append(f'<div class="status">{status}</div>')
        if meta.get("url_snapshot"):
            partes.append(f'<a href="{escape(meta["url_snapshot"])}">snapshot no Wayback</a>')
    partes.append(f'<div class="id">{escape(e["id"])}</div>')
    if e.get("aprovado") is True:
        classe, estado = "aprovado", "aprovado"
    elif e.get("aprovado") is False:
        classe, estado = "rejeitado", f"rejeitado: {e.get('motivo', '')}"
    else:
        classe, estado = "", "a revisar"
    partes.append(f'<div class="estado">{escape(estado)}</div>')
    return f'<td class="{classe}">{"".join(partes)}</td>'


def gerar_revisao_html(plano: list[dict], metas: dict[str, dict]) -> str:
    """Página de revisão: uma linha por entidade/variante, uma coluna por ano-alvo e uma para a captura
    ao vivo. Cada célula traz a miniatura (caminho relativo à pasta das capturas), o status de cada
    resolução, o link do snapshot e o estado da aprovação. `metas` é indexado pelo id da entrada."""
    colunas = [str(a) for a in ANOS_PADRAO] + ["ao vivo"]
    grade: dict[tuple[str, str], dict[str, dict]] = {}
    for e in plano:
        linha = grade.setdefault((e["entidade"], e["variante"]), {})
        for coluna in (["ao vivo"] if e["origem"] == "ao_vivo" else [str(a) for a in e["anos_alvo"]]):
            linha[coluna] = e  # um snapshot que cobre dois anos aparece nas duas colunas

    contagem = {"a revisar": 0, "aprovados": 0, "rejeitados": 0, "buracos": 0}
    for e in plano:
        chave = ("buracos" if e.get("buraco") else "aprovados" if e.get("aprovado") is True
                 else "rejeitados" if e.get("aprovado") is False else "a revisar")
        contagem[chave] += 1

    cabecalho = "".join(f"<th>{c}</th>" for c in colunas)
    linhas = []
    for (entidade, variante), celulas in grade.items():
        tds = "".join(_celula_revisao(celulas[c], metas.get(celulas[c]["id"])) if c in celulas
                      else '<td class="vazio"></td>' for c in colunas)
        linhas.append(f"<tr><th>{escape(entidade)}<br><small>{escape(variante)}</small></th>{tds}</tr>")
    resumo = " · ".join(f"{n} {k}" for k, n in contagem.items())
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Revisão dos templates</title>
<style>
 body {{ font-family: system-ui, sans-serif; margin: 16px; color: #222; background: #fafafa; }}
 table {{ border-collapse: collapse; }}
 th, td {{ border: 1px solid #ccc; padding: 6px; vertical-align: top; font-size: 12px; background: #fff; }}
 thead th {{ position: sticky; top: 0; background: #eee; }}
 td.aprovado {{ outline: 3px solid #2e7d32; }} td.rejeitado {{ outline: 3px solid #c62828; }}
 td.buraco, td.vazio {{ background: #f0f0f0; color: #777; }}
 .id {{ font-family: monospace; color: #555; }} .estado {{ font-weight: bold; }}
 code {{ background: #eee; padding: 1px 4px; }}
</style></head><body>
<h1>Revisão dos templates</h1>
<p>{resumo}</p>
<p>Para registrar a decisão: <code>python scripts/capturar_templates.py aprovar --plano &lt;plano&gt; ID [ID ...]</code>
ou <code>python scripts/capturar_templates.py rejeitar --plano &lt;plano&gt; ID --motivo "..."</code>.
Só templates aprovados entram na base.</p>
<table><thead><tr><th>entidade</th>{cabecalho}</tr></thead>
<tbody>{"".join(linhas)}</tbody></table>
</body></html>
"""
