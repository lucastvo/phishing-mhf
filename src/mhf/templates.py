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

# Resoluções capturadas DEPOIS da captura principal, cada uma com metadados e aprovação próprios
# (extra_<r>.json e o campo "extras" da entrada), sem tocar na captura e na aprovação já feitas.
# 1920x1080 é o tamanho de tela de 74% dos phishings do Phishpedia (etapa 3: a amostra é comparada com
# templates do mesmo tamanho de tela).
RESOLUCOES_EXTRAS = {"1920x1080": (1920, 1080)}

# Campo que indica que o formulário de login já apareceu (a captura espera por ele, não por um tempo fixo).
# Inclui campos típicos de bancos brasileiros (CPF, agência, usuário). Uma variante pode trocar o seletor
# pelo campo "seletor" da tabela de marcas, quando o login dela usar outro campo.
SELETOR_CREDENCIAL = ('input[type=password], input[type=email], input[name*=user i], '
                      'input[name*=login i], input[name*=email i], input[id*=user i], '
                      'input[name*=cpf i], input[id*=cpf i], input[name*=agencia i], input[id*=agencia i], '
                      'input[name*=usuario i]')

# Barra e banners que o Wayback injeta na página arquivada (modo comum); são removidos antes do
# screenshot e do DOM. Medido em 20/11/2026: com eles removidos, o screenshot fica idêntico (0 pixels
# diferentes) ao do modo if_ — que não é usado porque quebra o teste de cookies do login da Microsoft.
SELETOR_BARRA_WAYBACK = "#wm-ipp-base, #wm-ipp-print, #donato, #wm-ipp"

# Prefixo que o Wayback põe nas URLs da página arquivada, em qualquer das formas: absoluta, sem esquema
# (//web.archive.org) ou relativa (/web/...), com ou sem modificador (if_, im_, js_, cs_...). Só é
# removido quando vem seguido de uma URL com esquema, para não tocar em caminhos legítimos como /web/2020/.
_PREFIXO_WAYBACK = re.compile(r"(?:(?:https?:)?//web\.archive\.org)?/web/\d{1,14}(?:[a-z]{2}_)?/(?=https?:)")
# A mesma reescrita dentro de JavaScript/JSON da página, com as barras escapadas (https:\/\/web.archive.org\/web\/...).
_PREFIXO_WAYBACK_ESCAPADO = re.compile(r"(?:https?:)?\\/\\/web\.archive\.org\\/web\\/\d{1,14}(?:[a-z]{2}_)?\\/(?=https?:)")

# O que o Wayback injeta no DOM além da barra: scripts e folhas de estilo servidos por *.archive.org,
# scripts embutidos de reprodução/telemetria (__wm, archive_analytics) e a variável de altura da barra.
# Sem isso, templates do Wayback e ao vivo teriam DOMs sistematicamente diferentes.
_INJECOES_WAYBACK = [
    re.compile(r'<script\b[^>]*\bsrc="[^"]*archive\.org[^"]*"[^>]*>\s*</script>', re.I),
    re.compile(r'<link\b[^>]*\bhref="[^"]*archive\.org[^"]*"[^>]*>', re.I),
    re.compile(r"<script\b[^>]*>(?:(?!</script>).)*?(?:__wm\.|archive_analytics)(?:(?!</script>).)*?</script>",
               re.I | re.S),
    re.compile(r"--wm-toolbar-height:\s*\d+px;?\s*"),
]


BUSCAS = ("exata", "prefixo")

# Variantes buscadas por prefixo: quantos snapshots, do mais próximo do alvo para o mais longe, o
# `planejar` baixa e confere por ano antes de desistir e marcar o ano como buraco.
MAX_VERIFICACOES_CONTEUDO = 8



@dataclass(frozen=True)
class VarianteLogin:
    """Uma página de login de uma entidade de 𝒯 (ex.: Microsoft "pessoal" = login.live.com).

    `busca="prefixo"` é para logins que o Wayback só guardou em URLs de sessão, cada uma arquivada uma
    ou duas vezes (ex.: amazon.com/ap/signin/<sessão>?openid...): o `planejar` procura qualquer URL que
    comece com `url` e, como parte desses snapshots é a tela de CAPTCHA, confere o HTML original de cada
    candidato: nenhum dos textos de `evitar` pode aparecer e, se `exigir` não for vazio, pelo menos um
    dos textos dele precisa aparecer (sem diferenciar maiúsculas)."""
    entidade: str
    variante: str
    url: str
    locale: str  # en-US para marcas globais, pt-BR para bancos brasileiros
    seletor: str | None = None  # campo de credencial próprio da variante; None = SELETOR_CREDENCIAL
    busca: str = "exata"        # "exata" (a URL como está) ou "prefixo"
    evitar: tuple[str, ...] = ()
    exigir: tuple[str, ...] = ()


