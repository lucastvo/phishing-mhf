"""
Componente visual da impressão digital φ(w) = (h, e, s) (monografia, Seção 2.6).

  h — hash perceptual (pHash) da captura de tela, comparado pela distância de Hamming;
  e — embedding da MobileNetV3 (Small ou Large), comparado pelo cosseno.

Normalização (Seção 2.4.3): cada captura recebe uma classe de tela (o tamanho de tela dos templates
mais próximo) e é recortada na primeira dobra; a amostra é comparada com templates da mesma classe.
Redimensionar não desfaz a mudança de layout entre telas de tamanhos diferentes: o mesmo template em
1280x960 e 1366x768 fica a 18 bits (de 64) de distância, contra ~32 entre marcas diferentes.

Desenho: docs/especificacoes/2026-11-21-componente-visual.md
"""

from __future__ import annotations

import os

import imagehash
import numpy as np
from PIL import Image, ImageFile

# Armadilhas conhecidas dos datasets: PNGs do Phish360 com bloco final corrompido e capturas de página
# inteira do Phishpedia benign com até 85 mil px de altura.
ImageFile.LOAD_TRUNCATED_IMAGES = True
Image.MAX_IMAGE_PIXELS = None

# Tamanhos de tela dos templates (e dos datasets): Phish360, Phishpedia benign e Phishpedia phishing.
CLASSES_TELA = {"1280x960": (1280, 960), "1366x768": (1366, 768), "1920x1080": (1920, 1080)}

_TAMANHO_HASH = {64: 8, 256: 16}  # bits → lado da matriz de coeficientes da DCT


def classe_de_tela(largura: int) -> str:
    """Classe de tela de uma captura: a de largura mais próxima. As capturas de 800x600 do Phishpedia
    (4:3) caem em 1280x960, a única classe 4:3; são as únicas sem template do mesmo tamanho exato."""
    return min(CLASSES_TELA, key=lambda c: abs(CLASSES_TELA[c][0] - largura))


def abrir_imagem(origem) -> Image.Image:
    """Abre a captura (caminho ou arquivo em memória) em RGB, tolerando PNG truncado e imagens muito
    altas. Áreas transparentes são compostas sobre branco, como o navegador mostra a página: as capturas
    RGBA do Phishpedia têm regiões com alfa 0 e RGB 0, que ficariam pretas se o alfa fosse descartado."""
    with Image.open(origem) as img:
        if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
            rgba = img.convert("RGBA")
            return Image.alpha_composite(Image.new("RGBA", rgba.size, (255, 255, 255, 255)), rgba).convert("RGB")
        return img.convert("RGB")


def tamanho_da_dobra(largura: int, classe: str) -> tuple[int, int]:
    """Largura e altura da primeira dobra de uma captura com essa largura.
    - Até a largura da classe: a largura da imagem e a altura proporcional à classe (ex.: 1366 em 1366x768
      → 768 px; 800 em 1280x960 → 600 px).
    - Mais larga que a classe (transbordo horizontal numa captura de página inteira, como no Phishpedia
      benign): a janela, com a largura e a altura da classe, porque a tela só mostrava o canto superior
      esquerdo da página. É também o que o navegador entrega ao capturar a aba visível."""
    largura_classe, altura_classe = CLASSES_TELA[classe]
    if largura > largura_classe:
        return largura_classe, altura_classe
    return largura, int(largura * altura_classe / largura_classe + 0.5)


def primeira_dobra(img: Image.Image, classe: str) -> Image.Image:
    """Recorta a primeira dobra (tamanho_da_dobra) a partir do canto superior esquerdo. Captura mais baixa
    que a dobra é usada com a altura que tem."""
    largura, altura = tamanho_da_dobra(img.width, classe)
    if img.width <= largura and img.height <= altura:
        return img
    return img.crop((0, 0, largura, min(altura, img.height)))


