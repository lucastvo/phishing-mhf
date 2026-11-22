"""
Passo 6 — avaliação no conjunto de teste: o detector principal e os experimentos E0–E5.

Uso:
    python scripts/avaliar.py --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl data/estrutural_phishpedia_benign.jsonl --saida data/avaliacao

    Ensaio (antes da rodada única no teste): a dobra 0 do desenvolvimento faz o papel do teste, e as dobras
    1 a 4 o do desenvolvimento; exercita todos os caminhos sem ler o teste. Use outra --saida.
    python scripts/avaliar.py ... --ensaio --saida data/avaliacao_ensaio

Experimentos (desenho, seção 4); todo treino e toda calibração usam só o desenvolvimento:
    E0  detector principal (data/modelos/boosting): métricas com intervalo de confiança, falso positivo por
        grupo, por marca, por dataset, por tipo de página, phishing fora de 𝒯 e sem marca, curva ROC;
    E1  ablação (h, e, s e combinações); E1b  regressão e Random Forest salvos; E2  Large e pHash de 256 bits;
    E3  com estágio 1 pelo pHash; E4a  base com os templates planejados para 2026; E4b  base da época
    (Phishpedia); E5  marca nova (classificador e limiar sem as marcas em que é medido).

Saídas em --saida: resultados.json (mesclado entre execuções: rodar de novo um experimento não apaga os
outros), relatorio.md, tabelas/*.tex e figuras/*.pdf, gerados a partir do JSON mesclado; registro.jsonl
ganha uma linha no início ("iniciado") e outra no fim ("concluido") de cada execução.

Desenho: docs/especificacoes/2026-11-22-avaliacao.md
"""

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np  # noqa: E402
from sklearn.metrics import roc_curve  # noqa: E402

from mhf import avaliacao, cascata, divisao, figuras, marcas, metricas, treino  # noqa: E402
from mhf import base as base_mod  # noqa: E402
from mhf.conjuntos import carregar_conjunto  # noqa: E402

SUPERCONJUNTO = ["sim_h64", "sim_h256", "cos_small", "cos_large", *cascata.SINAIS_S, "s_ausente"]
COMBINACOES = [("h",), ("e",), ("s",), ("h", "e"), ("h", "s"), ("e", "s"), ("h", "e", "s")]
EXPERIMENTOS = ["E0", "E1", "E1b", "E2", "E3", "E4a", "E4b", "E5"]
METRICAS = (("acuracia", "Acurácia"), ("precisao", "Precisão"), ("revocacao", "Revocação"), ("f1", "F1"),
            ("especificidade", "Especificidade"), ("fpr", "Taxa de falso positivo"),
            ("top1_detectados", "Marca certa nos phishings detectados"), ("auc", "AUC"))
_POR_ARRAY = ("X", "d1", "t1", "legit", "entidade_real", "phishing_T", "legitima", "fora_T", "s_ausente",
              "cos_max", "dobra", "dataset")


# ---------------------------------------------------------------- utilidades

def fatiar(c, nomes):
    """O conjunto com só as características `nomes` (subconjunto do superconjunto carregado)."""
    idx = [c["nomes"].index(n) for n in nomes]
    return {**c, "X": c["X"][:, :, idx], "nomes": list(nomes)}


def subconjunto(c, mascara):
    """As amostras de `mascara`, com o peso por estrutura recalculado dentro delas."""
    novo = {**c, "meta": [m for m, k in zip(c["meta"], mascara) if k]}
    for chave in _POR_ARRAY:
        novo[chave] = c[chave][mascara]
    novo["pesos"] = divisao.pesos_por_estrutura(novo["meta"]) if novo["meta"] else np.zeros(0)
    return novo


def decidir(c, escores, theta_h, tau):
    return cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], theta_h, tau)


def escore_da_amostra(c, escores):
    """Escore da amostra para a curva ROC e a AUC: o maior entre as marcas, zerado quando a página está
    no domínio legítimo da marca de maior escore (a checagem de domínio a libera de qualquer forma)."""
    validos = np.nan_to_num(escores, nan=-np.inf)
    melhor = np.argmax(validos, axis=1)
    e = np.maximum(validos[np.arange(len(melhor)), melhor], 0.0)
    return np.where(c["legit"][np.arange(len(melhor)), melhor], 0.0, e)


