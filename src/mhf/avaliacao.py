"""
Avaliação no conjunto de teste (etapa 6): intervalos de confiança, grupos de falso positivo, recortes,
datas dos templates e das amostras e tabelas LaTeX para o Cap. 5.

Desenho: docs/especificacoes/2026-11-22-avaliacao.md
"""

import re
from datetime import date, datetime
from functools import lru_cache

import numpy as np

DATA_CAPTURA_AO_VIVO = date(2026, 11, 21)
CORTE_PHISHPEDIA = date(2020, 10, 31)  # fim da coleta do Phishpedia
_DATA_AMOSTRA = re.compile(r"\+(\d{4})-(\d{2})-(\d{2})-")


# ---------------------------------------------------------------- intervalos de confiança

def ic_bootstrap(grupos, calcular, n=1000, semente=0, nivel=0.95):
    """Intervalo de confiança por bootstrap reamostrando grupos inteiros (estruturas de DOM) com reposição.

    `calcular(multiplicidade)` recebe, para cada amostra, quantas vezes o grupo dela foi sorteado (0, 1,
    2...) e devolve um dicionário de métricas; a multiplicidade entra como peso. Devolve {métrica: (inferior,
    superior)} nos percentis (1−nível)/2 e (1+nível)/2; métrica indefinida em todas as reamostras → NaN."""
    _, codigos = np.unique(np.asarray(grupos), return_inverse=True)
    n_grupos = int(codigos.max()) + 1 if len(codigos) else 0
    rng = np.random.default_rng(semente)
    valores = {}
    for _ in range(n):
        sorteio = rng.integers(0, n_grupos, size=n_grupos)
        mult = np.bincount(sorteio, minlength=n_grupos)[codigos].astype(float)
        for k, v in calcular(mult).items():
            valores.setdefault(k, []).append(v)
    a, b = 100 * (1 - nivel) / 2, 100 * (1 + nivel) / 2
    saida = {}
    for k, vs in valores.items():
        vs = np.asarray(vs, dtype=float)
        saida[k] = ((float("nan"), float("nan")) if np.isnan(vs).all()
                    else (float(np.nanpercentile(vs, a)), float(np.nanpercentile(vs, b))))
    return saida


# ---------------------------------------------------------------- grupos e recortes

def grupos_fpr(c):
    """Máscaras das páginas legítimas em que a taxa de falso positivo é medida: todas, por dataset, as
    páginas das próprias marcas de 𝒯 (domínio legítimo de alguma marca) e as mais parecidas com a base
    (décimo superior do cosseno máximo com os templates)."""
    legit = c["legitima"]
    corte = np.quantile(c["cos_max"][legit], 0.9) if legit.any() else np.inf
    return {"todas": legit,
            "phish360": legit & (c["dataset"] == "phish360"),
            "phishpedia_benign": legit & (c["dataset"] == "phishpedia_benign"),
            "paginas_das_marcas": legit & c["legit"].any(axis=1),
            "mais_parecidas": legit & (c["cos_max"] >= corte)}


def tipo_de_pagina(c, campos_senha):
    """"sem_dom" (s ausente), "com_senha" (algum campo de senha) ou "sem_senha", por amostra.
    `campos_senha(meta) -> int | None` devolve o número de campos de senha do DOM da amostra."""
    tipos = []
    for m, ausente in zip(c["meta"], c["s_ausente"]):
        if ausente:
            tipos.append("sem_dom")
        else:
            n = campos_senha(m)
            tipos.append("com_senha" if n else "sem_senha")
    return np.array(tipos)


def por_marca(c, decisao):
    """Revocação (por amostra e por estrutura) e top-1 nos detectados, por marca de 𝒯, com o número de
    amostras e de estruturas do teste. `decisao` é o resultado de cascata.aplicar_cascata."""
    ent = np.array(c["entidades"], dtype=object)
    grupos = np.array([m["grupo"] for m in c["meta"]])
    linhas = []
    for e in sorted({x for x in c["entidade_real"][c["phishing_T"]]}):
        alvo = c["phishing_T"] & (c["entidade_real"] == e)
        det = alvo & decisao["phishing"]
        w = c["pesos"][alvo]
        linhas.append({"entidade": e, "amostras": int(alvo.sum()), "estruturas": len(set(grupos[alvo])),
                       "revocacao": float(decisao["phishing"][alvo].mean()),
                       "revocacao_estrutura": float((w * decisao["phishing"][alvo]).sum() / w.sum()),
                       "top1_detectados": float((ent[decisao["entidade"][det]] == e).mean()) if det.any()
                       else float("nan")})
    return sorted(linhas, key=lambda l: -l["amostras"])