def ler_marcas(caminho: str) -> list[VarianteLogin]:
    """Lê a tabela de marcas (lista de entidades, cada uma com `logins`) e achata as variantes.
    Um valor de `busca` desconhecido lança ValueError (um erro de digitação na tabela mudaria a busca
    sem aviso)."""
    with open(caminho, encoding="utf-8") as f:
        marcas = json.load(f)
    variantes = []
    for m in marcas:
        for login in m["logins"]:
            nome = f"{m['entidade']}/{login['variante']}"
            busca = login.get("busca", "exata")
            if busca not in BUSCAS:
                raise ValueError(f"{nome}: busca {busca!r} desconhecida (use {BUSCAS})")
            filtros = {}
            for campo in ("evitar", "exigir"):
                valor = login.get(campo, [])
                # uma string viraria uma tupla de letras: "exigir": "ap_email" aceitaria qualquer página
                if not isinstance(valor, list) or not all(isinstance(t, str) and t for t in valor):
                    raise ValueError(f"{nome}: {campo!r} precisa ser uma lista de textos")
                if valor and busca != "prefixo":
                    raise ValueError(f"{nome}: {campo!r} só vale com \"busca\": \"prefixo\" (seria ignorado)")
                filtros[campo] = tuple(valor)
            variantes.append(VarianteLogin(m["entidade"], login["variante"], login["url"], login["locale"],
                                           login.get("seletor"), busca, filtros["evitar"], filtros["exigir"]))
    return variantes


def html_aceitavel(html: str | None, evitar=(), exigir=()) -> bool:
    """O HTML original de um snapshot serve de template? Nenhum texto de `evitar` pode aparecer e, se
    houver `exigir`, pelo menos um dos textos dele precisa aparecer (sem diferenciar maiúsculas).
    HTML ausente (download falhou) não serve: não dá para conferir."""
    if html is None:
        return False
    texto = html.lower()
    if any(t.lower() in texto for t in evitar):
        return False
    return not exigir or any(t.lower() in texto for t in exigir)


def slug(texto: str) -> str:
    """Nome seguro para pasta: sem acentos, minúsculo, só [a-z0-9] separados por "_"."""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "_", sem_acento.lower()).strip("_")


def id_entrada(entidade: str, variante: str, rotulo: str) -> str:
    """Identificador de uma entrada do plano, que também é o caminho relativo da pasta dela.
    `rotulo` é a data do snapshot (AAAA-MM-DD), "ao-vivo" ou "buraco-<ano>"."""
    return f"{slug(entidade)}/{slug(variante)}/{rotulo}"


# ---------------------------------------------------------------- plano (fase "planejar")

def candidatos_ordenados(capturas: list[tuple], alvo: datetime,
                         tolerancia: timedelta = TOLERANCIA) -> list[tuple]:
    """Snapshots dentro da tolerância (inclusiva), na ordem de preferência: primeiro os de status 200,
    do mais próximo do alvo para o mais longe; depois os redirecionamentos (3xx), na mesma ordem. Cada
    captura é (timestamp de 14 dígitos, status) ou, na busca por prefixo, (timestamp, status, URL)."""
    def distancia(ts: str) -> timedelta:
        return abs(datetime.strptime(ts, "%Y%m%d%H%M%S") - alvo)

    ordenados = []
    for aceitos in ((200,), range(300, 400)):
        ordenados += sorted((c for c in capturas if c[1] in aceitos and distancia(c[0]) <= tolerancia),
                            key=lambda c: (distancia(c[0]), c))
    return ordenados


def escolher_snapshot(capturas: list[tuple[str, int]], alvo: datetime,
                      tolerancia: timedelta = TOLERANCIA) -> tuple[str, int] | None:
    """Entre as linhas da CDX (timestamp de 14 dígitos, status HTTP), escolhe o snapshot mais próximo
    do alvo dentro da tolerância (inclusiva). Prefere status 200; só aceita um redirecionamento (3xx)
    se não houver nenhum 200 na janela. Devolve None se nada couber."""
    candidatos = candidatos_ordenados(capturas, alvo, tolerancia)
    return candidatos[0] if candidatos else None


