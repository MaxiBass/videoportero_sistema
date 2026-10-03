"""Pruebas del motor de la visita. Python puro, sin Home Assistant ni pytest:

    python3 tests/test_motor.py

Cada bloque prueba una regla de la automatización que se sustituye (o uno de
los cambios deliberados, marcados [CAMBIO]). Todos los nombres y matrículas
son inventados: este repositorio es público.
"""

from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# El paquete sin su __init__ (que importa Home Assistant): los módulos que se
# prueban aquí son Python puro y no deben necesitar HA.
_paquete = types.ModuleType("custom_components.videoportero")
_paquete.__path__ = [str(RAIZ / "custom_components" / "videoportero")]
sys.modules.setdefault("custom_components.videoportero", _paquete)

from custom_components.videoportero import traduccion as tr  # noqa: E402
from custom_components.videoportero.llamadas import (  # noqa: E402
    Llamada,
    SalidaHogar,
    SalidaMovil,
    Salidas,
    llamadas,
)
from custom_components.videoportero.motor import (  # noqa: E402
    ABIERTA,
    ATENDIDA,
    HOGAR,
    POR_APP,
    POR_AUDIO,
    POR_PANEL,
    SIN_RESPUESTA,
    Abrir,
    AbrirPuerta,
    Ajustes,
    AperturaAutomatica,
    Atendido,
    Avisar,
    Banner,
    Cara,
    Dispositivo,
    EmpiezaVisita,
    GuardarFoto,
    Matricula,
    Motor,
    PedirNombre,
    Puerta,
    RetirarAviso,
    TerminaVisita,
    Tick,
    Timbre,
)

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    print(f"  {'OK   ' if condicion else 'FALLO'} {etiqueta}")
    if not condicion:
        fallos.append(etiqueta)


T0 = datetime(2026, 10, 3, 10, 0, 0, tzinfo=ZoneInfo("Europe/Madrid"))


def t(segundos: float) -> datetime:
    return T0 + timedelta(seconds=segundos)


ANA = Dispositivo("ana", "Ana", pide_nombre_matricula=True)
LUIS = Dispositivo("luis", "Luis")
TABLETA = Dispositivo("tableta", "Tableta", personal=False)  # móvil sin dueño (como un iPad)
SALON = Dispositivo("salon", "Tablet salón", tipo=HOGAR, personal=False)
TODOS = (ANA, LUIS, TABLETA, SALON)
MOVILES = ("ana", "luis", "tableta")
AJUSTES = Ajustes(imagen_camara="/camara")


def motor(**kw) -> Motor:
    return Motor(TODOS, AJUSTES, **kw)


def de(tipo, decisiones):
    return [d for d in decisiones if isinstance(d, tipo)]


def aviso(decisiones) -> Avisar | None:
    a = de(Avisar, decisiones)
    return a[0] if len(a) == 1 else None


def placa(tipo="conocida", matricula="1111BBB", nombre="Familia", avisar=True, abrir=False, frigate_id="f1"):
    return {
        "matricula": matricula,
        "tipo": tipo,
        "nombre": nombre,
        "avisar": avisar,
        "abrir": abrir,
        "frigate_id": frigate_id,
    }


# ── Timbre y fin por tiempo ──────────────────────────────────────────


def test_timbre():
    print("\nTimbre sin que nadie conteste")
    m = motor()
    d = m.procesar(Timbre(t(0)))
    comprobar([type(x) for x in d] == [EmpiezaVisita, GuardarFoto, Avisar], f"empieza, foto y aviso: {d}")
    a = aviso(d)
    comprobar(a.mensaje == "\U0001f514 Alguien está llamando al timbre (10:00)", a.mensaje)
    comprobar(a.destinatarios == MOVILES, f"a los tres móviles, no al hogar: {a.destinatarios}")
    comprobar(a.suena and a.boton == "ABRE LA PUERTA" and a.imagen == "/camara", "suena, botón ABRE y foto de la cámara")
    comprobar(d[0].tag == "visita-20261003100000", d[0].tag)
    comprobar(m.proximo_tick() == t(180), "pide tick a los 3 min")
    comprobar(m.procesar(Tick(t(179))) == [], "a los 2:59 no pasa nada")
    d = m.procesar(Tick(t(180)))
    fin = de(TerminaVisita, d)
    comprobar(len(fin) == 1 and fin[0].visita.estado == SIN_RESPUESTA, "a los 3 min termina sin respuesta")
    comprobar(not de(Banner, d) and m.visita is None and m.proximo_tick() is None, "sin banner ni nada pendiente")