def metricas_ponderadas(c, decisao, escore, pesos):
    """Métricas da detecção restrita a 𝒯 (phishing de 𝒯 × legítimas) com pesos por amostra."""
    binario = (c["phishing_T"] | c["legitima"]) & (pesos > 0)
    b = metricas.binarias(c["phishing_T"][binario], decisao["phishing"][binario], pesos[binario])
    det = c["phishing_T"] & decisao["phishing"] & (pesos > 0)
    ent = np.array(c["entidades"], dtype=object)
    return {**{k: b[k] for k in ("acuracia", "precisao", "revocacao", "f1", "especificidade", "fpr")},
            "top1_detectados": metricas.top1(c["entidade_real"][det], ent[decisao["entidade"][det]], pesos[det])
            if det.any() else float("nan"),
            "auc": metricas.auc(c["phishing_T"][binario], escore[binario], pesos[binario])}


def grupos_de(c):
    return np.array([m["grupo"] for m in c["meta"]])


def roc_resumida(c, escores, pontos=300):
    """Curva ROC (phishing de 𝒯 × legítimas) com até `pontos` pontos, para guardar no JSON."""
    binario = c["phishing_T"] | c["legitima"]
    fpr, tpr, _ = roc_curve(c["phishing_T"][binario], escore_da_amostra(c, escores)[binario])
    idx = np.unique(np.linspace(0, len(fpr) - 1, min(pontos, len(fpr))).astype(int))
    return {"fpr": fpr[idx], "tpr": tpr[idx]}