def planejar_variante(v: VarianteLogin, capturas: list[tuple] | None, anos=ANOS_PADRAO,
                      aceitar=None) -> list[dict]:
    """Entradas do plano de uma variante: um snapshot por ano-alvo (anos que caem no mesmo snapshot
    viram uma entrada só), buracos para os anos sem snapshot e, no fim, a captura ao vivo.
    `capturas=None` significa que a consulta à CDX falhou: todos os anos viram buraco "erro_consulta".

    Na busca por prefixo, as capturas trazem a URL arquivada, que vai para o campo `url_arquivada` da
    entrada, e `aceitar(timestamp, url)` diz se o conteúdo do snapshot serve (o script baixa e confere o
    HTML original): True serve, False não serve e None quer dizer que o download falhou. São tentados até
    MAX_VERIFICACOES_CONTEUDO candidatos por ano; se nenhum servir, o ano vira buraco
    "sem_snapshot_valido". Um download que falha encerra o ano como buraco "erro_conferencia" (em vez de
    passar em silêncio para um candidato mais distante), e o `mesclar_plano` mantém a variante antiga.
    Variantes de busca exata seguem como antes: o snapshot mais próximo, sem conferir conteúdo e sem o
    campo `url_arquivada`."""
    por_prefixo = v.busca == "prefixo"

    def entrada(rotulo: str, **campos) -> dict:
        return {"id": id_entrada(v.entidade, v.variante, rotulo), "entidade": v.entidade,
                "variante": v.variante, "url_login": v.url, "locale": v.locale, "seletor": v.seletor,
                **campos, "aprovado": None, "motivo": "", "aprovado_captura": None}

    def escolher(ano: int):
        candidatos = candidatos_ordenados(capturas, datetime(ano, 1, 1))
        if not por_prefixo:
            return (candidatos[0], None) if candidatos else (None, "sem_snapshot")
        if not candidatos:
            return None, "sem_snapshot"
        for c in candidatos[:MAX_VERIFICACOES_CONTEUDO]:
            resultado = True if aceitar is None else aceitar(c[0], c[2])
            if resultado is None:
                return None, "erro_conferencia"
            if resultado:
                return c, None
        return None, "sem_snapshot_valido"

    entradas, por_snapshot, rotulos = [], {}, set()
    for ano in anos:
        escolhido, motivo = (None, "erro_consulta") if capturas is None else escolher(ano)
        if escolhido is None:
            entradas.append(entrada(f"buraco-{ano}", origem="wayback", timestamp=None, status_cdx=None,
                                    anos_alvo=[ano], buraco=motivo))
            continue
        chave = (escolhido[0], escolhido[2] if por_prefixo else None)
        if chave in por_snapshot:
            por_snapshot[chave]["anos_alvo"].append(ano)
            continue
        ts, status = escolhido[0], escolhido[1]
        rotulo = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"
        if rotulo in rotulos:  # dois snapshots diferentes no mesmo dia (só acontece na busca por prefixo)
            rotulo += f"-{ts[8:12]}"
        rotulos.add(rotulo)
        extra = {"url_arquivada": escolhido[2]} if por_prefixo else {}
        e = entrada(rotulo, origem="wayback", timestamp=ts, status_cdx=status, anos_alvo=[ano], buraco=None,
                    **extra)
        por_snapshot[chave] = e
        entradas.append(e)
    entradas.append(entrada("ao-vivo", origem="ao_vivo", timestamp=None, status_cdx=None,
                            anos_alvo=[ANO_AO_VIVO], buraco=None))
    return entradas


def url_da_captura(e: dict) -> str:
    """URL que a captura carrega no Wayback: a URL arquivada (busca por prefixo) ou a da variante."""
    return e.get("url_arquivada") or e["url_login"]


def _mesmo_snapshot(a: dict, b: dict) -> bool:
    # url_arquivada só existe na busca por prefixo; nas variantes exatas os dois lados têm None.
    return all(a.get(k) == b.get(k) for k in ("url_login", "url_arquivada", "timestamp", "origem"))