def test_espera_se_reinicia():
    print("\nCada evento de la visita reinicia los 3 min")
    m = motor()
    m.procesar(Timbre(t(0)))
    m.procesar(Cara(t(120), "", 0.5, "c1"))
    comprobar(m.procesar(Tick(t(200))) == [] and m.visita is not None, "a los 3:20 sigue abierta")
    comprobar(m.proximo_tick() == t(300), "y termina a los 3 min de la cara")
    d = m.procesar(Timbre(t(400)))
    fin = de(TerminaVisita, d)
    comprobar(len(fin) == 1 and fin[0].visita.fin == t(300), "un evento tardío cierra la anterior a su hora...")
    comprobar(len(de(EmpiezaVisita, d)) == 1, "...y empieza otra")


def test_avisos_siguientes_no_suenan():
    print("\nSolo suena el primer aviso de la visita")
    m = motor()
    a1 = aviso(m.procesar(Cara(t(0), "", 0.3, "c1")))
    a2 = aviso(m.procesar(Timbre(t(5))))
    comprobar(a1.suena and not a2.suena and a1.tag == a2.tag, "mismo tag, el segundo en silencio")
    comprobar(a1.mensaje == "Alguien desconocido en la puerta (10:00)", a1.mensaje)
    comprobar(a2.mensaje == "\U0001f514 Alguien desconocido está llamando al timbre (10:00)", a2.mensaje)


# ── Inicio ───────────────────────────────────────────────────────────


def test_inicio():
    print("\nQué empieza una visita")
    m = motor()
    comprobar(m.procesar(Matricula(t(0), placa(avisar=False))) == [], "un coche que no avisa, no")
    comprobar(m.visita is None, "ni deja visita abierta")
    m = motor(puerta_abierta=True)
    comprobar(m.procesar(Cara(t(0), "Ana", 0.99, "c1")) == [], "con la puerta abierta, una cara no")
    comprobar(m.procesar(Matricula(t(1), placa())) == [], "ni una matrícula")
    comprobar(de(EmpiezaVisita, m.procesar(Timbre(t(2)))), "el timbre sí")
    m = motor()
    m.procesar(Puerta(t(0), True))
    m.procesar(Puerta(t(1), False))
    comprobar(de(EmpiezaVisita, m.procesar(Cara(t(2), "", 0.2, "c1"))), "cerrada otra vez, la cara sí")


def test_dentro_todo_cuenta():
    print("\nDentro de una visita cuenta todo, aunque no avise")
    m = motor()
    m.procesar(Timbre(t(0)))
    d = m.procesar(Matricula(t(5), placa(avisar=False, nombre="Vecina")))
    comprobar(not de(Avisar, d) and m.visita.coche == "Vecina", "la matrícula que no avisa fija el coche sin avisar")
    a = aviso(m.procesar(Timbre(t(10))))
    comprobar(a.mensaje == "\U0001f514 Coche de Vecina está llamando al timbre (10:00)", a.mensaje)


def test_puerta_abierta_dentro():
    print("\nCon la puerta abierta, matrícula y cara no avisan")
    m = motor()
    m.procesar(Timbre(t(0)))
    m.puerta_abierta = True  # abierta sin evento (p. ej. ya lo estaba)
    comprobar(not de(Avisar, m.procesar(Cara(t(5), "Ana", 0.99, "c1"))), "cara: no")
    comprobar(not de(Avisar, m.procesar(Matricula(t(6), placa()))), "matrícula: no")
    comprobar(m.visita.persona == "Ana" and m.visita.coche == "Familia", "pero las apunta")