def limpar(o):
    """Para JSON padrão: numpy → Python, NaN/inf → None, tuplas → listas."""
    if isinstance(o, dict):
        return {str(k): limpar(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [limpar(v) for v in o]
    if isinstance(o, np.ndarray):
        return limpar(o.tolist())
    if isinstance(o, (np.floating, float)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def sha256(caminho):
    with open(caminho, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _n(v):
    """None (do JSON) → NaN, para as funções de formatação."""
    return float("nan") if v is None else v


# ---------------------------------------------------------------- treino de uma configuração

class Rodada:
    """Treina e calibra uma configuração no desenvolvimento e pontua o teste."""

    def __init__(self, a):
        self.params = {"iteracoes": a.iteracoes, "arvores": a.arvores, "profundidade": a.profundidade or None,
                       "folha": a.folha, "n_jobs": a.n_jobs}
        self.alvo_fpr = a.alvo_fpr

    def __call__(self, dev, teste, tipo="boosting", estagio1="nenhum", excluidas=(), rotulo=""):
        """(calibração, escores do teste), ou (None, None) se o desenvolvimento não tiver pares positivos e
        negativos para treinar (ex.: uma base filtrada sem templates). Com `excluidas` (marca nova), as
        marcas ficam fora do treino e também da calibração: τ é escolhido como se elas não existissem."""
        _, y, _ = treino.pares_de_treino(dev, np.ones(len(dev["d1"]), dtype=bool), excluidas)
        if not y.any() or y.all():
            print(f"  {rotulo or tipo}: sem pares positivos e negativos para treinar", flush=True)
            return None, None
        t = time.perf_counter()
        oof = treino.escores_fora_da_dobra(dev, tipo, progresso=lambda s: None, entidades_excluidas=excluidas,
                                           **self.params)
        if excluidas:
            oof = avaliacao.mascarar_entidades(oof, dev["entidades"], excluidas)
        cal = treino.calibrar(dev, oof, self.alvo_fpr, 0.99, estagio1)
        modelo = treino.treinar_modelo(tipo, dev, np.ones(len(dev["d1"]), dtype=bool), excluidas, **self.params)
        escores = cascata.pontuar_amostras(modelo, teste["X"])
        print(f"  {rotulo or tipo}: {time.perf_counter() - t:.0f} s", flush=True)
        return cal, escores


def resumo(c, escores, cal):
    """Métricas da decisão completa no teste, por amostra e por estrutura (sem intervalo)."""
    m = treino.metricas_cascata(c, escores, cal.get("theta_h"), cal["tau"])
    dec = decidir(c, escores, cal.get("theta_h"), cal["tau"])
    esc = escore_da_amostra(c, escores)
    for nome, pesos in (("por_amostra", np.ones(len(esc))), ("por_estrutura", c["pesos"])):
        m[nome]["auc"] = metricas_ponderadas(c, dec, esc, pesos)["auc"]
    return m


# ---------------------------------------------------------------- E0

def experimento_principal(c, escores, cal, campos_senha, n_boot, semente):
    dec = decidir(c, escores, cal.get("theta_h"), cal["tau"])
    esc = escore_da_amostra(c, escores)
    grupos = grupos_de(c)
    um = np.ones(len(esc))
    geral = {}
    for nome, pesos in (("por_amostra", um), ("por_estrutura", c["pesos"])):
        valores = metricas_ponderadas(c, dec, esc, pesos)
        ic = avaliacao.ic_bootstrap(grupos, lambda mult, p=pesos: metricas_ponderadas(c, dec, esc, mult * p),
                                    n_boot, semente)
        geral[nome] = {**valores, "ic": ic}

    sinalizada = dec["phishing"]
    fpr = {}
    for nome, mk in avaliacao.grupos_fpr(c).items():
        if not mk.any():
            fpr[nome] = {"paginas": 0, "fpr": None, "ic": None}
            continue
        ic = avaliacao.ic_bootstrap(grupos[mk], lambda m, s=sinalizada[mk]: {"fpr": float((s * m).sum() / m.sum())
                                                                              if m.sum() else float("nan")},
                                    n_boot, semente)["fpr"]
        fpr[nome] = {"paginas": int(mk.sum()), "fpr": float(sinalizada[mk].mean()), "ic": ic}

    linhas_marca = avaliacao.por_marca(c, dec)
    for l in linhas_marca:
        alvo = c["phishing_T"] & (c["entidade_real"] == l["entidade"])
        l["ic"] = avaliacao.ic_bootstrap(grupos[alvo], lambda m, s=sinalizada[alvo]: {"r": float((s * m).sum() / m.sum())},
                                         n_boot, semente)["r"]

    datasets = {}
    for nome, mk in (("phish360", c["dataset"] == "phish360"),
                     ("phishpedia", np.char.startswith(c["dataset"].astype(str), "phishpedia"))):
        if mk.any():
            datasets[nome] = treino.metricas_cascata(c, escores, cal.get("theta_h"), cal["tau"], mk)

    tipos = avaliacao.tipo_de_pagina(c, campos_senha)
    por_tipo = {}
    for t in ("com_senha", "sem_senha", "sem_dom"):
        p, l = c["phishing_T"] & (tipos == t), c["legitima"] & (tipos == t)
        por_tipo[t] = {"phishing_T": int(p.sum()), "revocacao": float(sinalizada[p].mean()) if p.any() else None,
                       "legitimas": int(l.sum()), "fpr": float(sinalizada[l].mean()) if l.any() else None}

    estrato = np.array([m.get("estrato") for m in c["meta"]])
    fora = {}
    for nome in ("fora", "sem_marca"):
        mk = estrato == nome
        fora[nome] = {"paginas": int(mk.sum()), "sinalizadas": float(sinalizada[mk].mean()) if mk.any() else None}

    rotulo = np.array([m["rotulo"] for m in c["meta"]])
    todos = (rotulo == "phishing") | c["legitima"]
    completo = metricas.binarias((rotulo == "phishing")[todos], sinalizada[todos])
    return {"geral": geral, "fpr_grupos": fpr, "por_marca": linhas_marca, "por_dataset": datasets,
            "por_tipo": por_tipo, "fora_de_T": fora, "binario_completo": completo,
            "n": {"phishing_T": int(c["phishing_T"].sum()), "legitimas": int(c["legitima"].sum()),
                  "estruturas_phishing_T": len(set(grupos[c["phishing_T"]]))},
            "roc": roc_resumida(c, escores), "tau": cal["tau"]}


# ---------------------------------------------------------------- saídas (a partir do JSON mesclado)

class Saidas:
    def __init__(self, pasta, ensaio=False):
        self.pasta, self.ensaio, self.md = pasta, ensaio, []
        os.makedirs(os.path.join(pasta, "tabelas"), exist_ok=True)
        os.makedirs(os.path.join(pasta, "figuras"), exist_ok=True)

    def tabela(self, arquivo, cabecalho, linhas, legenda, rotulo):
        legenda = ("[ENSAIO, NÃO USAR NO TEXTO] " if self.ensaio else "") + legenda
        with open(os.path.join(self.pasta, "tabelas", arquivo), "w", encoding="utf-8") as f:
            f.write(avaliacao.tabela_latex(cabecalho, linhas, legenda, rotulo, fonte="Elaborada pelo autor."))
        sem_latex = lambda s: str(s).replace("\\%", "%")  # noqa: E731
        self.md += [f"## {legenda}", "", "| " + " | ".join(map(sem_latex, cabecalho)) + " |",
                    "|" + "---|" * len(cabecalho)]
        self.md += ["| " + " | ".join(map(sem_latex, l)) + " |" for l in linhas]
        self.md.append("")


def intervalo_pct(ic, casas=2):
    return "—" if ic is None or ic[0] is None else \
        f"{avaliacao.percentual(ic[0], casas)}–{avaliacao.percentual(ic[1], casas)}"


def linha_resumo(nome, m, extra=()):
    a, e = m["por_amostra"], m["por_estrutura"]
    return [nome, f"{avaliacao.numero(_n(a['auc']))} / {avaliacao.numero(_n(e['auc']))}",
            f"{avaliacao.numero(_n(a['revocacao']))} / {avaliacao.numero(_n(e['revocacao']))}",
            avaliacao.percentual(_n(a["fpr"]), 2), avaliacao.numero(_n(a["top1_detectados"])), *extra]


CAB_RESUMO = ["Configuração", "AUC (amostra / estrutura)", "Revocação (amostra / estrutura)",
              "Taxa de falso positivo", "Marca certa"]


def gerar_saidas(r, s):
    """Tabelas, relatório e figuras a partir dos resultados mesclados."""
    num, pct = avaliacao.numero, avaliacao.percentual
    curvas = {}
    if "E0" in r:
        e0 = r["E0"]
        g = e0["geral"]
        ic = lambda chave, k: g[chave]["ic"].get(k) if g[chave].get("ic") else None  # noqa: E731
        s.tabela("principal.tex", ["Métrica", "Por amostra", "IC 95\\%", "Por estrutura", "IC 95\\%"],
                 [[rot, num(_n(g["por_amostra"][k])), avaliacao.intervalo(ic("por_amostra", k)) if ic("por_amostra", k)
                   and ic("por_amostra", k)[0] is not None else "—",
                   num(_n(g["por_estrutura"][k])), avaliacao.intervalo(ic("por_estrutura", k))
                   if ic("por_estrutura", k) and ic("por_estrutura", k)[0] is not None else "—"]
                  for k, rot in METRICAS],
                 "Detector principal no conjunto de teste (gradient boosting, h+e+s, estágio único)", "tab:principal")
        nomes = {"todas": "Todas as legítimas", "phish360": "Legítimas do Phish360",
                 "phishpedia_benign": "Phishpedia benign", "paginas_das_marcas": "Páginas das próprias marcas",
                 "mais_parecidas": "10\\% mais parecidas com a base"}
        s.tabela("fpr_grupos.tex", ["Grupo de páginas legítimas", "Páginas", "Taxa de falso positivo", "IC 95\\%"],
                 [[nomes[k], str(v["paginas"]), pct(_n(v["fpr"]), 2), intervalo_pct(v["ic"])]
                  for k, v in e0["fpr_grupos"].items()],
                 "Taxa de falso positivo por grupo de páginas legítimas", "tab:fpr-grupos")
        s.tabela("por_marca.tex", ["Marca", "Amostras", "Estruturas", "Revocação", "IC 95\\%",
                                   "Revocação (estrutura)", "Marca certa"],
                 [[l["entidade"], str(l["amostras"]), str(l["estruturas"]), num(_n(l["revocacao"])),
                   avaliacao.intervalo(l["ic"]) if l.get("ic") and l["ic"][0] is not None else "—",
                   num(_n(l["revocacao_estrutura"])), num(_n(l["top1_detectados"]))] for l in e0["por_marca"]],
                 "Revocação e marca certa nos detectados, por marca", "tab:por-marca")
        rot_t = {"com_senha": "Com campo de senha", "sem_senha": "Sem campo de senha", "sem_dom": "Sem DOM útil"}
        s.tabela("por_tipo.tex", ["Tipo de página", "Phishings", "Revocação", "Legítimas", "Taxa de falso positivo"],
                 [[rot_t[k], str(v["phishing_T"]), num(_n(v["revocacao"])), str(v["legitimas"]), pct(_n(v["fpr"]), 2)]
                  for k, v in e0["por_tipo"].items()],
                 "Resultado por tipo de página", "tab:por-tipo")
        s.tabela("por_dataset.tex", ["Dataset", "Phishings de marcas da base", "Legítimas", "Revocação",
                                     "Revocação (estrutura)", "Taxa de falso positivo", "Marca certa"],
                 [[ds, str(m["n"]["phishing_T"]), str(m["n"]["legitimas"]), num(_n(m["por_amostra"]["revocacao"])),
                   num(_n(m["por_estrutura"]["revocacao"])), pct(_n(m["por_amostra"]["fpr"]), 2),
                   num(_n(m["por_amostra"]["top1_detectados"]))] for ds, m in e0["por_dataset"].items()],
                 "Resultado por dataset (no Phish360, os phishings de marcas da base no teste são só os grupos do "
                 "trainval que compartilham estrutura com o test)", "tab:por-dataset")
        f, b = e0["fora_de_T"], e0["binario_completo"]
        s.tabela("fora_de_T.tex", ["Grupo", "Páginas", "Sinalizadas como phishing"],
                 [["Phishing de marcas fora da base", str(f["fora"]["paginas"]), pct(_n(f["fora"]["sinalizadas"]))],
                  ["Phishing sem marca (test do Phish360)", str(f["sem_marca"]["paginas"]),
                   pct(_n(f["sem_marca"]["sinalizadas"]))],
                  ["Detecção binária com todo phishing: revocação", "—", pct(_n(b["revocacao"]))],
                  ["Detecção binária com todo phishing: precisão", "—", pct(_n(b["precisao"]))]],
                 "Phishing de marcas fora da base e detecção com todo phishing como positivo", "tab:fora-da-base")
        figuras.barras_por_marca([{**l, "revocacao": _n(l["revocacao"]),
                                   "ic": tuple(_n(x) for x in (l.get("ic") or (None, None)))}
                                  for l in e0["por_marca"]], os.path.join(s.pasta, "figuras", "por_marca.pdf"))
        curvas["h+e+s (principal)"] = (e0["roc"]["fpr"], e0["roc"]["tpr"], _n(g["por_amostra"]["auc"]))

    linhas = []
    for rot, m in r.get("E1", {}).items():
        if "por_amostra" in m:
            linhas.append(linha_resumo(f"Sinais {rot}", m))
            if rot in ("h", "e", "s") and m.get("roc"):
                curvas[f"só {rot}"] = (m["roc"]["fpr"], m["roc"]["tpr"], _n(m["por_amostra"]["auc"]))
    for tipo, rot in (("regressao", "Regressão logística"), ("floresta", "Random Forest compacta")):
        if tipo in r.get("E1b", {}):
            linhas.append(linha_resumo(f"{rot} (h+e+s)", r["E1b"][tipo]))
    for rot, m in r.get("E2", {}).items():
        if "por_amostra" in m:
            linhas.append(linha_resumo(f"h+e+s com {rot}", m))
    if linhas:
        s.tabela("ablacao.tex", CAB_RESUMO, linhas, "Ablação dos sinais, classificadores e variações (teste)",
                 "tab:ablacao")

    e3 = r.get("E3", {})
    if "com_estagio1" in e3:
        com, sem = e3["com_estagio1"], e3["sem_estagio1"]
        s.tabela("estagio1.tex", CAB_RESUMO + ["Legítimas liberadas no estágio 1"],
                 [linha_resumo("Estágio único (principal)", sem, [pct(0.0)]),
                  linha_resumo(f"Com estágio 1 (limiar de {com['theta_h']} bits no pHash)", com,
                               [pct(_n(com["por_amostra"]["legitimas_liberadas_estagio1"]))])],
                 "Com e sem o estágio 1 pelo pHash (teste)", "tab:estagio1")

    temporal, nota = [], ""
    e4a, e4b = r.get("E4a", {}), r.get("E4b", {})
    if "base_2026" in e4a:
        temporal += [linha_resumo("Base completa (2019–2026)", e4a["base_completa"]),
                     linha_resumo("Só templates planejados para 2026", e4a["base_2026"])]
        if e4a.get("marcas_sem_template_2026"):
            nota = "; sem template na base de 2026: " + ", ".join(e4a["marcas_sem_template_2026"])
    if "epoca" in e4b:
        temporal += [linha_resumo("Phishpedia: base completa", e4b["completa"]),
                     linha_resumo("Phishpedia: só templates anteriores à amostra", e4b["epoca"])]
    if temporal:
        s.tabela("temporal.tex", CAB_RESUMO, temporal, f"Defasagem temporal da base de templates (teste){nota}",
                 "tab:temporal")

    e5 = r.get("E5", {})
    if e5.get("grupos"):
        linhas = [[", ".join(g["marcas"]), str(g.get("phishings", 0)), num(_n(g.get("revocacao_marca_nova"))),
                   num(_n(g.get("revocacao_principal"))), num(_n(g.get("top1_marca_nova"))),
                   pct(_n(g.get("fpr_marca_nova")), 2)] for g in e5["grupos"]]
        if e5.get("total"):
            t = e5["total"]
            linhas.append(["Todas", str(t["phishings"]), num(t["revocacao_marca_nova"]), num(t["revocacao_principal"]),
                           "—", "—"])
        s.tabela("marca_nova.tex", ["Marcas fora do treino", "Phishings", "Revocação (marca nova)",
                                    "Revocação (principal)", "Marca certa (marca nova)", "Falso positivo"], linhas,
                 "Marcas que o classificador não viu no treino nem na calibração (teste)", "tab:marca-nova")

    if curvas:
        figuras.roc(curvas, os.path.join(s.pasta, "figuras", "roc.pdf"))
    titulo = "# Avaliação no conjunto de teste" + (" — ENSAIO (não usar no texto)" if s.ensaio else "")
    with open(os.path.join(s.pasta, "relatorio.md"), "w", encoding="utf-8") as f:
        f.write(titulo + "\n\n" + "\n".join(s.md))


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--tabelas", nargs="+", required=True)
    p.add_argument("--estrutural", nargs="+", required=True,
                   help="JSONL estruturais (estrutural_<dataset>.jsonl), casados com as tabelas pelo nome")
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--plano", default="config/templates_snapshots.json", help="anos planejados de cada snapshot")
    p.add_argument("--modelos", default="data/modelos")
    p.add_argument("--saida", default="data/avaliacao")
    p.add_argument("--experimentos", default=",".join(EXPERIMENTOS))
    p.add_argument("--ensaio", action="store_true",
                   help="a dobra 0 do desenvolvimento no papel do teste (não lê o teste)")
    p.add_argument("--bootstrap", type=int, default=1000)
    p.add_argument("--semente", type=int, default=0)
    p.add_argument("--alvo-fpr", type=float, default=0.01)
    p.add_argument("--iteracoes", type=int, default=150)
    p.add_argument("--arvores", type=int, default=100)
    p.add_argument("--profundidade", type=int, default=12)
    p.add_argument("--folha", type=int, default=50)
    p.add_argument("--n-jobs", type=int, default=4)
    a = p.parse_args()

    inicio = time.perf_counter()
    exps = [e for e in a.experimentos.split(",") if e]
    if not set(exps) <= set(EXPERIMENTOS):
        p.error(f"--experimentos deve conter só {EXPERIMENTOS}")
    datasets = {os.path.basename(t).removeprefix("similaridades_") for t in a.tabelas}
    senha = {}
    for arq in a.estrutural:
        ds = os.path.basename(arq).removeprefix("estrutural_").removesuffix(".jsonl")
        if ds not in datasets:
            p.error(f"{arq}: o nome deve ser estrutural_<dataset>.jsonl, com um dataset de --tabelas {sorted(datasets)}")
        with open(arq, encoding="utf-8") as f:
            for d in map(json.loads, f):
                senha[(ds, d["id"])] = d.get("contagens", {}).get("campos_senha")
    campos_senha = lambda m: senha.get((m["dataset"], m["id"]))  # noqa: E731
    anos_plano = {}
    if os.path.exists(a.plano):
        with open(a.plano, encoding="utf-8") as f:
            anos_plano = {e["id"]: e.get("anos_alvo") for e in json.load(f)}

    b = base_mod.Base.carregar(a.base)
    tabela_marcas = marcas.ler_tabela(a.marcas)
    div = divisao.ler_divisao(a.divisao)
    principal, info_p = cascata.carregar_modelo(os.path.join(a.modelos, "boosting"))
    nomes_p = info_p["caracteristicas"]["nomes"]
    if not a.ensaio and info_p.get("treino", {}).get("divisao_sha256") not in (None, sha256(a.divisao)):
        p.error("o detector principal foi treinado com outra divisão (divisao_sha256 diferente)")

    os.makedirs(a.saida, exist_ok=True)
    caminho_res = os.path.join(a.saida, "resultados.json")
    anteriores = {}
    if os.path.exists(caminho_res):
        with open(caminho_res, encoding="utf-8") as f:
            anteriores = json.load(f)
        if bool(anteriores.get("_ensaio")) != a.ensaio:
            p.error(f"{a.saida} tem resultados de {'ensaio' if anteriores.get('_ensaio') else 'teste'}; use outra --saida")
    registro = {"experimentos": exps, "ensaio": a.ensaio, "divisao_sha256": sha256(a.divisao),
                "base_meta_sha256": sha256(os.path.join(a.base, "base_meta.json")),
                "modelos_sha256": {t: sha256(os.path.join(a.modelos, t, "modelo.json"))
                                   for t in ("boosting", "regressao", "floresta")
                                   if os.path.exists(os.path.join(a.modelos, t, "modelo.json"))},
                "bootstrap": a.bootstrap, "semente": a.semente}

    def registrar(status, **extra):
        with open(os.path.join(a.saida, "registro.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"status": status, "em": datetime.now().isoformat(timespec="seconds"),
                                **registro, **extra}, ensure_ascii=False) + "\n")

    registrar("iniciado")

    def par(prefixos, nomes, filtro=None):
        """(desenvolvimento, teste); no ensaio, (dobras 1–4, dobra 0) do desenvolvimento."""
        if not a.ensaio:
            return (carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, nomes, filtro),
                    carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.TESTE, nomes, filtro))
        tudo = carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, nomes, filtro)
        return subconjunto(tudo, tudo["dobra"] != 0), subconjunto(tudo, tudo["dobra"] == 0)

    print("Carregando desenvolvimento e teste" + (" (ENSAIO: dobra 0 no papel do teste)" if a.ensaio else "") + "...",
          flush=True)
    dev, teste = par(a.tabelas, SUPERCONJUNTO)
    print(f"Teste: {len(teste['meta'])} amostras ({int(teste['phishing_T'].sum())} phishings de 𝒯, "
          f"{int(teste['legitima'].sum())} legítimas)", flush=True)
    if list(info_p["entidades"]) != list(teste["entidades"]):
        p.error("as marcas do detector principal não batem com as da base")
    rodada = Rodada(a)
    teste_p = fatiar(teste, nomes_p)
    if a.ensaio:  # o detector salvo viu a dobra 0 no treino: no ensaio, o principal é retreinado sem ela
        cal_p, escores_p = rodada(fatiar(dev, nomes_p), teste_p, rotulo="principal (ensaio)")
    else:
        cal_p, escores_p = info_p["cascata"], cascata.pontuar_amostras(principal, teste_p["X"])
    r = {"_ensaio": a.ensaio}

    if "E0" in exps:
        print("E0: detector principal", flush=True)
        r["E0"] = experimento_principal(teste_p, escores_p, cal_p, campos_senha, a.bootstrap, a.semente)
    if "E1" in exps:
        print("E1: ablação", flush=True)
        r["E1"] = {}
        for comb in COMBINACOES:
            nomes, rot = cascata.nomes_caracteristicas(comb), "+".join(comb)
            ct = fatiar(teste, nomes)
            cal, esc = rodada(fatiar(dev, nomes), ct, rotulo=rot)
            r["E1"][rot] = {"sem_pares_no_treino": True} if cal is None else \
                {**resumo(ct, esc, cal), "tau": cal["tau"], "roc": roc_resumida(ct, esc)}
    if "E1b" in exps:
        print("E1b: regressão e Random Forest salvos", flush=True)
        r["E1b"] = {}
        for tipo in ("regressao", "floresta"):
            modelo, info = cascata.carregar_modelo(os.path.join(a.modelos, tipo))
            ct = fatiar(teste, info["caracteristicas"]["nomes"])
            r["E1b"][tipo] = resumo(ct, cascata.pontuar_amostras(modelo, ct["X"]), info["cascata"])
    if "E2" in exps:
        print("E2: variações dos sinais", flush=True)
        r["E2"] = {}
        for rot, nomes in (("embedding Large", cascata.nomes_caracteristicas(embedding="large")),
                           ("pHash de 256 bits", cascata.nomes_caracteristicas(hash_bits=256))):
            ct = fatiar(teste, nomes)
            cal, esc = rodada(fatiar(dev, nomes), ct, rotulo=rot)
            r["E2"][rot] = {"sem_pares_no_treino": True} if cal is None else resumo(ct, esc, cal)
    if "E3" in exps:
        print("E3: com estágio 1", flush=True)
        cal, esc = rodada(fatiar(dev, nomes_p), teste_p, estagio1="phash", rotulo="estágio 1")
        r["E3"] = {"sem_pares_no_treino": True} if cal is None else \
            {"com_estagio1": {**resumo(teste_p, esc, cal), "theta_h": cal["theta_h"]},
             "sem_estagio1": resumo(teste_p, escores_p, cal_p)}
    if "E4a" in exps:
        print("E4a: base com os templates planejados para 2026", flush=True)
        filtro = avaliacao.filtro_ano_alvo(2026, anos_plano)
        com_2026 = {it["entidade"] for it, ok in zip(b.itens, filtro({}, b.itens)) if ok}
        r["E4a"] = {"marcas_sem_template_2026": sorted({it["entidade"] for it in b.itens} - com_2026),
                    "base_completa": resumo(teste_p, escores_p, cal_p)}
        dev26, teste26 = par(a.tabelas, nomes_p, filtro)
        cal, esc = rodada(dev26, teste26, rotulo="base de 2026")
        if cal is None:
            r["E4a"]["sem_pares_no_treino"] = True
        else:
            r["E4a"]["base_2026"] = resumo(teste26, esc, cal)
    if "E4b" in exps:
        print("E4b: base da época (Phishpedia)", flush=True)
        prefixos = [t for t in a.tabelas if "phishpedia" in os.path.basename(t)]
        com_data = [k for k in div if k[0].startswith("phishpedia") and avaliacao.data_da_amostra(k[1])]
        if not prefixos or not com_data:
            r["E4b"] = {"sem_amostras_com_data": True}
        else:
            dev_c, teste_c = par(prefixos, nomes_p)
            dev_e, teste_e = par(prefixos, nomes_p, avaliacao.filtro_ate_data())
            cal_c, esc_c = rodada(dev_c, teste_c, rotulo="Phishpedia, base completa")
            cal_e, esc_e = rodada(dev_e, teste_e, rotulo="Phishpedia, base da época")
            r["E4b"] = {"sem_pares_no_treino": True} if cal_c is None or cal_e is None else \
                {"completa": resumo(teste_c, esc_c, cal_c), "epoca": resumo(teste_e, esc_e, cal_e)}
    if "E5" in exps:
        print("E5: marca nova", flush=True)
        dec_p = decidir(teste_p, escores_p, cal_p.get("theta_h"), cal_p["tau"])
        ents = sorted({it["entidade"] for it in b.itens})
        rng = np.random.default_rng(a.semente)
        grupos_marcas = [list(g) for g in np.array_split(rng.permutation(ents), min(4, len(ents)))]
        r["E5"] = {"grupos": []}
        tot = {"n": 0, "nova": 0.0, "principal": 0.0}
        ent = np.array(teste_p["entidades"], dtype=object)
        for g in grupos_marcas:
            alvo = teste_p["phishing_T"] & np.isin(teste_p["entidade_real"].astype(str), g)
            if not alvo.any():
                r["E5"]["grupos"].append({"marcas": g, "sem_phishing_no_teste": True})
                continue
            cal, esc = rodada(fatiar(dev, nomes_p), teste_p, excluidas=tuple(g), rotulo=f"sem {', '.join(g)}")
            if cal is None:
                r["E5"]["grupos"].append({"marcas": g, "sem_pares_no_treino": True})
                continue
            dec = decidir(teste_p, esc, None, cal["tau"])
            det = alvo & dec["phishing"]
            item = {"marcas": g, "phishings": int(alvo.sum()), "tau": cal["tau"],
                    "revocacao_marca_nova": float(dec["phishing"][alvo].mean()),
                    "revocacao_principal": float(dec_p["phishing"][alvo].mean()),
                    "top1_marca_nova": float((ent[dec["entidade"][det]] == teste_p["entidade_real"][det]).mean())
                    if det.any() else None,
                    "fpr_marca_nova": float(dec["phishing"][teste_p["legitima"]].mean())}
            r["E5"]["grupos"].append(item)
            tot["n"] += item["phishings"]
            tot["nova"] += item["revocacao_marca_nova"] * item["phishings"]
            tot["principal"] += item["revocacao_principal"] * item["phishings"]
        if tot["n"]:
            r["E5"]["total"] = {"phishings": tot["n"], "revocacao_marca_nova": tot["nova"] / tot["n"],
                                "revocacao_principal": tot["principal"] / tot["n"]}

    mesclado = {**anteriores, **limpar(r)}
    with open(caminho_res, "w", encoding="utf-8") as f:
        json.dump(mesclado, f, ensure_ascii=False, indent=1, allow_nan=False)
    gerar_saidas(mesclado, Saidas(a.saida, a.ensaio))
    duracao = time.perf_counter() - inicio
    registrar("concluido", duracao_s=round(duracao))
    print(f"Saídas em {a.saida} ({duracao:.0f} s)", flush=True)


if __name__ == "__main__":
    main()