# ---------------------------------------------------------------- datas e filtros de templates

def data_da_amostra(id_):
    """Data de coleta de uma amostra do Phishpedia (no nome da pasta: "Marca+AAAA-MM-DD-..."), ou None."""
    m = _DATA_AMOSTRA.search(id_ or "")
    return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None


@lru_cache(maxsize=None)
def _data_template(origem, timestamp):
    if origem == "ao_vivo" or not timestamp:
        return DATA_CAPTURA_AO_VIVO
    return datetime.strptime(timestamp[:8], "%Y%m%d").date()


def data_do_template(item):
    """Data do snapshot do Wayback, ou a da captura ao vivo (21/11/2026)."""
    return _data_template(item.get("origem"), item.get("timestamp"))


def filtro_2026(meta, itens):
    """Só templates com data em 2026 (pelo timestamp). Para o experimento da base de 2026, use
    filtro_ano_alvo, que segue o ano planejado de cada snapshot."""
    return np.array([data_do_template(it).year == 2026 for it in itens])


def filtro_ano_alvo(ano, anos_por_entrada):
    """Só os templates planejados para `ano` (o campo `anos_alvo` do plano de snapshots) e os capturados ao
    vivo. O plano escolhe o snapshot mais próximo de 1º de janeiro, então muitos templates "de 2026" são de
    dezembro de 2025: filtrar pelo ano do timestamp tiraria esses templates (e a Amazon inteira) da base.
    Template fora do plano: vale o ano do timestamp."""
    def filtro(meta, itens):
        saida = []
        for it in itens:
            if it.get("origem") == "ao_vivo":
                saida.append(True)
                continue
            anos = anos_por_entrada.get(it["id"].split("@")[0])
            saida.append(ano in anos if anos else data_do_template(it).year == ano)
        return np.array(saida)
    return filtro


def mascarar_entidades(escores, entidades, excluidas):
    """Cópia dos escores com as colunas das `excluidas` em NaN (o detector "antes" de a marca existir)."""
    saida = np.array(escores, dtype=float, copy=True)
    for i, e in enumerate(entidades):
        if e in set(excluidas):
            saida[:, i] = np.nan
    return saida


def filtro_ate_data(corte_padrao=CORTE_PHISHPEDIA):
    """Base "da época": para um phishing com data, só templates até a data dele; para as demais amostras
    (legítimas, ou sem data reconhecível), só templates até `corte_padrao`."""
    def filtro(meta, itens):
        d = data_da_amostra(meta.get("id")) if meta.get("rotulo") == "phishing" else None
        corte = d or corte_padrao
        return np.array([data_do_template(it) <= corte for it in itens])
    return filtro


# ---------------------------------------------------------------- tabelas LaTeX

_ESPECIAIS = re.compile(r"(?<!\\)([&%_#$])")


def escapar(texto):
    """Escapa &, %, _, # e $ que ainda não estejam escapados."""
    return _ESPECIAIS.sub(r"\\\1", str(texto))


def numero(v, casas=3):
    """Número com vírgula decimal; NaN ou None → "—"."""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "—"
    return f"{v:.{casas}f}".replace(".", ",")


def percentual(v, casas=1):
    """Fração como porcentagem com vírgula decimal (escapada para LaTeX)."""
    return "—" if v is None or (isinstance(v, float) and np.isnan(v)) else numero(100 * v, casas) + "\\%"


def intervalo(ic, casas=3):
    """(inferior, superior) → "0,80–0,88"."""
    return "—" if ic is None or np.isnan(ic[0]) else f"{numero(ic[0], casas)}–{numero(ic[1], casas)}"


def tabela_latex(cabecalho, linhas, legenda, rotulo, fonte=None):
    """Tabela LaTeX com booktabs: a primeira coluna à esquerda, as demais à direita. As células são
    escapadas; o cabeçalho, não (pode ter matemática, como $\\mathcal{T}$)."""
    alinhamento = "l" + "r" * (len(cabecalho) - 1)
    corpo = [" & ".join(escapar(c) for c in l) + " \\\\" for l in linhas]
    partes = ["\\begin{table}[htb]", "\\centering", f"\\caption{{{legenda}}}", f"\\label{{{rotulo}}}",
              f"\\begin{{tabular}}{{{alinhamento}}}", "\\toprule", " & ".join(cabecalho) + " \\\\", "\\midrule",
              *corpo, "\\bottomrule", "\\end{tabular}"]
    if fonte:
        partes.append(f"\\fonte{{{fonte}}}")
    partes.append("\\end{table}")
    return "\n".join(partes) + "\n"
