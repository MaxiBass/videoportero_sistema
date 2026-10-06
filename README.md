# Videoportero

Integración para Home Assistant que lleva la visita a un videoportero: cuándo
empieza y acaba, a quién se avisa y con qué texto, cuándo se abre sola la
puerta, quién ha atendido, y un historial de visitas.

No habla con el videoportero: usa los sensores de timbre y puerta de la
integración Dahua, las caras de Frigate (MQTT) y las matrículas de la
integración Matrículas.

**Estado: fase 1, modo sombra.** Se instala y decide, pero no ejecuta nada:
compara lo que habría hecho con lo que hacen las automatizaciones actuales.
El diseño y las fases están en [`docs/DECISIONES.md`](docs/DECISIONES.md), y lo que hay que tener
instalado y activado (en Home Assistant y en la app de HA de cada dispositivo), en
[`docs/REQUISITOS.md`](docs/REQUISITOS.md).

## Instalación

1. HACS → Repositorios personalizados → este repositorio, categoría
   Integración. Instalar «Videoportero» y reiniciar Home Assistant.
2. Ajustes → Dispositivos y servicios → Añadir integración → Videoportero.
3. En la página de la integración: «Añadir móvil» y «Añadir dispositivo del
   hogar», uno por aparato.

## Pruebas

```bash
python3 tests/test_motor.py
/tmp/hav/bin/python tests/test_ha.py   # necesita Home Assistant en un venv
```