# ── Matrículas ───────────────────────────────────────────────────────


def test_matricula_conocida():
    print("\nMatrícula conocida")
    m = motor()
    d = m.procesar(Matricula(t(0), placa()))
    a = aviso(d)
    comprobar(a.mensaje == "Coche de Familia en la puerta (10:00)", a.mensaje)
    comprobar(a.imagen == "/api/frigate/notifications/f1/snapshot.jpg", a.imagen)
    comprobar(not de(AbrirPuerta, d), "sin apertura automática, no abre")
    comprobar(not de(Avisar, m.procesar(Matricula(t(3), placa()))), "la misma matrícula otra vez: nada")


def test_matricula_abre():
    print("\nMatrícula con «puede abrir» y apertura automática")
    m = motor(apertura_automatica=True)
    d = m.procesar(Matricula(t(0), placa(abrir=True)))
    comprobar(de(AbrirPuerta, d) == [AbrirPuerta(automatica=True)], "abre")
    comprobar(aviso(d).mensaje == "He abierto la puerta al coche de Familia (10:00)", aviso(d).mensaje)
    comprobar(aviso(d).boton == "ABRIR / CERRAR", "botón ABRIR / CERRAR")
    fin = de(TerminaVisita, d)
    comprobar(len(fin) == 1 and fin[0].visita.estado == ABIERTA, "y termina como abierta")
    comprobar(de(Banner, d) == [Banner("Puerta abierta automáticamente")], "con su banner")
    comprobar(m.procesar(Tick(t(179))) == [] and m.procesar(Tick(t(180))) == [Banner("")], "que se borra a los 3 min")
    m = motor(apertura_automatica=True)
    d = m.procesar(Matricula(t(0), placa(abrir=False)))
    comprobar(not de(AbrirPuerta, d), "sin «puede abrir», no abre")
    m = motor()
    m.procesar(AperturaAutomatica(t(0), True))
    comprobar(de(AbrirPuerta, m.procesar(Matricula(t(1), placa(abrir=True)))), "la apertura automática se activa por evento")


def test_matricula_caducada():
    print("\nMatrícula caducada")
    m = motor(apertura_automatica=True)
    d = m.procesar(Matricula(t(0), placa(tipo="caducada", abrir=True)))
    comprobar(aviso(d).mensaje == "Coche de Familia (autorización caducada) en la puerta (10:00)", aviso(d).mensaje)
    comprobar(not de(AbrirPuerta, d), "no abre aunque tuviera «puede abrir»")


def test_matricula_desconocida():
    print("\nMatrícula desconocida")
    m = motor()
    d = m.procesar(Matricula(t(0), placa(tipo="desconocida", matricula="2222CCC", nombre="", frigate_id="f9")))
    p = de(PedirNombre, d)
    comprobar(len(p) == 1 and p[0].destinatarios == ("ana",), f"pide el nombre solo a quien lo tiene activado: {p}")
    comprobar(p[0].tag == "lpr-2222CCC" and p[0].imagen.endswith("/f9/snapshot.jpg"), p[0].tag)
    comprobar(aviso(d).mensaje == "Coche desconocido en la puerta (10:00)", aviso(d).mensaje)
    # El mismo coche de Frigate, leído mejor
    d = m.procesar(Matricula(t(4), placa(tipo="desconocida", matricula="2222CCD", nombre="", frigate_id="f9")))
    comprobar(de(RetirarAviso, d) == [RetirarAviso("lpr-2222CCC", ("ana",))], "retira la petición anterior")
    comprobar([x.tag for x in de(PedirNombre, d)] == ["lpr-2222CCD"], "y pide el nombre de la nueva lectura")
    # Leído como conocida
    d = m.procesar(Matricula(t(8), placa(matricula="2222CCE", frigate_id="f9")))
    comprobar(de(RetirarAviso, d) == [RetirarAviso("lpr-2222CCD", ("ana",))], "si resulta conocida, también la retira")
    comprobar(m.visita.coche == "Familia" and m.visita.coche_desconocido, "y fija el coche")
    # Otro coche no retira nada
    m = motor()
    m.procesar(Matricula(t(0), placa(tipo="desconocida", matricula="2222CCC", frigate_id="f9")))
    d = m.procesar(Matricula(t(4), placa(tipo="desconocida", matricula="3333DDD", frigate_id="f10")))
    comprobar(not de(RetirarAviso, d) and len(de(PedirNombre, d)) == 1, "otro coche no retira la petición anterior")


