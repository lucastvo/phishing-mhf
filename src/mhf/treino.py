"""
Treino, calibração e métricas da regra de decisão (etapas 5 e 6), sobre conjuntos de conjuntos.carregar_conjunto.

- pares_de_treino / treinar_modelo: pares (amostra, marca) com o rótulo "é phishing desta marca";
- escores_fora_da_dobra: validação cruzada nas dobras do desenvolvimento;
- calibrar: τ para o alvo de falso positivo (e θ_h, se houver estágio 1);
- metricas_cascata: a decisão completa medida por amostra e por estrutura.

Desenho: docs/especificacoes/2026-11-22-cascata.md
"""

import time

import numpy as np

from mhf import cascata, metricas


def pares_de_treino(c, mascara, entidades_excluidas=()):
    """Pares (amostra, entidade) das amostras em `mascara`: sem entidade ausente da classe, sem o par de
    uma página no domínio legítimo da própria entidade e sem nenhum par das `entidades_excluidas` (o
    experimento "marca nova"). Rótulo: a amostra é phishing dessa entidade. Peso: o da estrutura, com
    positivos e negativos somando o mesmo total (média 1)."""
    X = c["X"][mascara]
    n, e, _ = X.shape
    y = c["entidade_real"][mascara][:, None] == np.array(c["entidades"], dtype=object)[None, :]
    fora = np.array([ent in set(entidades_excluidas) for ent in c["entidades"]])
    validos = ~np.isnan(X).any(axis=2) & ~c["legit"][mascara] & ~fora[None, :]
    w = np.broadcast_to(c["pesos"][mascara][:, None], (n, e))[validos].astype(float)
    y = y[validos].astype(bool)
    if y.any() and (~y).any():
        w = np.where(y, w * (w[~y].sum() / w[y].sum()), w)
    return X[validos], y, (w / w.mean() if w.size else w)


def treinar_modelo(tipo, c, mascara, entidades_excluidas=(), iteracoes=150, **floresta):
    """`floresta`: arvores, n_jobs, profundidade e folha do Random Forest; `iteracoes`: do boosting."""
    X, y, w = pares_de_treino(c, mascara, entidades_excluidas)
    if tipo == "regressao":
        return cascata.RegressaoLogistica.treinar(X, y, w, c["nomes"])
    if tipo == "boosting":
        return cascata.Boosting.treinar(X, y, w, c["nomes"], iteracoes=iteracoes)
    return cascata.Floresta.treinar(X, y, w, c["nomes"], **floresta)


def escores_fora_da_dobra(c, tipo, progresso=print, entidades_excluidas=(), **floresta):
    """Escores (amostras, entidades) em que cada amostra é pontuada pelo modelo treinado sem a dobra dela."""
    escores = np.full(c["X"].shape[:2], np.nan)
    for k in sorted(set(c["dobra"].tolist()) - {-1}):
        t = time.perf_counter()
        modelo = treinar_modelo(tipo, c, (c["dobra"] != k) & (c["dobra"] >= 0), entidades_excluidas, **floresta)
        alvo = c["dobra"] == k
        escores[alvo] = cascata.pontuar_amostras(modelo, c["X"][alvo])
        progresso(f"  {tipo}: dobra {k} ({time.perf_counter() - t:.0f} s)")
    return escores


