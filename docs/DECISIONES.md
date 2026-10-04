# Decisiones de diseño

Por qué la integración es como es. Antes de cambiar algo, lee la sección que
toca. Repositorio público: aquí no van nombres, matrículas ni identificadores
de aparatos de casa.

## 1. Qué sustituye

La automatización «Visita unificada» de Maxi (una sola automatización de unos
22 KB con un bucle `repeat` y 8 disparadores en espera) y lo que cuelga de
ella: el borrado del banner, el mute de seguridad del altavoz, el botón ABRIR
de los avisos, los tres pasos de la apertura automática, guardar o ignorar una
matrícula nueva desde el aviso y mostrar la cámara en las pantallas al abrirse
la puerta. En total, 10 automatizaciones, 4 scripts y 6 ayudantes al acabar
todas las fases (§6).

**No sustituye** lo que habla con los aparatos: la integración Dahua (timbre y
puerta), Frigate (caras), la integración Matrículas, go2rtc y la tarjeta
WebRTC (vídeo y audio) ni los scripts propios de las tablets (ADB). La
integración los usa.

Es el «cerebro de la visita»: decide cuándo empieza y acaba, a quién se avisa
y con qué texto, cuándo se abre sola la puerta, quién ha atendido, y lo deja
registrado.

## 2. Por qué una integración

- La lógica estaba en plantillas Jinja de cientos de caracteres y alias de
  500, y añadir un dispositivo obligaba a tocar tres sitios.
- Tres fallos que se encontraron el 26/09/2026 venían de cómo funciona el
  YAML: un mute que vigilaba un script de 0,25 s, `mode: single` descartando
  timbres durante 3 min y las 30 trazas llenas de ejecuciones inútiles. Se
  arreglaron en YAML, pero el diseño invitaba a repetirlos.
- Se ganan dos cosas que no existían: pruebas automáticas y un historial de
  visitas.

## 3. El motor no sabe nada de Home Assistant

`motor.py`, `mensajes.py`, `llamadas.py` y `traduccion.py` no importan nada
de HA (como `coincidencia.py` en Matrículas):

- `traduccion.py` convierte lo que ve HA (un cambio de estado, un mensaje
  MQTT, un evento) en eventos del motor: `Timbre`, `Puerta`, `Cara`,
  `Matricula`, `Atendido`, `Abrir`...
- `motor.py` recibe esos eventos con su hora y devuelve decisiones:
  `EmpiezaVisita`, `Avisar`, `PedirNombre`, `AbrirPuerta`, `TerminaVisita`...
  El tiempo lo marca quien llama (`proximo_tick()`), así que una prueba puede
  simular tres minutos en microsegundos.
- `llamadas.py` convierte cada decisión en las llamadas a servicios que hacía
  la automatización, campo a campo.

Así se puede comparar el motor con la automatización real sobre los mismos
eventos (§8), y la parte de HA queda fina: suscribirse, llamar al motor y
hacer las llamadas.

## 4. Mismas reglas, y dos cambios aprobados

Las reglas se portan una a una y los campos de `Visita` se llaman como las
variables de la automatización. Resumen:

- Empieza por timbre, cara de la cámara del videoportero o matrícula con
  `avisar`. Con la puerta abierta (o no disponible) solo por timbre: las
  aperturas por voz llegan antes que la lectura de la matrícula.
- Dentro de la visita cuenta todo, también la matrícula que no avisa (fija el
  coche para los textos).
- Termina al atender, al abrirse sola o a los 3 min sin eventos (cada evento
  reinicia la cuenta). El cierre de la puerta no es un evento.
- El primer aviso suena; el resto lo sustituye en silencio (mismo tag).
- Cara conocida: score **estrictamente** mayor que 0,95 y con nombre.
- Tope de 200 eventos por visita, como el `repeat`.

Cambios aprobados por Maxi el 03/10/2026, y los únicos:

1. **Decir quién**: «Ana ha abierto la puerta» en vez de «Alguien ha abierto
   la puerta», y lo mismo al atender. Si el aparato no tiene dueño: «Han
   atendido desde Tablet salón». Si no se sabe, «Alguien», como antes.
2. **Quien pulsa ABRIR no recibe el aviso de cierre**, igual que ya pasaba con
   quien contestaba.

Saber quién pulsó ABRIR es posible porque el evento del botón trae el
`device_id` de la app y el usuario en el contexto (comprobado con los eventos
reales). La puerta abierta se atribuye a quien pulsó ABRIR si se abre en los
60 s siguientes.

Además desaparecen, sin que haya que decidir nada, la ventana en la que un
timbre se perdía (no hay `mode: single`) y la dependencia del mute de un
ayudante (fase 3).

## 5. Dispositivos: móvil y del hogar

Petición de Maxi (03/10): poder añadir dispositivos después, de dos tipos. Se
hace con **subentradas** de HA: en la página de la integración salen «Añadir
móvil» y «Añadir dispositivo del hogar», y cada uno se edita o se quita en
cualquier momento sin YAML ni reinicio.

El tipo lo da el papel, no el aparato (las tablets también tienen la app):

| | Móvil | Dispositivo del hogar |
|---|---|---|
| Es de | Una persona (o de nadie) | La casa |
| En una visita | Recibe el aviso: suena, foto, ABRIR | Ding dong, enciende la pantalla y muestra la cámara |
| Al terminar | Aviso de cierre, salvo si atendió él | Vuelve a su vista de inicio |
| Atiende cuando | Abre la app de HA o la vista de llamada, contesta o pulsa ABRIR | Entra en la vista de llamada o contesta |