# ── Caras ────────────────────────────────────────────────────────────


def test_caras():
    print("\nCaras")
    m = motor()
    d = m.procesar(Cara(t(0), "Ana", 0.97, "c1"))
    comprobar(aviso(d).mensaje == "Ana está en la puerta (10:00)", aviso(d).mensaje)
    comprobar(aviso(d).imagen == "/api/frigate/notifications/c1/snapshot.jpg", aviso(d).imagen)
    comprobar(not de(Avisar, m.procesar(Cara(t(1), "Ana", 0.98, "c2"))), "el mismo nombre otra vez: no avisa")
    comprobar(not de(Avisar, m.procesar(Cara(t(2), "Luis", 0.96, "c2"))), "mismo objeto con peor score: no cuenta")
    comprobar(m.visita.persona == "Ana", "y la persona no cambia")
    a = aviso(m.procesar(Cara(t(3), "Luis", 0.99, "c2")))
    comprobar(a is not None and a.mensaje == "Luis está en la puerta (10:00)", "mismo objeto mejor score y otro nombre: avisa")
    comprobar(not de(Avisar, m.procesar(Cara(t(4), "", 0.2, "c3"))), "tras una conocida, una desconocida no avisa")

    m = motor()
    comprobar(aviso(m.procesar(Cara(t(0), "Ana", 0.95, "c1"))).mensaje == "Alguien desconocido en la puerta (10:00)",
              "0,95 justo no es conocida (umbral estricto)")
    comprobar(not de(Avisar, m.procesar(Cara(t(1), "", 0.1, "c2"))), "la desconocida avisa una sola vez por visita")
    comprobar(aviso(m.procesar(Cara(t(2), "Ana", 0.99, "c3"))).mensaje == "Ana está en la puerta (10:00)",
              "una conocida después sí avisa")


def test_apertura_por_cara_y_timbre():
    print("\nApertura automática por cara conocida o por timbre")
    m = motor(apertura_automatica=True)
    d = m.procesar(Cara(t(0), "Ana", 0.99, "c1"))
    comprobar(aviso(d).mensaje == "He abierto la puerta a Ana (10:00)", aviso(d).mensaje)
    m = motor(apertura_automatica=True)
    comprobar(not de(AbrirPuerta, m.procesar(Cara(t(0), "", 0.3, "c1"))), "cara desconocida: no abre")
    d = m.procesar(Timbre(t(5)))
    comprobar(de(AbrirPuerta, d) and aviso(d).mensaje == "He abierto la puerta (10:00)", "el timbre sí abre")
    m = motor(apertura_automatica=True)
    m.procesar(Timbre(t(0)))  # abre y termina
    m.procesar(Puerta(t(2), True))
    d = m.procesar(Timbre(t(10)))
    comprobar(de(EmpiezaVisita, d) and not de(AbrirPuerta, d), "otro timbre con la puerta abierta no vuelve a abrir")


# ── Atender ──────────────────────────────────────────────────────────