def mesclar_plano(novo: list[dict], antigo: list[dict]) -> list[dict]:
    """Plano recém-gerado, preservando a revisão já feita no plano anterior:
    - a decisão (`aprovado`, `motivo`, `aprovado_captura`) só é herdada por uma entrada de mesmo id
      que aponte para o MESMO snapshot (mesma URL de login, timestamp e origem); outra URL ou outro
      snapshot com o mesmo id volta a "a revisar";
    - se a consulta à CDX falhou para uma variante (todos os seus anos viraram "erro_consulta"), ou se
      algum download da conferência de conteúdo falhou (algum ano virou "erro_conferencia", na busca por
      prefixo), e o plano anterior tem essa variante, as entradas antigas dela são mantidas como estavam,
      para que uma queda do Internet Archive não apague o plano nem as aprovações."""
    def variante(e: dict) -> tuple:
        return e.get("entidade"), e.get("variante")

    antigas_por_variante: dict[tuple, list[dict]] = {}
    for e in antigo:
        antigas_por_variante.setdefault(variante(e), []).append(e)
    anteriores = {e["id"]: e for e in antigo}

    novas_por_variante: dict[tuple, list[dict]] = {}
    for e in novo:
        novas_por_variante.setdefault(variante(e), []).append(e)

    mescladas = []
    for chave, entradas in novas_por_variante.items():
        do_wayback = [e for e in entradas if e.get("origem") == "wayback"]
        consulta_falhou = bool(do_wayback) and (all(e.get("buraco") == "erro_consulta" for e in do_wayback)
                                                or any(e.get("buraco") == "erro_conferencia" for e in do_wayback))
        if consulta_falhou and chave in antigas_por_variante:
            mescladas += antigas_por_variante[chave]
            continue
        for e in entradas:
            anterior = anteriores.get(e["id"])
            if anterior is not None and _mesmo_snapshot(e, anterior):
                e = {**e, "aprovado": anterior.get("aprovado"), "motivo": anterior.get("motivo", ""),
                     "aprovado_captura": anterior.get("aprovado_captura")}
                if anterior.get("extras"):  # decisões das resoluções extras, do mesmo snapshot
                    e["extras"] = anterior["extras"]
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
    return _PREFIXO_WAYBACK_ESCAPADO.sub("", _PREFIXO_WAYBACK.sub("", html))


def limpar_injecoes_wayback(html: str) -> str:
    """Remove do DOM capturado os scripts, folhas de estilo e estilos que o próprio Wayback injeta,
    deixando os recursos da página arquivada intactos."""
    for padrao in _INJECOES_WAYBACK:
        html = padrao.sub("", html)
    return html


def residuos_wayback(html: str) -> int:
    """Quantos vestígios do Wayback sobraram no DOM (gravado no meta.json para conferência)."""
    return html.count("archive.org") + html.count("__wm")


def timestamp_efetivo(url_final: str) -> str | None:
    """Timestamp do snapshot que de fato foi exibido, tirado da URL final. No modo comum, o Wayback
    segue redirecionamentos para a captura mais próxima do destino, que pode não ser a planejada."""
    m = re.search(r"web\.archive\.org/web/(\d{14})", url_final)
    return m.group(1) if m else None


def fora_da_janela(ts: str, anos_alvo: list[int], tolerancia: timedelta = TOLERANCIA) -> bool:
    """O snapshot `ts` está a mais de `tolerancia` de algum dos alvos (1º de janeiro) que ele representa?"""
    instante = datetime.strptime(ts, "%Y%m%d%H%M%S")
    return any(abs(instante - datetime(ano, 1, 1)) > tolerancia for ano in anos_alvo)


def pasta_entrada(raiz: str, id_: str) -> str:
    """Pasta onde ficam os arquivos de uma entrada (o id usa "/" como separador)."""
    return os.path.join(raiz, *id_.split("/"))


ARQUIVOS_CAPTURA = ["html_original.html"] + [f"{p}_{r}.{ext}" for r in RESOLUCOES
                                             for p, ext in (("shot", "png"), ("dom", "html"))]


def limpar_pasta_captura(pasta: str) -> None:
    """Apaga os arquivos de uma captura anterior (meta.json, HTML original, screenshots e DOMs) antes de
    recapturar. Sem isso, se o download do HTML original falhasse na recaptura, o arquivo do snapshot
    anterior ficaria na pasta e passaria como sendo do novo."""
    for nome in ["meta.json"] + ARQUIVOS_CAPTURA:
        try:
            os.remove(os.path.join(pasta, nome))
        except FileNotFoundError:
            pass


