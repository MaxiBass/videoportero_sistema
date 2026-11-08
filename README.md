# Videoportero

Integración para Home Assistant que lleva la visita a un videoportero: cuándo
empieza y acaba, a quién se avisa y con qué texto, cuándo se abre sola la
puerta, quién ha atendido, y un historial de visitas.

No habla con el videoportero: usa los sensores de timbre y puerta de la
integración Dahua, las caras de Frigate (MQTT) y las matrículas de la
integración Matrículas.

**Estado: en marcha.** Fase 2 hecha: avisa, abre y escribe el banner ella,
con los ayudantes y scripts de la casa, y las automatizaciones a las que
sustituyó ya no existen (v0.3.0, sin modo sombra). De la fase 3 está hecho
contestar al aviso de matrícula nueva (v0.4.0); siguen pendientes la apertura
automática y el audio integrados y, en los dispositivos del hogar, lo básico
sin script y los scripts de fin.
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