def test_atender_app():
    print("\nAlguien abre la app durante la visita")
    m = motor()
    m.procesar(Timbre(t(0)))
    d = m.procesar(Atendido(t(8), "luis", POR_APP))
    a = aviso(d)
    comprobar(a.destinatarios == ("ana", "tableta"), f"a Luis no le avisa: {a.destinatarios}")
    comprobar(a.mensaje == "Luis ha atendido (10:00)", f"[CAMBIO] dice quién: {a.mensaje}")
    comprobar(a.cierre and not a.suena and a.boton == "ABRIR / CERRAR", "aviso de cierre, en silencio, ABRIR / CERRAR")
    fin = de(TerminaVisita, d)[0].visita
    comprobar(fin.estado == ATENDIDA and fin.dispositivo_atendio == "luis" and fin.como == POR_APP, "termina atendida por Luis")
    comprobar(de(Banner, d) == [Banner("Llamada ya atendida")], "banner de atendida")
    comprobar(m.procesar(Atendido(t(20), "ana", POR_APP)) == [], "fuera de una visita, atender no hace nada")


def test_atender_hogar_y_desconocido():
    print("\nAtienden desde la tablet del salón, o no se sabe quién")
    m = motor()
    m.procesar(Cara(t(0), "Ana", 0.99, "c1"))
    a = aviso(m.procesar(Atendido(t(5), "salon", POR_PANEL)))
    comprobar(a.destinatarios == MOVILES, "avisa a todos los móviles")
    comprobar(a.mensaje == "Han atendido a Ana desde Tablet salón (10:00)", f"[CAMBIO] {a.mensaje}")
    m = motor()
    m.procesar(Timbre(t(0)))
    a = aviso(m.procesar(Atendido(t(5), None, POR_AUDIO)))
    comprobar(a.mensaje == "Alguien ha atendido (10:00)" and a.destinatarios == MOVILES, a.mensaje)


def test_abrir_desde_aviso():
    print("\nBotón ABRIR del aviso")
    m = motor()
    m.procesar(Timbre(t(0)))
    d = m.procesar(Abrir(t(10), "ana", tag="visita-20261003100000"))
    comprobar(d == [AbrirPuerta(automatica=False, quien="ana")], "abre")
    a = aviso(m.procesar(Puerta(t(14), True)))
    comprobar(a.mensaje == "Ana ha abierto la puerta (10:00)", f"[CAMBIO] dice quién: {a.mensaje}")
    comprobar(a.destinatarios == ("luis", "tableta"), f"[CAMBIO] a quien pulsó no le llega el cierre: {a.destinatarios}")
    m = motor()
    m.procesar(Timbre(t(0)))
    m.procesar(Abrir(t(10), "ana"))
    a = aviso(m.procesar(Puerta(t(100), True)))
    comprobar(a.mensaje == "Alguien ha abierto la puerta (10:01)" and a.destinatarios == MOVILES,
              "si la puerta se abre más de 60 s después, no se atribuye")
    m = motor()
    m.procesar(Abrir(t(0), "ana"))
    m.procesar(Timbre(t(30)))
    a = aviso(m.procesar(Puerta(t(40), True)))
    comprobar(a.mensaje.startswith("Ana ha abierto"), "pulsado justo antes de empezar la visita, también")
    m = motor()
    m.procesar(Timbre(t(0)))
    m.procesar(Abrir(t(5), "tableta"))
    a = aviso(m.procesar(Puerta(t(8), True)))
    comprobar(a.mensaje == "Han abierto la puerta desde Tableta (10:00)", a.mensaje)
    comprobar(Motor(TODOS, AJUSTES).procesar(Abrir(t(0), None, tag="visita-20250101000000"))
              == [AbrirPuerta(automatica=False, quien=None)], "un aviso antiguo, sin visita, abre igual (no caduca)")
    m = motor()
    m.procesar(Timbre(t(0)))
    comprobar(m.procesar(Abrir(t(5), "luis", ejecutar=False)) == [], "el botón del panel no vuelve a abrir")
    comprobar(aviso(m.procesar(Puerta(t(7), True))).mensaje.startswith("Luis ha abierto"), "pero se sabe quién fue")