def calibrar(c, escores, alvo_fpr=0.01, alvo_rev1=0.99, estagio1="nenhum"):
    """τ: menor limiar com FPR ≤ `alvo_fpr` nas páginas legítimas, por amostra, com a decisão completa;
    também o τ que maximiza o F1. Com `estagio1="phash"`, também θ_h: percentil `alvo_rev1` de d₁ nos
    phishings de 𝒯 (pelo menos essa fração chega ao classificador), e θ_h para 95% e 90%. Com "nenhum"
    (padrão), θ_h = None: toda página vai ao classificador."""
    if estagio1 == "nenhum":
        r = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], None, -np.inf)
        sinalizada, legit = r["phishing"], c["legitima"]
        tau = metricas.limiar_para_fpr(r["escore"][sinalizada & legit],
                                       np.ones(int((sinalizada & legit).sum())), float(legit.sum()), alvo_fpr)
        alvo_f1 = sinalizada & (legit | c["phishing_T"])
        tau_f1 = metricas.limiar_f1(r["escore"][alvo_f1], c["phishing_T"][alvo_f1],
                                    np.ones(int(alvo_f1.sum())), float(c["phishing_T"].sum()))
        return {"estagio1": "nenhum", "theta_h": None, "tau": float(tau), "tau_f1": float(tau_f1),
                "alvo_fpr": alvo_fpr}
    d1_phish = c["d1"][c["phishing_T"]]
    theta = {a: int(np.quantile(d1_phish, a, method="higher")) for a in (alvo_rev1, 0.95, 0.90)}
    theta_h = theta[alvo_rev1]
    r = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], theta_h, -np.inf)
    sinalizada = r["phishing"]  # com τ = −∞: o que o limiar ainda pode segurar
    legit = c["legitima"]
    tau = metricas.limiar_para_fpr(r["escore"][sinalizada & legit], np.ones(int((sinalizada & legit).sum())),
                                   float(legit.sum()), alvo_fpr)
    alvo_f1 = sinalizada & (legit | c["phishing_T"])
    tau_f1 = metricas.limiar_f1(r["escore"][alvo_f1], c["phishing_T"][alvo_f1],
                                np.ones(int(alvo_f1.sum())), float(c["phishing_T"].sum()))
    def liberadas(th):  # fração das legítimas que o estágio 1 já libera com esse θ_h
        r1 = cascata.aplicar_cascata(c["d1"], c["t1"], escores, c["legit"], th, -np.inf)
        return float(((r1["estagio"] == 1) & legit).sum() / max(legit.sum(), 1))
    return {"estagio1": "phash", "theta_h": theta_h, "tau": float(tau), "tau_f1": float(tau_f1), "alvo_fpr": alvo_fpr,
            "alvo_revocacao_estagio1": alvo_rev1, "theta_h_95": theta[0.95], "theta_h_90": theta[0.90],
            "fracao_legitimas_liberadas_estagio1": liberadas(theta_h),
            "fracao_legitimas_liberadas_estagio1_95": liberadas(theta[0.95]),
            "fracao_legitimas_liberadas_estagio1_90": liberadas(theta[0.90])}


def metricas_cascata(c, escores, theta_h, tau, mascara=None):
    """Métricas da cascata no subconjunto `mascara`, por amostra e por estrutura (pesos 1/grupo)."""
    m = np.ones(len(c["d1"]), dtype=bool) if mascara is None else mascara
    r = cascata.aplicar_cascata(c["d1"][m], c["t1"][m], escores[m], c["legit"][m], theta_h, tau)
    pt, legit, fora = c["phishing_T"][m], c["legitima"][m], c["fora_T"][m]
    binario = pt | legit
    esc_max = np.nan_to_num(np.nanmax(np.nan_to_num(escores[m], nan=-1.0), axis=1), nan=0.0)
    melhor = np.argmax(np.nan_to_num(escores[m], nan=-np.inf), axis=1)
    ent = np.array(c["entidades"], dtype=object)
    real = c["entidade_real"][m]
    saida = {}
    for nome, pesos in (("por_amostra", np.ones(int(m.sum()))), ("por_estrutura", c["pesos"][m])):
        b = metricas.binarias(pt[binario], r["phishing"][binario], pesos[binario])
        det = pt & r["phishing"]
        saida[nome] = {**{k: b[k] for k in ("precisao", "revocacao", "f1", "fpr", "especificidade", "acuracia")},
                       "auc": metricas.auc(pt[binario], esc_max[binario], pesos[binario]),
                       "top1": metricas.top1(real[pt], ent[melhor[pt]], pesos[pt]),
                       "top1_detectados": metricas.top1(real[det], ent[r["entidade"][det]], pesos[det])
                       if det.any() else float("nan"),
                       "fora_T_sinalizado": float((pesos[fora] * r["phishing"][fora]).sum() / pesos[fora].sum())
                       if fora.any() else float("nan"),
                       "legitimas_liberadas_estagio1": float((pesos[legit] * (r["estagio"][legit] == 1)).sum()
                                                             / pesos[legit].sum()) if legit.any() else float("nan"),
                       "phishing_T_no_estagio2": float((pesos[pt] * (r["estagio"][pt] == 2)).sum()
                                                       / pesos[pt].sum()) if pt.any() else float("nan")}
    saida["n"] = {"phishing_T": int(pt.sum()), "legitimas": int(legit.sum()), "fora_T": int(fora.sum())}
    return saida