def phash(img: Image.Image, bits: int = 64) -> str:
    """Hash perceptual (DCT) em hexadecimal: 64 bits (padrão) ou 256 bits."""
    if bits not in _TAMANHO_HASH:
        raise ValueError(f"bits deve ser um de {sorted(_TAMANHO_HASH)}")
    return str(imagehash.phash(img, hash_size=_TAMANHO_HASH[bits]))


def sim_hash(a: str, b: str) -> float:
    """Similaridade entre dois hashes em hexadecimal: 1 − d_H/n, em [0, 1]."""
    if len(a) != len(b):
        raise ValueError("hashes de tamanhos diferentes")
    n = 4 * len(a)
    return 1 - bin(int(a, 16) ^ int(b, 16)).count("1") / n


# Pesos pré-treinados ficam em data/torch (fora do git): a pasta padrão do PyTorch (~/.cache) não é
# gravável na máquina do Lucas. Uma TORCH_HOME já definida tem prioridade.
_PASTA_PESOS = os.path.join(os.path.dirname(__file__), "..", "..", "data", "torch")

_MEDIA_IMAGENET, _DESVIO_IMAGENET = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)


class Embedder:
    """Embedding e da MobileNetV3 pré-treinada na ImageNet: "small" (principal, 576 dimensões) ou
    "large" (comparação, 960). A entrada é a dobra redimensionada para 224x224 (sem recorte central:
    a borda da página faz parte do layout) e normalizada como na ImageNet; a saída é o vetor depois do
    global average pooling, antes do classificador, com norma 1 — assim o cosseno é um produto interno.
    `pesos=False` cria a rede com pesos aleatórios e semente fixa, para testes sem rede."""

    _MODELOS = {"small": ("mobilenet_v3_small", "MobileNet_V3_Small_Weights", "IMAGENET1K_V1"),
                "large": ("mobilenet_v3_large", "MobileNet_V3_Large_Weights", "IMAGENET1K_V2")}

    def __init__(self, modelo: str = "small", pesos: bool = True):
        if modelo not in self._MODELOS:
            raise ValueError(f"modelo deve ser um de {sorted(self._MODELOS)}")
        import torch
        import torchvision.models as modelos
        from torchvision import transforms

        construtor, classe_pesos, versao = self._MODELOS[modelo]
        if pesos:
            os.environ.setdefault("TORCH_HOME", os.path.abspath(_PASTA_PESOS))
            w = getattr(getattr(modelos, classe_pesos), versao)
        else:
            torch.manual_seed(0)
            w = None
        self.modelo = modelo
        self._torch = torch
        self._rede = getattr(modelos, construtor)(weights=w).eval()
        self.dim = self._rede.classifier[0].in_features
        self._preparar = transforms.Compose([
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(_MEDIA_IMAGENET, _DESVIO_IMAGENET),
        ])

    def embed(self, img: Image.Image) -> np.ndarray:
        """Vetor float32 de norma 1 para uma imagem (já recortada na primeira dobra)."""
        with self._torch.inference_mode():
            x = self._preparar(img.convert("RGB")).unsqueeze(0)
            v = self._rede.avgpool(self._rede.features(x)).flatten(1)[0].numpy().astype(np.float32)
        return v / max(float(np.linalg.norm(v)), 1e-12)


def cosseno(a: np.ndarray, b: np.ndarray) -> float:
    """Similaridade do cosseno entre dois embeddings."""
    return float(np.dot(a, b) / max(float(np.linalg.norm(a) * np.linalg.norm(b)), 1e-12))


def comparar(v1: dict, v2: dict) -> dict:
    """Compara duas impressões visuais {"h": hash em hexadecimal, "e": embedding}. Devolve os componentes
    separados, como estrutural.comparar: sim_h = 1 − d_H/n e cos_e = cosseno. A combinação dos escores é
    da regra de decisão (etapa 5)."""
    return {"sim_h": sim_hash(v1["h"], v2["h"]), "cos_e": cosseno(v1["e"], v2["e"])}