def test_puerta_cerrandose_no_cuenta():
    print("\nCerrarse la puerta no es un evento de la visita")
    m = motor(puerta_abierta=True)
    m.procesar(Timbre(t(0)))
    comprobar(m.procesar(Puerta(t(60), False)) == [] and m.visita.ultimo_evento == t(0), "ni avisa ni reinicia la espera")


def test_aviso_cierre_desactivado():
    print("\nMóvil sin aviso de cierre")
    m = Motor((ANA, Dispositivo("luis", "Luis", aviso_cierre=False)), AJUSTES)
    comprobar(aviso(m.procesar(Timbre(t(0)))).destinatarios == ("ana", "luis"), "recibe el aviso de la visita")
    comprobar(aviso(m.procesar(Atendido(t(5), "ana", POR_APP))).destinatarios == (), "pero no el de cierre")


def test_sin_ventana_ciega():
    print("\nUn timbre justo después de una visita atendida")
    m = motor()
    m.procesar(Timbre(t(0)))
    m.procesar(Puerta(t(10), True))
    m.procesar(Puerta(t(20), False))
    d = m.procesar(Timbre(t(30)))
    comprobar(de(EmpiezaVisita, d) and aviso(d).suena, "empieza otra visita y suena")
    comprobar(m.proximo_tick() == t(210), "el banner de la anterior ya no está pendiente (lo quita la nueva)")


def test_tope_eventos():
    print("\nTope de eventos por visita")
    m = Motor(TODOS, Ajustes(imagen_camara="/camara", max_eventos=3))
    for i in range(4):
        m.procesar(Cara(t(i), "", 0.1, f"c{i}"))
    comprobar(m.visita is not None and m.visita.eventos == 4, "procesa uno más que el tope, como la automatización")
    d = m.procesar(Timbre(t(10)))
    comprobar(de(TerminaVisita, d) and not de(Avisar, d) and m.visita is None, "el siguiente cierra la visita y se pierde")


def test_dispositivos_en_caliente():
    print("\nAñadir un dispositivo con la visita en curso")
    m = Motor((ANA,), AJUSTES)
    m.procesar(Timbre(t(0)))
    m.cambiar_dispositivos((ANA, LUIS))
    a = aviso(m.procesar(Cara(t(5), "Ana", 0.99, "c1")))
    comprobar(a.destinatarios == ("ana", "luis"), "el nuevo recibe el siguiente aviso")


def test_historial():
    print("\nLo que queda para el historial")
    m = motor()
    m.procesar(Matricula(t(0), placa()))
    m.procesar(Cara(t(5), "Ana", 0.99, "c1"))
    m.procesar(Timbre(t(10)))
    v = de(TerminaVisita, m.procesar(Atendido(t(20), "ana", POR_APP)))[0].visita
    comprobar(v.motivo == "matricula" and v.matriculas == ["1111BBB"] and v.caras == ["Ana"], "cómo empezó, coche y cara")
    comprobar(v.timbres == [t(10)] and v.avisos == 4 and v.inicio == t(0) and v.fin == t(20), "timbres, avisos, inicio y fin")


# ── Llamadas a HA ────────────────────────────────────────────────────


SALIDAS = Salidas(
    moviles={
        "ana": SalidaMovil("mobile_app_ana", "/llamada/ana?kiosk"),
        "luis": SalidaMovil("mobile_app_luis", "/llamada/luis?kiosk", boton_abrir=False),
    },
    hogar={"salon": SalidaHogar(("script.salon_timbre",))},
    al_empezar=("script.zoom", "script.silencia"),
    al_timbre=("script.foto",),
    abrir_boton="script.abrir",
    abrir_automatica="switch.motor",
    banner="input_text.estado",
    marca_audio="input_text.quien",
)


