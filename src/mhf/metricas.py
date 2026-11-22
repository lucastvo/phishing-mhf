"""
Métricas de avaliação com pesos e escolha de limiares (etapas 5 e 6).

Phishing é a classe positiva (monografia, Seção 2.11). Todas as funções aceitam pesos por amostra: com o
peso 1/(tamanho do grupo de estrutura), cada kit de phishing conta uma vez, em vez de milhares de cópias
idênticas pesarem milhares de vezes.
"""

import numpy as np
from sklearn.metrics import roc_auc_score


def _pesos(n, pesos):
    return np.ones(n) if pesos is None else np.asarray(pesos, dtype=float)


def _razao(a, b):
    return a / b if b > 0 else float("nan")


def binarias(real, previsto, pesos=None):
    """Matriz de confusão (somando pesos) e as métricas derivadas. Divisão por zero → NaN."""
    real = np.asarray(real, dtype=bool)
    previsto = np.asarray(previsto, dtype=bool)
    w = _pesos(len(real), pesos)
    vp = float(w[real & previsto].sum())
    fn = float(w[real & ~previsto].sum())
    fp = float(w[~real & previsto].sum())
    vn = float(w[~real & ~previsto].sum())
    precisao, revocacao = _razao(vp, vp + fp), _razao(vp, vp + fn)
    f1 = (2 * precisao * revocacao / (precisao + revocacao)
          if precisao == precisao and revocacao == revocacao and precisao + revocacao > 0 else float("nan"))
    return {"vp": vp, "fp": fp, "vn": vn, "fn": fn, "precisao": precisao, "revocacao": revocacao, "f1": f1,
            "especificidade": _razao(vn, vn + fp), "fpr": _razao(fp, fp + vn),
            "acuracia": _razao(vp + vn, vp + vn + fp + fn)}


def auc(real, escores, pesos=None):
    """Área sob a curva ROC; NaN se só houver uma classe."""
    real = np.asarray(real, dtype=bool)
    if real.all() or not real.any():
        return float("nan")
    return float(roc_auc_score(real, np.asarray(escores, dtype=float), sample_weight=pesos))


def top1(real, previsto, pesos=None):
    """Fração (ponderada) em que a entidade prevista é a real; previsão None conta como erro."""
    acertos = np.array([p is not None and p == r for r, p in zip(real, previsto)], dtype=float)
    w = _pesos(len(acertos), pesos)
    return _razao(float((acertos * w).sum()), float(w.sum()))


def limiar_para_fpr(escores_neg, pesos_neg, peso_total_neg, alvo):
    """Menor τ tal que o peso dos negativos com escore ≥ τ, dividido por `peso_total_neg`, fique ≤ `alvo`.

    `escores_neg` são só os negativos que seriam sinalizados se passassem do limiar (os liberados antes,
    no estágio 1 ou pela checagem de domínio, entram apenas no total). Se nenhum valor cabe no alvo, τ fica
    logo acima do maior escore; se todos cabem, τ = −∞."""
    escores_neg = np.asarray(escores_neg, dtype=float)
    pesos_neg = np.asarray(pesos_neg, dtype=float)
    if escores_neg.size == 0:
        return -np.inf
    permitido = alvo * peso_total_neg + 1e-12
    valores = np.unique(escores_neg)[::-1]  # do maior para o menor
    tau = np.nextafter(valores[0], np.inf)
    acumulado = 0.0
    for v in valores:
        acumulado += float(pesos_neg[escores_neg == v].sum())
        if acumulado > permitido:
            return float(tau)
        tau = v
    return -np.inf


def limiar_f1(escores, positivo, pesos, peso_total_pos):
    """τ (entre os escores dados) que maximiza o F1; `peso_total_pos` inclui positivos que nunca chegam ao
    limiar (eles são falsos negativos para qualquer τ)."""
    escores = np.asarray(escores, dtype=float)
    positivo = np.asarray(positivo, dtype=bool)
    pesos = np.asarray(pesos, dtype=float)
    melhor, tau_melhor = -1.0, np.inf
    for v in np.unique(escores)[::-1]:
        acima = escores >= v
        vp = float(pesos[acima & positivo].sum())
        fp = float(pesos[acima & ~positivo].sum())
        if vp == 0:
            continue
        p, r = vp / (vp + fp), vp / peso_total_pos
        f1 = 2 * p * r / (p + r)
        if f1 > melhor:
            melhor, tau_melhor = f1, float(v)
    return tau_melhor
