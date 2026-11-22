"""
Figuras do Cap. 5 (etapa 6), em PDF, com vírgula decimal e rótulos em português.
"""

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

_VIRGULA = FuncFormatter(lambda v, _: f"{v:g}".replace(".", ","))


def _salvar(fig, caminho):
    fig.tight_layout()
    fig.savefig(caminho)
    plt.close(fig)


def roc(curvas, caminho, zoom=0.1):
    """Curvas ROC {nome: (fpr, tpr, auc)}: à esquerda, inteira; à direita, a região de falso positivo baixo
    (até `zoom`), que é onde o detector opera."""
    fig, eixos = plt.subplots(1, 2, figsize=(9, 4))
    for eixo, limite in zip(eixos, (1.0, zoom)):
        for nome, (fpr, tpr, auc) in curvas.items():
            eixo.plot(fpr, tpr, label=f"{nome} (AUC {auc:.3f})".replace(".", ","))
        eixo.plot([0, limite], [0, limite], ls=":", color="gray")
        eixo.set_xlim(0, limite)
        eixo.set_ylim(0, 1)
        eixo.set_xlabel("Taxa de falso positivo")
        eixo.set_ylabel("Revocação")
        eixo.xaxis.set_major_formatter(_VIRGULA)
        eixo.yaxis.set_major_formatter(_VIRGULA)
        eixo.grid(alpha=0.3)
    eixos[0].legend(fontsize=8, loc="lower right")
    eixos[1].set_title(f"Falso positivo até {zoom:g}".replace(".", ","), fontsize=9)
    _salvar(fig, caminho)


def barras_por_marca(linhas, caminho):
    """Revocação por marca, com o intervalo de confiança; linhas: entidade, revocacao, ic, amostras."""
    linhas = sorted(linhas, key=lambda l: l["revocacao"])
    fig, eixo = plt.subplots(figsize=(7, 0.32 * len(linhas) + 1))
    y = range(len(linhas))
    erros = [[max(l["revocacao"] - (l["ic"][0] if l["ic"][0] == l["ic"][0] else l["revocacao"]), 0) for l in linhas],
             [max((l["ic"][1] if l["ic"][1] == l["ic"][1] else l["revocacao"]) - l["revocacao"], 0) for l in linhas]]
    eixo.barh(list(y), [l["revocacao"] for l in linhas], xerr=erros, color="#4C72B0", capsize=2)
    eixo.set_yticks(list(y))
    eixo.set_yticklabels([f"{l['entidade']} (n={l['amostras']})" for l in linhas], fontsize=8)
    eixo.set_xlim(0, 1)
    eixo.set_xlabel("Revocação no teste (intervalo de 95%)")
    eixo.xaxis.set_major_formatter(_VIRGULA)
    eixo.grid(axis="x", alpha=0.3)
    _salvar(fig, caminho)


def latencia(partes, caminho):
    """Mediana (ms) de cada parte da análise de uma página."""
    nomes = list(partes)
    fig, eixo = plt.subplots(figsize=(7, 0.4 * len(nomes) + 1))
    eixo.barh(nomes, [partes[n] for n in nomes], color="#55A868")
    for i, n in enumerate(nomes):
        eixo.text(partes[n], i, f" {partes[n]:.1f}".replace(".", ","), va="center", fontsize=8)
    eixo.set_xlabel("Tempo por página (ms, mediana)")
    eixo.xaxis.set_major_formatter(_VIRGULA)
    eixo.invert_yaxis()
    eixo.grid(axis="x", alpha=0.3)
    _salvar(fig, caminho)