def test_llamadas():
    print("\nLlamadas a Home Assistant (las mismas que hace hoy la automatización)")
    ll = llamadas(EmpiezaVisita("visita-1", t(0), "timbre"), SALIDAS)
    comprobar(ll == [
        Llamada("input_text", "set_value", {"entity_id": "input_text.estado", "value": ""}),
        Llamada("input_text", "set_value", {"entity_id": "input_text.quien", "value": ""}),
        Llamada("script", "turn_on", {"entity_id": "script.zoom"}),
        Llamada("script", "turn_on", {"entity_id": "script.silencia"}),
        Llamada("script", "turn_on", {"entity_id": "script.salon_timbre", "variables": {"origen": "vto"}}),
    ], f"al empezar: {ll}")
    av = Avisar("visita-1", ("ana", "luis", "nadie"), "Hola", "/img", True, "ABRE LA PUERTA", False)
    ll = llamadas(av, SALIDAS)
    comprobar([x.servicio for x in ll] == ["mobile_app_ana", "mobile_app_luis"], "un notify por móvil conocido")
    datos = ll[0].datos["data"]
    comprobar(ll[0].datos["title"] == "Videoportero" and ll[0].datos["message"] == "Hola", "título y texto")
    comprobar(datos["actions"] == [{"action": "ABRIR_PUERTA", "title": "ABRE LA PUERTA"}], "botón ABRIR")
    comprobar(datos["alert_once"] is False and datos["tag"] == "visita-1" and datos["clickAction"] == "/llamada/ana?kiosk",
              "suena, tag y vista")
    comprobar("actions" not in ll[1].datos["data"], "sin botón si el móvil no lo quiere")
    comprobar(llamadas(AbrirPuerta(True), SALIDAS) == [Llamada("switch", "turn_on", {"entity_id": "switch.motor"})],
              "apertura automática")
    comprobar(llamadas(AbrirPuerta(False, "ana"), SALIDAS) == [Llamada("script", "turn_on", {"entity_id": "script.abrir"})],
              "botón ABRIR")
    comprobar(llamadas(GuardarFoto("visita-1"), SALIDAS) == [Llamada("script", "turn_on", {"entity_id": "script.foto"})],
              "foto con el timbre")
    ll = llamadas(PedirNombre("lpr-2222CCC", "2222CCC", "/img", ("ana",)), SALIDAS)
    comprobar(len(ll) == 1 and ll[0].datos["data"]["tag"] == "lpr-2222CCC"
              and [a["action"] for a in ll[0].datos["data"]["actions"]] == ["input_nombre_matricula", "ignorar_matricula"],
              "pedir el nombre")
    comprobar(llamadas(RetirarAviso("lpr-x", ("ana",)), SALIDAS)
              == [Llamada("notify", "mobile_app_ana", {"message": "clear_notification", "data": {"tag": "lpr-x"}})],
              "retirar")
    comprobar(llamadas(Banner("Llamada ya atendida"), SALIDAS)
              == [Llamada("input_text", "set_value", {"entity_id": "input_text.estado", "value": "Llamada ya atendida"})],
              "banner")


def test_puerta_no_disponible():
    print("\nPuerta no disponible")
    m = motor(puerta_abierta=None)
    comprobar(m.procesar(Cara(t(0), "Ana", 0.99, "c1")) == [], "ni abierta ni cerrada: una cara no empieza visita")
    m = motor(apertura_automatica=True)
    m.procesar(Puerta(t(0), None))
    d = m.procesar(Timbre(t(1)))
    comprobar(de(EmpiezaVisita, d) and not de(AbrirPuerta, d), "el timbre sí empieza, pero no abre sola")
    comprobar(not de(Avisar, m.procesar(Puerta(t(2), True))), "y pasar de no disponible a abierta no es atender")
    comprobar(de(Avisar, m.procesar(Cara(t(3), "Ana", 0.99, "c1"))) == [], "ya abierta, la cara no avisa")


# ── Traducción de HA ─────────────────────────────────────────────────


E = tr.Entradas(
    timbre="binary_sensor.timbre",
    puerta="binary_sensor.puerta",
    camara_caras="Portal",
    apertura_automatica="input_boolean.auto",
    audio="input_boolean.audio",
    marca_audio="input_text.marca",
    marcas={"ana": "ana"},
    app={"sensor.ana_last_used_app": "ana"},
    panel={"sensor.salon_path": "salon"},
    aparatos={"app-ana": "ana"},
    usuarios={"u-luis": "luis"},
)