- **Móvil:** se elige de la lista de aparatos con la app de HA; de ahí salen
  el servicio de aviso, el sensor `last_used_app` (Android) y el `device_id`
  del botón ABRIR. Opciones: vista al tocar el aviso, BrowserMod, aviso de
  cierre, petición de nombre de matrícula nueva y botón ABRIR.
- **Del hogar:** la integración hace sola lo básico con la app de HA en
  Android (encender pantalla, ding dong, mostrar la cámara, volver al
  terminar), así que una tablet nueva no necesita YAML. Si el dispositivo
  tiene un script propio de inicio o de fin, se usa **en lugar de** lo
  básico: así siguen las tablets que hacen cosas por ADB.

## 6. Fases

| Fase | Qué | En casa |
|---|---|---|
| 0 | Motor y pruebas; comparación con la automatización y con el último mes | Nada |
| 1 | Sombra: instalada, escucha y anota lo que habría hecho (§9) | Solo se instala |
| 2 | Cambio: avisa, abre y escribe el banner con los mismos ayudantes y scripts; la automatización se desactiva, no se borra | Con OK de Maxi |
| 3 | Apertura automática, audio, matrícula nueva y dispositivos del hogar integrados | Con OK de Maxi |
| 4 | Opcional: panel con historial; retirar lo antiguo | Con OK de Maxi |

## 7. Lo que no se discute (decisiones de Maxi)

- El botón ABRIR de los avisos **no caduca**: abre siempre, de cualquier
  visita (27/09/2026).
- Una matrícula **aproximada sí abre** (ver Matrículas, §4).
- «Ignorar» en el aviso de matrícula nueva solo cierra el aviso.
- Que el mismo coche abra otra visita al volver a leerse se deja así: es cosa
  del detector de Matrículas.
- Con la puerta abierta solo el timbre empieza una visita.
- Historial de 90 días, sin guardar fotos nuevas (solo referencias a las que
  ya existen).

## 8. Cómo se comprueba

- `tests/test_motor.py`: una prueba por regla, con datos inventados. Python
  puro.
- Fuera del repo (privado, porque usa la configuración de casa):
  - comparación diferencial: los mismos eventos a la automatización real,
    corriendo en un HA local, y al motor; se comparan las llamadas a servicios
    una a una. Los dos cambios de §4 se normalizan antes de comparar. Se
    comprobó que la comparación detecta un error de umbral metido a propósito;
  - el último mes real del recorder pasado por el motor y comparado con los
    avisos que mandó de verdad la automatización.

Resultado de la fase 0 (03/10/2026): 452 escenarios iguales a la
automatización (52 fijos y 400 aleatorios), y las 7 visitas reales desde el
27/09 iguales a lo que avisó la automatización. Las diferencias de antes del
27/09 se explican por las versiones anteriores de la automatización.

Los datos reales nunca entran en el repositorio.

## 9. Fase 1: el modo sombra

La integración se instala y hace todo menos ejecutar: escucha lo mismo que la
automatización (estados, MQTT de caras, `matriculas_detectada`, el botón
ABRIR), decide con el motor, apunta en el historial y calcula las llamadas
que habría hecho. **No llama a ningún servicio.**

Para comparar, en las opciones se eligen las automatizaciones que hoy hacen
ese trabajo. Cada vez que una se dispara (`automation_triggered`), se guarda
el contexto de esa ejecución; las llamadas a servicios (`call_service`) con
ese contexto son «lo que hizo la automatización». Así no se mezclan las de
otras automatizaciones que tocan lo mismo (por ejemplo, el zoom al abrir la
puerta o los avisos de audio).

Solo cuentan las llamadas que haría la propia integración (`sombra.Alcance`):
avisos a los móviles dados de alta y los scripts, interruptores e
`input_text` que la integración llama. Un script lanzado con `script.turn_on`
hereda el contexto de quien lo lanza, así que lo que hace por dentro (los
avisos y el ADB de las tablets, sus scripts de restaurar, el motor que
enciende el script del botón ABRIR) llega con el contexto de la
automatización; la integración lanza esos scripts, pero no hace lo que ellos
hacen dentro. Visto en casa con la primera visita real (04/10, 12:21): las 7
diferencias que dejó la v0.1.0 son de esto y están explicadas; la v0.1.1 ya
no las cuenta.

Cada llamada se empareja con una igual del otro lado hecha a menos de 5 s.
Lo que pasa 20 s sin pareja es una diferencia: se guarda en el historial y la
cuenta el sensor `sensor.videoportero_diferencias`. Antes de comparar se
deshacen los dos cambios de §4, y se ignoran la hora del texto y el tag de la
visita, que lleva la hora de inicio.

Diferencias que se esperan y no son fallos de la integración:

- Un evento que llega mientras la automatización está procesando otro: ella
  lo pierde (`mode: single` sin espera activa), la integración no.
- Las dos tablets en la vista de llamada a la vez: la automatización las
  vigila con una sola plantilla (o una u otra), y la segunda no la ve.
- Un reinicio de HA en mitad de una visita.

Los dispositivos (subentradas) y las opciones se aplican sin recargar la
entrada, para no perder una visita en curso.

Comprobado antes de instalar (privado, con la configuración de casa, 03/10):
la integración dada de alta con sus formularios, junto a las automatizaciones
reales en un HA local: 219 escenarios (39 fijos y 180 aleatorios), 5.707
llamadas emparejadas y ninguna diferencia.