def _ler_meta(raiz: str, e: dict) -> dict | None:
    """meta.json de uma entrada, ou None se não existir ou estiver ilegível."""
    try:
        with open(os.path.join(pasta_entrada(raiz, e["id"]), "meta.json"), encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError):
        return None


def _captura_valida(raiz: str, e: dict, meta: dict | None, exigir_ok: bool) -> bool:
    """A captura no disco é desta entrada (mesma URL e snapshot do plano) e está completa?"""
    if meta is None or not _mesmo_snapshot({**meta, "origem": e.get("origem")}, e):
        return False
    pasta = pasta_entrada(raiz, e["id"])
    if not all(os.path.exists(os.path.join(pasta, a)) for a in ARQUIVOS_CAPTURA):
        return False
    if exigir_ok:
        try:
            return all(meta["resolucoes"][r]["status"] == "ok" for r in RESOLUCOES)
        except (KeyError, TypeError):
            return False
    return True


def data_captura_valida(raiz: str, e: dict) -> str | None:
    """`data_captura` da captura no disco, só se ela for desta entrada (mesma URL, URL arquivada e
    snapshot do plano) e estiver completa; senão None (e aprovar essa entrada é recusado)."""
    meta = _ler_meta(raiz, e)
    return meta.get("data_captura") if _captura_valida(raiz, e, meta, exigir_ok=False) else None


def entradas_pendentes(plano: list[dict], raiz: str) -> list[dict]:
    """Entradas que ainda precisam ser capturadas. Ficam de fora os buracos e as entradas que já têm
    decisão do revisor (aprovadas ou rejeitadas): recapturar uma aprovada trocaria o conteúdo que foi
    visto. Para recapturar uma delas, limpe a decisão no plano. Fica pendente a entrada sem meta.json
    (captura interrompida) ou com meta.json ilegível, com status diferente de "ok", com algum arquivo
    faltando, ou cuja captura no disco é de outra URL ou de outro snapshot."""
    return [e for e in plano
            if not e.get("buraco") and e.get("aprovado") is None
            and not _captura_valida(raiz, e, _ler_meta(raiz, e), exigir_ok=True)]


def entradas_aprovadas(plano: list[dict], raiz: str) -> list[dict]:
    """As entradas que podem entrar na base (etapa 4): aprovadas, com a captura no disco completa,
    desta mesma URL e snapshot, e ainda a MESMA captura que o revisor viu (data_captura igual à
    registrada na aprovação)."""
    aprovadas = []
    for e in plano:
        if e.get("buraco") or e.get("aprovado") is not True:
            continue
        meta = _ler_meta(raiz, e)
        if (_captura_valida(raiz, e, meta, exigir_ok=False)
                and meta.get("data_captura") == e.get("aprovado_captura")):
            aprovadas.append(e)
    return aprovadas


# ---------------------------------------------------------------- resoluções extras

def meta_extra_caminho(raiz: str, id_: str, resolucao: str) -> str:
    """Metadados da captura de uma resolução extra: <pasta da entrada>/extra_<resolucao>.json."""
    return os.path.join(pasta_entrada(raiz, id_), f"extra_{resolucao}.json")


def arquivos_extra(resolucao: str) -> list[str]:
    """Arquivos que a captura de uma resolução extra grava na pasta da entrada."""
    return [f"shot_{resolucao}.png", f"dom_{resolucao}.html"]


def _ler_meta_extra(raiz: str, e: dict, resolucao: str) -> dict | None:
    try:
        with open(meta_extra_caminho(raiz, e["id"], resolucao), encoding="utf-8") as f:
            meta = json.load(f)
        return meta if isinstance(meta, dict) else None
    except (OSError, ValueError):
        return None


def _extra_valido(raiz: str, e: dict, resolucao: str, meta: dict | None, exigir_ok: bool) -> bool:
    """A captura extra no disco é desta entrada (mesmo snapshot) e está completa (e com status ok)?"""
    if meta is None or not _mesmo_snapshot({**meta, "origem": e.get("origem")}, e):
        return False
    pasta = pasta_entrada(raiz, e["id"])
    if not all(os.path.exists(os.path.join(pasta, a)) for a in arquivos_extra(resolucao)):
        return False
    return not exigir_ok or meta.get("status") == "ok"