def test_traduccion():
    print("\nTraducción de lo que ve HA")
    nada = lambda e: None  # noqa: E731
    comprobar(tr.estado(E, t(0), "binary_sensor.timbre", "off", "on", nada) == [Timbre(t(0))], "timbre off → on")
    comprobar(tr.estado(E, t(0), "binary_sensor.timbre", "unavailable", "on", nada) == [], "unavailable → on no es timbre")
    comprobar(tr.estado(E, t(0), "binary_sensor.timbre", "on", "on", nada) == [], "solo atributos: nada")
    comprobar(tr.estado(E, t(0), "binary_sensor.puerta", "off", "unavailable", nada) == [Puerta(t(0), None)],
              "puerta no disponible")
    comprobar(tr.estado(E, t(0), "sensor.ana_last_used_app", "com.otra", tr.APP_HA, nada)
              == [Atendido(t(0), "ana", POR_APP)], "abrir la app de HA")
    comprobar(tr.estado(E, t(0), "sensor.ana_last_used_app", tr.APP_HA, "com.otra", nada) == [], "salir de ella no")
    comprobar(tr.estado(E, t(0), "sensor.salon_path", "/marco", "/videoportero/salon", nada)
              == [Atendido(t(0), "salon", POR_PANEL)], "entrar en la vista de llamada")
    comprobar(tr.estado(E, t(0), "sensor.salon_path", "/marco", "/videoportero/salon-ver", nada) == [],
              "la vista de solo ver no cuenta")
    comprobar(tr.estado(E, t(0), "sensor.salon_path", "/videoportero/a", "/videoportero/b", nada) == [],
              "moverse dentro de la vista de llamada no vuelve a contar")
    comprobar(tr.estado(E, t(0), "input_boolean.audio", "off", "on", {"input_text.marca": "ana"}.get)
              == [Atendido(t(0), "ana", POR_AUDIO)], "audio con la marca de quien contesta")
    comprobar(tr.estado(E, t(0), "input_boolean.audio", "off", "on", {"input_text.marca": ""}.get)
              == [Atendido(t(0), None, POR_AUDIO)], "audio sin marca: no se sabe quién")
    comprobar(tr.cara(E, t(0), {"type": "face", "camera": "Portal", "name": "Ana", "score": 0.97, "id": "x"})
              == [Cara(t(0), "Ana", 0.97, "x")], "cara de la cámara")
    comprobar(tr.cara(E, t(0), {"type": "face", "camera": "Otra", "name": "Ana", "score": 0.97, "id": "x"}) == [],
              "otra cámara no")
    comprobar(tr.cara(E, t(0), {"type": "lpr", "camera": "Portal"}) == [], "otro tipo no")
    comprobar(tr.cara(E, t(0), {"type": "face", "camera": "Portal", "name": None, "score": None, "id": "x"})
              == [Cara(t(0), "", 0.0, "x")], "sin nombre ni score")
    comprobar(tr.accion_aviso(E, t(0), {"action": "ABRIR_PUERTA", "device_id": "app-ana", "tag": "v"}, None)
              == [Abrir(t(0), "ana", ejecutar=True, tag="v")], "ABRIR: quién por el aparato")
    comprobar(tr.accion_aviso(E, t(0), {"action": "ABRIR_PUERTA"}, "u-luis")[0].quien == "luis",
              "ABRIR: si no, por el usuario")
    comprobar(tr.accion_aviso(E, t(0), {"action": "ignorar_matricula"}, None) == [], "otras acciones no")


if __name__ == "__main__":
    for nombre, prueba in list(globals().items()):
        if nombre.startswith("test_") and callable(prueba):
            prueba()
    print(f"\n{'TODO BIEN' if not fallos else f'{len(fallos)} FALLOS'}")
    sys.exit(1 if fallos else 0)
