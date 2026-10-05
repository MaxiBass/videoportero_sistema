"""Icono de Videoportero: la placa de un videoportero (cámara, rejilla del
altavoz y pulsador) en blanco sobre un cuadrado redondeado verde azulado.

Diseño propio (el repositorio es público). Se dibuja con Pillow, que ya trae
Home Assistant:

    /tmp/hav/bin/python docs/icono/generar.py custom_components/videoportero/brand
"""

import sys

from PIL import Image, ImageChops, ImageDraw


def dibujar(lado: int) -> Image.Image:
    S = 4  # sobremuestreo para bordes suaves
    W = lado * S
    u = W / 256  # unidades de un lienzo de 256

    # Fondo: cuadrado redondeado con un degradado vertical suave.
    fondo = Image.new("RGBA", (W, W))
    arriba, abajo = (38, 166, 154), (0, 105, 92)
    df = ImageDraw.Draw(fondo)
    for y in range(W):
        t = y / (W - 1)
        df.line([(0, y), (W, y)], fill=tuple(round(arriba[i] + (abajo[i] - arriba[i]) * t) for i in range(3)) + (255,))
    mascara = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mascara).rounded_rectangle([0, 0, W - 1, W - 1], radius=56 * u, fill=255)
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    img.paste(fondo, (0, 0), mascara)

    # La placa en blanco, con los huecos recortados (dejan ver el fondo).
    placa = Image.new("L", (W, W), 0)
    ImageDraw.Draw(placa).rounded_rectangle([80 * u, 34 * u, 176 * u, 222 * u], radius=26 * u, fill=255)

    huecos = Image.new("L", (W, W), 0)
    dh = ImageDraw.Draw(huecos)
    # Cámara
    cx, cy, r = 128 * u, 84 * u, 25 * u
    dh.ellipse([cx - r, cy - r, cx + r, cy + r], fill=255)
    # Rejilla del altavoz: tres ranuras
    for y in (128, 144, 160):
        dh.rounded_rectangle([102 * u, (y - 4) * u, 154 * u, (y + 4) * u], radius=4 * u, fill=255)
    # Pulsador
    bx, by, br = 128 * u, 194 * u, 15 * u
    dh.ellipse([bx - br, by - br, bx + br, by + br], fill=255)

    capa = ImageChops.subtract(placa, huecos)
    d = ImageDraw.Draw(capa)
    # Objetivo dentro del hueco de la cámara, y el botón dentro del pulsador
    ro = 11 * u
    d.ellipse([cx - ro, cy - ro, cx + ro, cy + ro], fill=255)
    rb = 8 * u
    d.ellipse([bx - rb, by - rb, bx + rb, by + rb], fill=255)

    blanco = Image.new("RGBA", (W, W), (255, 255, 255, 255))
    img.paste(blanco, (0, 0), capa)
    return img.resize((lado, lado), Image.LANCZOS)


destino = sys.argv[1]
dibujar(256).save(f"{destino}/icon.png", optimize=True)
dibujar(512).save(f"{destino}/icon@2x.png", optimize=True)
print("ok")
