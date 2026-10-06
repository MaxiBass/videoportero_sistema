# videoportero_sistema

Repositorio de la integración custom de Home Assistant «Videoportero» de
Maxi (dominio `videoportero`): la visita al videoportero (avisos, apertura,
quién atiende, historial). Es la **fuente de verdad** del código y la fuente
desde la que HACS la instalará.

Es **público** a propósito, porque HACS no lee repos privados. Por eso:

- **Nunca** subir nombres de la familia (salvo «Maxi»), matrículas, ids de
  aparatos, rutas de paneles de casa ni entidades personales: ni en el código,
  ni en las pruebas, ni en la documentación, ni en los commits. Las pruebas
  usan datos inventados.
- Lo que usa la configuración real de casa vive fuera, en
  `~/Downloads/GitHub/Arreglos_Videoportero/` (privado): el diseño completo
  (`DISENO_INTEGRACION.md`), la comparación con la automatización
  (`fase0/diferencial.py`) y con el historial (`fase0/historial.py`).

## Entorno

- Repo local: `~/Downloads/GitHub/videoportero_sistema`
- HA real por Samba: `/Volumes/config` (si no está montado:
  `osascript -e 'mount volume "smb://192.168.1.9/config"'`).
- Esta sesión **no tiene credenciales de GitHub**: `git add` y `git commit`
  sí, `git push` no. El push, y crear el repo en GitHub, lo hace Maxi desde
  GitHub Desktop.

## Estructura

```
custom_components/videoportero/
  motor.py        la visita como máquina de estados; no importa HA
  mensajes.py     textos de los avisos; no importa HA
  llamadas.py     decisiones → llamadas a servicios; no importa HA
  traduccion.py   estados/MQTT/eventos de HA → eventos del motor; no importa HA
  sombra.py       comparación con la automatización; no importa HA
  configuracion.py  entrada + subentradas → configuración del motor
  historial.py    visitas y diferencias en .storage (90 días)
  __init__.py     Sistema: suscripciones, motor, modo sombra
  config_flow.py  alta, opciones y subentradas «móvil» y «hogar»
  sensor.py       sensor.videoportero_visita y sensor.videoportero_diferencias
  brand/          icono (HA 2026.9 lo lee de aquí; se dibuja con docs/icono/generar.py)
docs/DECISIONES.md  por qué es así
docs/REQUISITOS.md  qué hay que instalar/activar en HA y en la app de HA (actualizarlo con cada cambio)
tests/test_motor.py  Python puro
tests/test_ha.py     en un HA real (venv), con datos inventados
```

## Antes de tocar nada, lee `docs/DECISIONES.md`

En particular:

- Las reglas son las de la automatización, una a una (§4). Si cambias una,
  pasa la comparación diferencial (privada) y explica la diferencia.
- Solo hay dos cambios aprobados respecto a la automatización (§4). Cualquier
  otro cambio de comportamiento necesita el OK de Maxi.
- El botón ABRIR **no caduca** y una matrícula aproximada **sí abre** (§7).

## Pruebas

```bash
python3 tests/test_motor.py
/tmp/hav/bin/python tests/test_ha.py
```

Las comparaciones con la casa (privadas):

```bash
python3 -m venv --clear /tmp/hav && /tmp/hav/bin/pip install homeassistant==2026.9.2 paho-mqtt
/tmp/hav/bin/python ~/Downloads/GitHub/Arreglos_Videoportero/fase0/diferencial.py 100 1
/tmp/hav/bin/python ~/Downloads/GitHub/Arreglos_Videoportero/fase0/historial.py
/tmp/hav/bin/python ~/Downloads/GitHub/Arreglos_Videoportero/fase1/sombra_local.py 40 1
```

El Python 3.14 del Mac da un segfault al cerrarse con HA cargado (ver
DECISIONES §6 de Integracion_Matriculas); por eso los scripts con HA salen con
`os._exit`.
