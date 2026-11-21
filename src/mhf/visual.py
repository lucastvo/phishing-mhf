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

import imagehash
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


def abrir_imagem(caminho: str) -> Image.Image:
    """Abre a captura em RGB, tolerando PNG truncado e imagens muito altas."""
    with Image.open(caminho) as img:
        return img.convert("RGB")


def primeira_dobra(img: Image.Image, classe: str) -> Image.Image:
    """Recorta o topo da captura com a altura da tela: a largura da imagem vezes a proporção da classe
    (ex.: 1366 de largura em 1366x768 → 768 px). Captura mais baixa que isso é usada como está."""
    largura_classe, altura_classe = CLASSES_TELA[classe]
    altura = int(img.width * altura_classe / largura_classe + 0.5)
    return img if img.height <= altura else img.crop((0, 0, img.width, altura))


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