def data_captura_extra_valida(raiz: str, e: dict, resolucao: str) -> str | None:
    """`data_captura` da captura extra no disco, só se ela for deste snapshot e estiver completa."""
    meta = _ler_meta_extra(raiz, e, resolucao)
    return meta.get("data_captura") if _extra_valido(raiz, e, resolucao, meta, exigir_ok=False) else None


def extras_pendentes(plano: list[dict], raiz: str, resolucao: str) -> list[dict]:
    """Entradas aprovadas (e válidas) que ainda precisam da captura nessa resolução extra: sem decisão
    nela e sem uma captura extra completa, deste snapshot, com status ok. Rejeitadas, a revisar e
    buracos ficam de fora: só um template aprovado ganha outra resolução."""
    return [e for e in entradas_aprovadas(plano, raiz)
            if (e.get("extras") or {}).get(resolucao, {}).get("aprovado") is None
            and not _extra_valido(raiz, e, resolucao, _ler_meta_extra(raiz, e, resolucao), exigir_ok=True)]


def marcar_aprovacao_extra(plano: list[dict], id_: str, resolucao: str, aprovado: bool, motivo: str = "",
                           data_captura: str | None = None) -> None:
    """Registra a decisão sobre uma resolução extra de uma entrada, junto com a captura vista. Id
    desconhecido lança KeyError. Resolução que não é extra, buraco, entrada principal não aprovada ou
    aprovar o que não foi capturado lançam ValueError."""
    if resolucao not in RESOLUCOES_EXTRAS:
        raise ValueError(f"{resolucao} não é uma resolução extra (use {sorted(RESOLUCOES_EXTRAS)})")
    for e in plano:
        if e["id"] == id_:
            if e.get("buraco"):
                raise ValueError(f"{id_} é um buraco (não há template para aprovar ou rejeitar)")
            if e.get("aprovado") is not True:
                raise ValueError(f"{id_}: a entrada precisa estar aprovada antes de decidir uma resolução extra")
            if aprovado and data_captura is None:
                raise ValueError(f"{id_} ainda não foi capturada em {resolucao}; não dá para aprovar o que não foi visto")
            e.setdefault("extras", {})[resolucao] = {"aprovado": aprovado, "motivo": motivo,
                                                    "aprovado_captura": data_captura}
            return
    raise KeyError(id_)


def templates_aprovados(plano: list[dict], raiz: str) -> list[tuple[dict, str]]:
    """Pares (entrada, resolução) que entram na base (etapas 3 e 4): as resoluções da captura principal
    de cada entrada de `entradas_aprovadas` e cada resolução extra aprovada cuja captura no disco é deste
    snapshot, está completa e é a mesma que o revisor viu."""
    pares = []
    for e in entradas_aprovadas(plano, raiz):
        pares += [(e, r) for r in RESOLUCOES]
        for r, decisao in (e.get("extras") or {}).items():
            if r not in RESOLUCOES_EXTRAS or decisao.get("aprovado") is not True:
                continue
            meta = _ler_meta_extra(raiz, e, r)
            if (_extra_valido(raiz, e, r, meta, exigir_ok=False)
                    and meta.get("data_captura") == decisao.get("aprovado_captura")):
                pares.append((e, r))
    return pares


# ---------------------------------------------------------------- revisão (fase "revisar")

def marcar_aprovacao(plano: list[dict], id_: str, aprovado: bool, motivo: str = "",
                     data_captura: str | None = None) -> None:
    """Registra no plano a decisão do revisor sobre uma entrada, junto com QUAL captura foi vista
    (`data_captura` do meta.json). Id desconhecido lança KeyError; buraco, ou aprovar algo que ainda
    não foi capturado, lança ValueError."""
    for e in plano:
        if e["id"] == id_:
            if e.get("buraco"):
                raise ValueError(f"{id_} é um buraco (não há template para aprovar ou rejeitar)")
            if aprovado and data_captura is None:
                raise ValueError(f"{id_} ainda não foi capturada; não dá para aprovar o que não foi visto")
            e["aprovado"], e["motivo"], e["aprovado_captura"] = aprovado, motivo, data_captura
            return
    raise KeyError(id_)


