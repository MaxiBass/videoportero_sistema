# Requisitos

Qué tiene que estar instalado y activado en Home Assistant y en la app de HA
(Companion) para que la integración funcione, y qué deja de funcionar si
falta algo. Consúltalo al añadir un dispositivo o antes de desinstalar algo.

Estado: versión 0.1.4 (fase 1, modo sombra). Este documento se actualiza con
cada cambio de lo que se necesita.

## Home Assistant

| Qué | Para qué | Si falta |
|---|---|---|
| Home Assistant 2026.9 o posterior | Subentradas (dispositivos) e icono propio | No se instala o no hay icono |
| HACS | Instalar y actualizar la integración | Habría que copiarla a mano |
| Una integración del videoportero (por ejemplo Dahua) con un `binary_sensor` del **pulsador** (se enciende al pulsar) y otro de la **puerta** (encendido = abierta) | Empezar la visita con el timbre; saber que se ha abierto | Sin pulsador no hay visitas por timbre; sin puerta no se detecta la apertura |
| Una **cámara** (`camera.*`) del videoportero | Foto de los avisos cuando no hay una de Frigate | Los avisos salen sin foto |
| **MQTT** configurado | Recibir las caras de Frigate | No hay visitas por cara |
| **Frigate** (complemento + integración) con **reconocimiento facial** activado en la cámara del videoportero | Publica las caras en `frigate/tracked_object_update` | No hay visitas por cara |
| El **sensor de personas** de esa cámara que crea la integración de Frigate (`sensor.<cámara>_person_count`) | Una cara solo empieza visita si Frigate cuenta una persona (evita detecciones falsas) | Sin configurarlo, cualquier cara empieza visita |
| **Matrículas** (opcional) | Visitas por matrícula (evento `matriculas_detectada`) | No hay visitas por matrícula |
| **BrowserMod** (opcional, recomendado) | Saber que alguien entra en la vista de llamada, también con la app de HA ya abierta | Se pierde esa forma de detectar que alguien atiende |
| La **app de HA** en cada móvil y tablet | Avisos, botón ABRIR y detectar quién atiende | Ese dispositivo no recibe avisos ni cuenta como atendido |

Hasta la fase 3, la integración usa además los ayudantes y scripts que ya
hay en casa (abrir, apertura automática, audio, banner y scripts al empezar
la visita y con cada timbre). Se eligen en las opciones de la integración;
si se borra alguno, hay que quitarlo también de ahí.

## En la app de HA de cada dispositivo

En la app: Ajustes → Aplicación complementaria → Gestionar sensores.

### Móvil Android

| Qué | Para qué | Si falta |
|---|---|---|
| Notificaciones permitidas | Recibir los avisos | No recibe nada |
| Sensor **«Last used app»** (pide el permiso de acceso al uso de aplicaciones) | Abrir la app de HA durante una visita cuenta como atender. Es la forma más rápida | Solo se detecta por BrowserMod, más tarde y no siempre |
| **BrowserMod** registrado en la app (recomendado), con sus sensores de **ruta** y de **visibilidad** (los crea BrowserMod; en el formulario del móvil se elige el de ruta y la integración encuentra sola el de visibilidad) | La página de HA que pasa a verse en pantalla cuenta como atender, también si HA ya era la última app usada. Entrar en la vista de llamada, también | Si HA ya era la última app usada, abrirla no se detecta |

No hace falta activar «Interactive» ni «Keyguard locked»: no se usan (ver
DECISIONES §4).

Al darlo de alta, la integración saca sola el servicio de avisos, el sensor
«Last used app» y el identificador del botón ABRIR a partir del aparato
elegido. Si se reinstala la app de HA, el aparato cambia: hay que editar el
móvil en la integración y elegir el aparato nuevo.

### iPhone, iPad o Mac

| Qué | Para qué | Si falta |
|---|---|---|
| Notificaciones permitidas | Recibir los avisos y el botón ABRIR | No recibe nada |

La app de HA para Apple no tiene «Last used app»: abrir la app no cuenta
como atender (sí pulsar ABRIR).

### Dispositivo del hogar (tablet Android)

| Qué | Para qué | Si falta |
|---|---|---|
| App de HA abierta y con la sesión iniciada | Mostrar la cámara y el ding dong | No se ve ni suena |
| **BrowserMod** registrado y su sensor de ruta | Entrar en la vista de llamada desde la tablet cuenta como atender | No se detecta que se atiende desde ahí |
| Scripts propios (opcional), con ADB si hacen falta | Despertar la pantalla, volúmenes, volver a la vista de inicio | Hasta la fase 3, la tablet no hace nada en la visita |

Ojo: si un script cierra la app de HA a la fuerza, Android no le entrega
avisos hasta que se vuelve a abrir.

## Comprobar que todo va

- `sensor.videoportero_visita`: la visita en curso o la última.
- `sensor.videoportero_diferencias`: en el modo sombra, lo que no coincidió
  con la automatización (debe quedarse quieto).
- Ajustes → Sistema → Registros, filtrando por `videoportero`.
