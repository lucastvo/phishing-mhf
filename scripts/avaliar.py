"""
Passo 6 — avaliação no conjunto de teste: o detector principal e os experimentos E0–E5, de uma vez.

Uso:
    python scripts/avaliar.py \
        --tabelas data/similaridades_phish360 data/similaridades_phishpedia_phish data/similaridades_phishpedia_benign \
        --estrutural data/estrutural_phish360.jsonl data/estrutural_phishpedia_phish.jsonl \
                     data/estrutural_phishpedia_benign.jsonl \
        --divisao data/divisao.csv --base data/base --marcas config/marcas.json --modelos data/modelos \
        --saida data/avaliacao

Experimentos (desenho, seção 4); todo treino e toda calibração usam só o desenvolvimento:
    E0  detector principal (data/modelos/boosting): métricas com intervalo de confiança, falso positivo por
        grupo, por marca, por dataset, por tipo de página, phishing fora de 𝒯 e sem marca, curva ROC;
    E1  ablação (h, e, s e combinações); E1b  regressão e Random Forest salvos; E2  Large e pHash de 256 bits;
    E3  com estágio 1 pelo pHash; E4a  base só com templates de 2026; E4b  base da época (Phishpedia);
    E5  marca nova (o classificador treinado sem as marcas em que é medido).
Saídas em --saida: resultados.json, relatorio.md, tabelas/*.tex, figuras/*.pdf; cada execução acrescenta
uma linha a registro.jsonl (o teste é usado uma vez; uma nova execução fica visível).

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


# ---------------------------------------------------------------- utilidades

def fatiar(c, nomes):
    """O conjunto com só as características `nomes` (subconjunto do superconjunto carregado)."""
    idx = [c["nomes"].index(n) for n in nomes]
    return {**c, "X": c["X"][:, :, idx], "nomes": list(nomes)}


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


# ---------------------------------------------------------------- treino de uma configuração

class Rodada:
    """Treina e calibra uma configuração no desenvolvimento e pontua o teste."""

    def __init__(self, a):
        self.params = {"iteracoes": a.iteracoes, "arvores": a.arvores, "profundidade": a.profundidade or None,
                       "folha": a.folha, "n_jobs": a.n_jobs}
        self.alvo_fpr = a.alvo_fpr

    def __call__(self, dev, teste, tipo="boosting", estagio1="nenhum", excluidas=(), rotulo=""):
        """(calibração, escores do teste), ou (None, None) se o desenvolvimento não tiver pares para treinar
        (ex.: uma base filtrada sem nenhum template)."""
        _, y, _ = treino.pares_de_treino(dev, np.ones(len(dev["d1"]), dtype=bool), excluidas)
        if not y.any() or y.all():
            print(f"  {rotulo or tipo}: sem pares positivos e negativos para treinar", flush=True)
            return None, None
        t = time.perf_counter()
        oof = treino.escores_fora_da_dobra(dev, tipo, progresso=lambda s: None, entidades_excluidas=excluidas,
                                           **self.params)
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

    binario = c["phishing_T"] | c["legitima"]
    fpr_c, tpr_c, _ = roc_curve(c["phishing_T"][binario], esc[binario])
    return {"geral": geral, "fpr_grupos": fpr, "por_marca": linhas_marca, "por_dataset": datasets,
            "por_tipo": por_tipo, "fora_de_T": fora, "binario_completo": completo,
            "n": {"phishing_T": int(c["phishing_T"].sum()), "legitimas": int(c["legitima"].sum()),
                  "estruturas_phishing_T": len(set(grupos[c["phishing_T"]]))},
            "_roc": (fpr_c, tpr_c, geral["por_amostra"]["auc"]), "_decisao": dec}


# ---------------------------------------------------------------- tabelas

class Saidas:
    def __init__(self, pasta):
        self.pasta = pasta
        self.md = []
        os.makedirs(os.path.join(pasta, "tabelas"), exist_ok=True)
        os.makedirs(os.path.join(pasta, "figuras"), exist_ok=True)

    def tabela(self, arquivo, cabecalho, linhas, legenda, rotulo):
        with open(os.path.join(self.pasta, "tabelas", arquivo), "w", encoding="utf-8") as f:
            f.write(avaliacao.tabela_latex(cabecalho, linhas, legenda, rotulo, fonte="Elaborada pelo autor."))
        sem_latex = lambda s: str(s).replace("\\%", "%").replace("$\\mathcal{T}$", "𝒯")  # noqa: E731
        self.md += [f"## {legenda}", "", "| " + " | ".join(map(sem_latex, cabecalho)) + " |",
                    "|" + "---|" * len(cabecalho)]
        self.md += ["| " + " | ".join(map(sem_latex, l)) + " |" for l in linhas]
        self.md.append("")


def tabelas_principal(s, e0):
    g = e0["geral"]
    linhas = [[rot, avaliacao.numero(g["por_amostra"][k]), avaliacao.intervalo(g["por_amostra"]["ic"].get(k)),
               avaliacao.numero(g["por_estrutura"][k]), avaliacao.intervalo(g["por_estrutura"]["ic"].get(k))]
              for k, rot in METRICAS]
    s.tabela("principal.tex", ["Métrica", "Por amostra", "IC 95\\%", "Por estrutura", "IC 95\\%"], linhas,
             "Detector principal no conjunto de teste (gradient boosting, h+e+s, estágio único)", "tab:principal")
    nomes = {"todas": "Todas as legítimas", "phish360": "Legítimas do Phish360",
             "phishpedia_benign": "Phishpedia benign", "paginas_das_marcas": "Páginas das próprias marcas",
             "mais_parecidas": "10\\% mais parecidas com a base"}
    s.tabela("fpr_grupos.tex", ["Grupo de páginas legítimas", "Páginas", "Taxa de falso positivo", "IC 95\\%"],
             [[nomes[k], str(v["paginas"]), avaliacao.percentual(v["fpr"], 2), avaliacao.intervalo(v["ic"], 4)]
              for k, v in e0["fpr_grupos"].items()],
             "Taxa de falso positivo por grupo de páginas legítimas", "tab:fpr-grupos")
    s.tabela("por_marca.tex", ["Marca", "Amostras", "Estruturas", "Revocação", "IC 95\\%", "Revocação (estrutura)",
                               "Marca certa"],
             [[l["entidade"], str(l["amostras"]), str(l["estruturas"]), avaliacao.numero(l["revocacao"]),
               avaliacao.intervalo(l["ic"]), avaliacao.numero(l["revocacao_estrutura"]),
               avaliacao.numero(l["top1_detectados"])] for l in e0["por_marca"]],
             "Revocação e marca certa nos detectados, por marca", "tab:por-marca")
    rot_t = {"com_senha": "Com campo de senha", "sem_senha": "Sem campo de senha", "sem_dom": "Sem DOM útil"}
    s.tabela("por_tipo.tex", ["Tipo de página", "Phishings", "Revocação", "Legítimas", "Taxa de falso positivo"],
             [[rot_t[k], str(v["phishing_T"]), avaliacao.numero(v["revocacao"]), str(v["legitimas"]),
               avaliacao.percentual(v["fpr"], 2)] for k, v in e0["por_tipo"].items()],
             "Resultado por tipo de página", "tab:por-tipo")
    linhas = [[ds, avaliacao.numero(m["por_amostra"]["revocacao"]), avaliacao.numero(m["por_estrutura"]["revocacao"]),
               avaliacao.percentual(m["por_amostra"]["fpr"], 2), avaliacao.numero(m["por_amostra"]["top1_detectados"])]
              for ds, m in e0["por_dataset"].items()]
    s.tabela("por_dataset.tex", ["Dataset", "Revocação", "Revocação (estrutura)", "Taxa de falso positivo",
                                 "Marca certa"], linhas, "Resultado por dataset", "tab:por-dataset")
    f = e0["fora_de_T"]
    b = e0["binario_completo"]
    s.tabela("fora_de_T.tex", ["Grupo", "Páginas", "Sinalizadas como phishing"],
             [["Phishing de marcas fora da base", str(f["fora"]["paginas"]), avaliacao.percentual(f["fora"]["sinalizadas"])],
              ["Phishing sem marca (test do Phish360)", str(f["sem_marca"]["paginas"]),
               avaliacao.percentual(f["sem_marca"]["sinalizadas"])],
              ["Detecção binária com todo phishing: revocação", "—", avaliacao.percentual(b["revocacao"])],
              ["Detecção binária com todo phishing: precisão", "—", avaliacao.percentual(b["precisao"])]],
             "Phishing de marcas fora da base e detecção com todo phishing como positivo", "tab:fora-da-base")


def linha_resumo(nome, m, extra=()):
    a, e = m["por_amostra"], m["por_estrutura"]
    return [nome, f"{avaliacao.numero(a['auc'])} / {avaliacao.numero(e['auc'])}",
            f"{avaliacao.numero(a['revocacao'])} / {avaliacao.numero(e['revocacao'])}",
            avaliacao.percentual(a["fpr"], 2), avaliacao.numero(a["top1_detectados"]), *extra]


CAB_RESUMO = ["Configuração", "AUC (amostra / estrutura)", "Revocação (amostra / estrutura)",
              "Taxa de falso positivo", "Marca certa"]


# ---------------------------------------------------------------- main

def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0].strip())
    p.add_argument("--tabelas", nargs="+", required=True)
    p.add_argument("--estrutural", nargs="+", required=True, help="JSONL estruturais, na mesma ordem das tabelas")
    p.add_argument("--divisao", default="data/divisao.csv")
    p.add_argument("--base", default="data/base")
    p.add_argument("--marcas", default="config/marcas.json")
    p.add_argument("--modelos", default="data/modelos")
    p.add_argument("--saida", default="data/avaliacao")
    p.add_argument("--experimentos", default=",".join(EXPERIMENTOS))
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
    b = base_mod.Base.carregar(a.base)
    tabela_marcas = marcas.ler_tabela(a.marcas)
    div = divisao.ler_divisao(a.divisao)
    senha = {}
    for prefixo, arq in zip(a.tabelas, a.estrutural):
        ds = os.path.basename(prefixo).removeprefix("similaridades_")
        with open(arq, encoding="utf-8") as f:
            for d in map(json.loads, f):
                senha[(ds, d["id"])] = d.get("contagens", {}).get("campos_senha")
    campos_senha = lambda m: senha.get((m["dataset"], m["id"]))  # noqa: E731

    print("Carregando desenvolvimento e teste...", flush=True)
    dev = carregar_conjunto(a.tabelas, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, SUPERCONJUNTO)
    teste = carregar_conjunto(a.tabelas, div, b, tabela_marcas, divisao.TESTE, SUPERCONJUNTO)
    print(f"Teste: {len(teste['meta'])} amostras ({int(teste['phishing_T'].sum())} phishings de 𝒯, "
          f"{int(teste['legitima'].sum())} legítimas)", flush=True)
    principal, info_p = cascata.carregar_modelo(os.path.join(a.modelos, "boosting"))
    nomes_p = info_p["caracteristicas"]["nomes"]
    rodada = Rodada(a)
    r, s = {}, Saidas(a.saida)
    curvas = {}

    teste_p = fatiar(teste, nomes_p)
    escores_p = cascata.pontuar_amostras(principal, teste_p["X"])
    cal_p = info_p["cascata"]
    if "E0" in exps:
        print("E0: detector principal", flush=True)
        e0 = experimento_principal(teste_p, escores_p, cal_p, campos_senha, a.bootstrap, a.semente)
        curvas["h+e+s (principal)"] = e0.pop("_roc")
        e0.pop("_decisao")
        r["E0"] = e0
        tabelas_principal(s, e0)
        figuras.barras_por_marca(e0["por_marca"], os.path.join(a.saida, "figuras", "por_marca.pdf"))

    resumo_linhas = []
    if "E1" in exps:
        print("E1: ablação", flush=True)
        r["E1"] = {}
        for comb in COMBINACOES:
            nomes = cascata.nomes_caracteristicas(comb)
            rot = "+".join(comb)
            cal, esc = rodada(fatiar(dev, nomes), fatiar(teste, nomes), rotulo=rot)
            if cal is None:
                r["E1"][rot] = {"sem_pares_no_treino": True}
                continue
            ct = fatiar(teste, nomes)
            r["E1"][rot] = {**resumo(ct, esc, cal), "tau": cal["tau"]}
            resumo_linhas.append(linha_resumo(f"Sinais {rot}", r["E1"][rot]))
            if comb in (("h",), ("e",), ("s",)):
                binario = ct["phishing_T"] | ct["legitima"]
                e = escore_da_amostra(ct, esc)
                fpr_c, tpr_c, _ = roc_curve(ct["phishing_T"][binario], e[binario])
                curvas[f"só {rot}"] = (fpr_c, tpr_c, r["E1"][rot]["por_amostra"]["auc"])
    if "E1b" in exps:
        print("E1b: regressão e Random Forest salvos", flush=True)
        r["E1b"] = {}
        for tipo, rot in (("regressao", "Regressão logística"), ("floresta", "Random Forest compacta")):
            modelo, info = cascata.carregar_modelo(os.path.join(a.modelos, tipo))
            ct = fatiar(teste, info["caracteristicas"]["nomes"])
            esc = cascata.pontuar_amostras(modelo, ct["X"])
            r["E1b"][tipo] = resumo(ct, esc, info["cascata"])
            resumo_linhas.append(linha_resumo(f"{rot} (h+e+s)", r["E1b"][tipo]))
    if "E2" in exps:
        print("E2: variações dos sinais", flush=True)
        r["E2"] = {}
        for rot, nomes in (("embedding Large", cascata.nomes_caracteristicas(embedding="large")),
                           ("pHash de 256 bits", cascata.nomes_caracteristicas(hash_bits=256))):
            cal, esc = rodada(fatiar(dev, nomes), fatiar(teste, nomes), rotulo=rot)
            if cal is None:
                r["E2"][rot] = {"sem_pares_no_treino": True}
                continue
            r["E2"][rot] = resumo(fatiar(teste, nomes), esc, cal)
            resumo_linhas.append(linha_resumo(f"h+e+s com {rot}", r["E2"][rot]))
    if resumo_linhas:
        s.tabela("ablacao.tex", CAB_RESUMO, resumo_linhas,
                 "Ablação dos sinais, classificadores e variações (teste)", "tab:ablacao")

    if "E3" in exps:
        print("E3: com estágio 1", flush=True)
        cal, esc = rodada(fatiar(dev, nomes_p), teste_p, estagio1="phash", rotulo="estágio 1")
        if cal is None:
            r["E3"] = {"sem_pares_no_treino": True}
        else:
            com = resumo(teste_p, esc, cal)
            sem = resumo(teste_p, escores_p, cal_p)
            r["E3"] = {"com_estagio1": {**com, "theta_h": cal["theta_h"]}, "sem_estagio1": sem}
            s.tabela("estagio1.tex", CAB_RESUMO + ["Legítimas liberadas no estágio 1"],
                     [linha_resumo("Estágio único (principal)", sem, [avaliacao.percentual(0.0)]),
                      linha_resumo(f"Com estágio 1 ($\theta_h$ = {cal['theta_h']} bits)", com,
                                   [avaliacao.percentual(com["por_amostra"]["legitimas_liberadas_estagio1"])])],
                     "Com e sem o estágio 1 pelo pHash (teste)", "tab:estagio1")

    temporal = []
    if "E4a" in exps:
        print("E4a: base só de 2026", flush=True)
        dev26 = carregar_conjunto(a.tabelas, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, nomes_p,
                                  filtro_templates=avaliacao.filtro_2026)
        teste26 = carregar_conjunto(a.tabelas, div, b, tabela_marcas, divisao.TESTE, nomes_p,
                                    filtro_templates=avaliacao.filtro_2026)
        cal, esc = rodada(dev26, teste26, rotulo="base de 2026")
        sem_2026 = sorted({it["entidade"] for it in b.itens} -
                          {it["entidade"] for it in b.itens if avaliacao.data_do_template(it).year == 2026})
        r["E4a"] = {"marcas_sem_template_2026": sem_2026}
        if cal is None:
            r["E4a"]["sem_pares_no_treino"] = True
        else:
            r["E4a"]["base_2026"] = resumo(teste26, esc, cal)
            temporal += [linha_resumo("Base completa (2019–2026)", resumo(teste_p, escores_p, cal_p)),
                         linha_resumo("Só templates de 2026", r["E4a"]["base_2026"])]
    if "E4b" in exps:
        print("E4b: base da época (Phishpedia)", flush=True)
        prefixos = [t for t in a.tabelas if "phishpedia" in os.path.basename(t)]
        com_data = [k for k in div if k[0].startswith("phishpedia") and avaliacao.data_da_amostra(k[1])]
        if not prefixos or not com_data:
            r["E4b"] = {"sem_amostras_com_data": True}
        else:
            filtro = avaliacao.filtro_ate_data()
            dev_c = carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, nomes_p)
            teste_c = carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.TESTE, nomes_p)
            dev_e = carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.DESENVOLVIMENTO, nomes_p, filtro)
            teste_e = carregar_conjunto(prefixos, div, b, tabela_marcas, divisao.TESTE, nomes_p, filtro)
            cal_c, esc_c = rodada(dev_c, teste_c, rotulo="Phishpedia, base completa")
            cal_e, esc_e = rodada(dev_e, teste_e, rotulo="Phishpedia, base da época")
            if cal_c is None or cal_e is None:
                r["E4b"] = {"sem_pares_no_treino": True}
            else:
                r["E4b"] = {"completa": resumo(teste_c, esc_c, cal_c), "epoca": resumo(teste_e, esc_e, cal_e)}
                temporal += [linha_resumo("Phishpedia: base completa", r["E4b"]["completa"]),
                             linha_resumo("Phishpedia: só templates anteriores à amostra", r["E4b"]["epoca"])]
    if temporal:
        s.tabela("temporal.tex", CAB_RESUMO, temporal, "Defasagem temporal da base de templates (teste)",
                 "tab:temporal")

    if "E5" in exps:
        print("E5: marca nova", flush=True)
        dec_p = decidir(teste_p, escores_p, cal_p.get("theta_h"), cal_p["tau"])
        ents = sorted({it["entidade"] for it in b.itens})
        rng = np.random.default_rng(a.semente)
        grupos_marcas = [list(g) for g in np.array_split(rng.permutation(ents), min(4, len(ents)))]
        r["E5"] = {"grupos": []}
        linhas, tot = [], {"n": 0, "nova": 0.0, "principal": 0.0}
        ent = np.array(teste_p["entidades"], dtype=object)
        for g in grupos_marcas:
            cal, esc = rodada(fatiar(dev, nomes_p), teste_p, excluidas=tuple(g), rotulo=f"sem {', '.join(g)}")
            if cal is None:
                r["E5"]["grupos"].append({"marcas": g, "sem_pares_no_treino": True})
                continue
            dec = decidir(teste_p, esc, None, cal["tau"])
            alvo = teste_p["phishing_T"] & np.isin(teste_p["entidade_real"].astype(str), g)
            if not alvo.any():
                continue
            det = alvo & dec["phishing"]
            item = {"marcas": g, "phishings": int(alvo.sum()), "revocacao_marca_nova": float(dec["phishing"][alvo].mean()),
                    "revocacao_principal": float(dec_p["phishing"][alvo].mean()),
                    "top1_marca_nova": float((ent[dec["entidade"][det]] == teste_p["entidade_real"][det]).mean())
                    if det.any() else None, "fpr_marca_nova": float(dec["phishing"][teste_p["legitima"]].mean())}
            r["E5"]["grupos"].append(item)
            tot["n"] += item["phishings"]
            tot["nova"] += item["revocacao_marca_nova"] * item["phishings"]
            tot["principal"] += item["revocacao_principal"] * item["phishings"]
            linhas.append([", ".join(g), str(item["phishings"]), avaliacao.numero(item["revocacao_marca_nova"]),
                           avaliacao.numero(item["revocacao_principal"]), avaliacao.numero(item["top1_marca_nova"])])
        if tot["n"]:
            r["E5"]["total"] = {"phishings": tot["n"], "revocacao_marca_nova": tot["nova"] / tot["n"],
                                "revocacao_principal": tot["principal"] / tot["n"]}
            linhas.append(["Todas", str(tot["n"]), avaliacao.numero(tot["nova"] / tot["n"]),
                           avaliacao.numero(tot["principal"] / tot["n"]), "—"])
        s.tabela("marca_nova.tex", ["Marcas fora do treino", "Phishings", "Revocação (marca nova)",
                                    "Revocação (principal)", "Marca certa (marca nova)"], linhas,
                 "Marcas que o classificador não viu no treino (teste)", "tab:marca-nova")

    if curvas:
        figuras.roc(curvas, os.path.join(a.saida, "figuras", "roc.pdf"))
    with open(os.path.join(a.saida, "resultados.json"), "w", encoding="utf-8") as f:
        json.dump(limpar(r), f, ensure_ascii=False, indent=1, allow_nan=False)
    with open(os.path.join(a.saida, "relatorio.md"), "w", encoding="utf-8") as f:
        f.write("# Avaliação no conjunto de teste\n\n" + "\n".join(s.md))
    registro = {"executado_em": datetime.now().isoformat(timespec="seconds"), "experimentos": exps,
                "divisao_sha256": sha256(a.divisao), "base_meta_sha256": sha256(os.path.join(a.base, "base_meta.json")),
                "modelos_sha256": {t: sha256(os.path.join(a.modelos, t, "modelo.json"))
                                   for t in ("boosting", "regressao", "floresta")
                                   if os.path.exists(os.path.join(a.modelos, t, "modelo.json"))},
                "bootstrap": a.bootstrap, "semente": a.semente}
    with open(os.path.join(a.saida, "registro.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    print(f"Saídas em {a.saida} ({time.perf_counter() - inicio:.0f} s)", flush=True)


if __name__ == "__main__":
    main()