def _data(ts: str) -> str:
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def _celula_revisao(e: dict, meta: dict | None) -> str:
    if e.get("buraco"):
        return f'<td class="buraco">buraco: {escape(e["buraco"])}</td>'
    partes = []
    if meta is None:
        partes.append('<div class="status">não capturado</div>')
    else:
        resolucoes = meta.get("resolucoes", {})
        for r in RESOLUCOES:
            shot = f'{escape(e["id"])}/shot_{r}.png'
            partes.append(f'<a href="{shot}"><img src="{shot}" width="160" alt="{r}" title="{r}"></a>')
        for r, v in resolucoes.items():
            status = escape(str(v.get("status", "?")))
            classe = "" if v.get("status") == "ok" else ' class="falha"'
            partes.append(f'<div{classe}>{r}: {status}</div>')
            if v.get("residuos_wayback"):
                partes.append(f'<div class="falha">{r}: {v["residuos_wayback"]} vestígios do Wayback no DOM</div>')
        efetivos = sorted({v["timestamp_efetivo"] for v in resolucoes.values() if v.get("timestamp_efetivo")})
        for ts in efetivos:
            if e.get("origem") == "wayback" and e.get("anos_alvo") and fora_da_janela(ts, e["anos_alvo"]):
                partes.append(f'<div class="falha">snapshot exibido fora da janela: {_data(ts)}</div>')
            elif ts != e.get("timestamp"):
                partes.append(f'<div class="status">snapshot exibido: {_data(ts)}</div>')
        if meta.get("url_snapshot"):
            partes.append(f'<a href="{escape(meta["url_snapshot"])}">snapshot no Wayback</a>')
    partes.append(f'<div class="id">{escape(e["id"])}</div>')
    if e.get("aprovado") is True:
        if meta is not None and meta.get("data_captura") == e.get("aprovado_captura"):
            classe, estado = "aprovado", "aprovado"
        else:
            classe, estado = "vencida", "aprovação vencida: a captura mudou depois da aprovação"
    elif e.get("aprovado") is False:
        classe, estado = "rejeitado", f"rejeitado: {e.get('motivo', '')}"
    else:
        classe, estado = "", "a revisar"
    partes.append(f'<div class="estado">{escape(estado)}</div>')
    return f'<td class="{classe}">{"".join(partes)}</td>'


_COLUNAS_REVISAO = [str(a) for a in ANOS_PADRAO] + ["ao vivo"]


def _grade_revisao(plano: list[dict]) -> dict[tuple[str, str], dict[str, dict]]:
    """Uma linha por entidade/variante, uma coluna por ano-alvo e uma para a captura ao vivo."""
    grade: dict[tuple[str, str], dict[str, dict]] = {}
    for e in plano:
        linha = grade.setdefault((e["entidade"], e["variante"]), {})
        for coluna in (["ao vivo"] if e["origem"] == "ao_vivo" else [str(a) for a in e["anos_alvo"]]):
            linha[coluna] = e  # um snapshot que cobre dois anos aparece nas duas colunas
    return grade


def _celula_extra(e: dict, meta: dict | None, resolucao: str) -> str:
    if e.get("buraco") or e.get("aprovado") is not True:
        return '<td class="vazio">fora da base</td>'
    partes = []
    if meta is None:
        partes.append('<div class="status">não capturado</div>')
    else:
        shot = f'{escape(e["id"])}/shot_{resolucao}.png'
        partes.append(f'<a href="{shot}"><img src="{shot}" width="200" alt="{resolucao}"></a>')
        status = meta.get("status", "?")
        partes.append(f'<div{"" if status == "ok" else " class=\"falha\""}>{escape(str(status))}</div>')
        ts = meta.get("timestamp_efetivo")
        if ts and e.get("origem") == "wayback" and e.get("anos_alvo") and fora_da_janela(ts, e["anos_alvo"]):
            partes.append(f'<div class="falha">snapshot exibido fora da janela: {_data(ts)}</div>')
    partes.append(f'<div class="id">{escape(e["id"])}</div>')
    decisao = (e.get("extras") or {}).get(resolucao) or {}
    if decisao.get("aprovado") is True:
        vale = meta is not None and meta.get("data_captura") == decisao.get("aprovado_captura")
        classe, estado = ("aprovado", "aprovado") if vale else ("vencida", "aprovação vencida: a captura mudou")
    elif decisao.get("aprovado") is False:
        classe, estado = "rejeitado", f"rejeitado: {decisao.get('motivo', '')}"
    else:
        classe, estado = "", "a revisar"
    partes.append(f'<div class="estado">{escape(estado)}</div>')
    return f'<td class="{classe}">{"".join(partes)}</td>'


def gerar_revisao_extra_html(plano: list[dict], metas_extras: dict[str, dict], resolucao: str) -> str:
    """Página de revisão de uma resolução extra: a mesma grade da revisão principal, com a miniatura só
    dessa resolução e só para as entradas aprovadas (as outras não ganham resolução extra).
    `metas_extras` é indexado pelo id da entrada (conteúdo do extra_<resolucao>.json)."""
    grade = _grade_revisao(plano)
    cabecalho = "".join(f"<th>{c}</th>" for c in _COLUNAS_REVISAO)
    linhas = []
    for (entidade, variante), celulas in grade.items():
        tds = "".join(_celula_extra(celulas[c], metas_extras.get(celulas[c]["id"]), resolucao) if c in celulas
                      else '<td class="vazio"></td>' for c in _COLUNAS_REVISAO)
        linhas.append(f"<tr><th>{escape(entidade)}<br><small>{escape(variante)}</small></th>{tds}</tr>")
    return f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8"><title>Revisão dos templates em {resolucao}</title>
<style>{_ESTILO_REVISAO}</style></head><body>
<h1>Revisão dos templates em {resolucao}</h1>
<p>Só as entradas já aprovadas aparecem. Para registrar a decisão nesta resolução:
<code>python scripts/capturar_templates.py aprovar --resolucao {resolucao} --plano &lt;plano&gt; --raiz &lt;pasta&gt; ID [ID ...]</code>
ou <code>python scripts/capturar_templates.py rejeitar --resolucao {resolucao} --plano &lt;plano&gt; --raiz &lt;pasta&gt; ID --motivo "..."</code>.</p>
<table><thead><tr><th>entidade</th>{cabecalho}</tr></thead>
<tbody>{"".join(linhas)}</tbody></table>
</body></html>
"""


_ESTILO_REVISAO = """
 body { font-family: system-ui, sans-serif; margin: 16px; color: #222; background: #fafafa; }
 table { border-collapse: collapse; }
 th, td { border: 1px solid #ccc; padding: 6px; vertical-align: top; font-size: 12px; background: #fff; }
 thead th { position: sticky; top: 0; background: #eee; }
 td.aprovado { outline: 3px solid #2e7d32; } td.rejeitado { outline: 3px solid #c62828; }
 td.vencida { outline: 3px dashed #ef6c00; }
 td.buraco, td.vazio { background: #f0f0f0; color: #777; }
 .id { font-family: monospace; color: #555; } .estado { font-weight: bold; }
 .falha { color: #c62828; font-weight: bold; }
 code { background: #eee; padding: 1px 4px; }
"""


def gerar_revisao_html(plano: list[dict], metas: dict[str, dict]) -> str:
    """Página de revisão: uma linha por entidade/variante, uma coluna por ano-alvo e uma para a captura
    ao vivo. Cada célula traz a miniatura (caminho relativo à pasta das capturas), o status de cada
    resolução, o link do snapshot e o estado da aprovação. `metas` é indexado pelo id da entrada."""
    colunas = _COLUNAS_REVISAO
    grade = _grade_revisao(plano)

    contagem = {"a revisar": 0, "aprovados": 0, "aprovações vencidas": 0, "rejeitados": 0, "buracos": 0}
    for e in plano:
        if e.get("buraco"):
            chave = "buracos"
        elif e.get("aprovado") is True:
            meta = metas.get(e["id"])
            vale = meta is not None and meta.get("data_captura") == e.get("aprovado_captura")
            chave = "aprovados" if vale else "aprovações vencidas"
        else:
            chave = "rejeitados" if e.get("aprovado") is False else "a revisar"
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
<style>{_ESTILO_REVISAO}</style></head><body>
<h1>Revisão dos templates</h1>
<p>{resumo}</p>
<p>Cada célula mostra as duas resoluções (1280x960 e 1366x768). Para registrar a decisão:
<code>python scripts/capturar_templates.py aprovar --plano &lt;plano&gt; --raiz &lt;pasta&gt; ID [ID ...]</code>
ou <code>python scripts/capturar_templates.py rejeitar --plano &lt;plano&gt; --raiz &lt;pasta&gt; ID --motivo "..."</code>.
Só templates aprovados entram na base, e a aprovação vale só para a captura que foi vista.</p>
<table><thead><tr><th>entidade</th>{cabecalho}</tr></thead>
<tbody>{"".join(linhas)}</tbody></table>
</body></html>
"""
