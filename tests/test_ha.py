"""La integración en un Home Assistant real (el del venv), sin pytest:

    /tmp/hav/bin/python tests/test_ha.py

Arranca HA en un directorio temporal con la integración enlazada en
`custom_components/`, la da de alta con sus formularios, añade dispositivos
(subentradas) y comprueba que escucha, decide en sombra y compara. Todos los
nombres son inventados: este repositorio es público.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

fallos: list[str] = []


def comprobar(condicion: bool, etiqueta: str) -> None:
    print(f"  {'OK   ' if condicion else 'FALLO'} {etiqueta}")
    if not condicion:
        fallos.append(etiqueta)


APP_HA = "io.homeassistant.companion.android"


async def arrancar(directorio: Path):
    from homeassistant import bootstrap, config_entries, core, loader
    from homeassistant.core_config import async_process_ha_core_config
    from homeassistant.setup import async_setup_component

    hass = core.HomeAssistant(str(directorio))
    loader.async_setup(hass)
    hass.config_entries = config_entries.ConfigEntries(hass, {})
    await loader.async_get_custom_components(hass)
    assert await bootstrap.async_load_base_functionality(hass)
    for dominio in bootstrap.CORE_INTEGRATIONS:
        assert await async_setup_component(hass, dominio, {}), dominio
    await async_process_ha_core_config(hass, {"time_zone": "Europe/Madrid"})
    # Un puerto libre: la integración espera a MQTT y a la app de HA, que
    # cargan el servidor web, y el 8123 puede estar ocupado.
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    assert await async_setup_component(hass, "http", {"http": {"server_port": puerto, "server_host": "127.0.0.1"}})
    hass.set_state(core.CoreState.running)
    return hass


async def aparato_con_app(hass, nombre: str, app_id: str, usuario: str, android: bool = True, user_id: str | None = None):
    """Un aparato con la app de HA, como lo deja la app al registrarse."""
    from types import MappingProxyType

    from homeassistant.config_entries import ConfigEntry, ConfigEntryDisabler
    from homeassistant.helpers import device_registry as dr, entity_registry as er

    if user_id is None:
        user_id = (await hass.auth.async_create_user(usuario)).id
    entrada = ConfigEntry(
        data={"device_id": app_id, "device_name": nombre, "user_id": user_id,
              "os_name": "Android" if android else "iOS", "webhook_id": f"w-{app_id}"},
        discovery_keys=MappingProxyType({}), domain="mobile_app", minor_version=1, options={},
        source="registration", subentries_data=None, title=nombre, unique_id=app_id, version=1,
        disabled_by=ConfigEntryDisabler.USER,  # no hace falta cargarla
    )
    await hass.config_entries.async_add(entrada)
    aparato = dr.async_get(hass).async_get_or_create(
        config_entry_id=entrada.entry_id, identifiers={("mobile_app", app_id)}, name=nombre
    )
    sensor = None
    if android:
        sensor = er.async_get(hass).async_get_or_create(
            "sensor", "mobile_app", f"w-{app_id}_last_used_app", device_id=aparato.id,
            suggested_object_id=f"{app_id}_last_used_app", config_entry=entrada,
        ).entity_id
    return aparato.id, sensor, user_id


async def recorrido(directorio: Path) -> None:
    from homeassistant.config_entries import ConfigEntryState

    hass = await arrancar(directorio)
    try:
        await hass.async_block_till_done()
        ana, sensor_ana, usuario_ana = await aparato_con_app(hass, "Movil de Ana", "app-ana", "Ana")
        luis, sensor_luis, _ = await aparato_con_app(hass, "Movil de Luis", "app-luis", "Luis")
        tableta, _, _ = await aparato_con_app(hass, "Tableta", "app-tab", "Tableta")
        reloj, _, _ = await aparato_con_app(hass, "Reloj", "app-reloj", "Ana", android=False, user_id=usuario_ana)
        for ent, valor in {
            "binary_sensor.timbre": "off", "binary_sensor.puerta": "off", "input_boolean.auto": "off",
            "input_boolean.audio": "off", "input_text.marca": "", sensor_ana: "com.otra",
            sensor_luis: "com.otra", "sensor.salon_ruta": "/marco",
        }.items():
            hass.states.async_set(ent, valor)

        # ── Alta ──
        print("\nAlta")
        fl = hass.config_entries.flow
        r = await fl.async_init("videoportero", context={"source": "user"})
        comprobar(r["type"] == "form" and r["step_id"] == "user", "primera pantalla: el videoportero")
        r = await fl.async_configure(r["flow_id"], {
            "timbre": "binary_sensor.timbre", "puerta": "binary_sensor.puerta", "camara": "camera.portal",
            "camara_frigate": "Portal", "umbral_cara": 0.95, "vista_llamada": "videoportero"})
        comprobar(r["type"] == "form" and r["step_id"] == "acciones", "segunda pantalla: lo que hay hoy en casa")
        r = await fl.async_configure(r["flow_id"], {
            "abrir_boton": "script.abrir", "abrir_automatica": "switch.motor", "apertura_automatica": "input_boolean.auto",
            "audio": "input_boolean.audio", "marca_audio": "input_text.marca", "banner": "input_text.banner",
            "al_empezar": ["script.zoom"], "al_timbre": ["script.foto"], "comparar": ["automation.visita"]})
        comprobar(r["type"] == "create_entry", f"crea la entrada ({r.get('type')})")
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries("videoportero")[0]
        comprobar(entrada.state is ConfigEntryState.LOADED, f"carga ({entrada.state})")
        r = await fl.async_init("videoportero", context={"source": "user"})
        comprobar(r["type"] == "abort", "no admite una segunda entrada")
        sistema = entrada.runtime_data
        comprobar(hass.states.get("sensor.videoportero_visita").state == "sin_visita", "sensor de visita: sin visita")
        comprobar(hass.states.get("sensor.videoportero_diferencias").state == "0", "sensor de diferencias a 0")

        # ── Dispositivos ──
        print("\nAñadir dispositivos (subentradas)")
        sub = hass.config_entries.subentries
        tipos = entrada.supported_subentry_types
        comprobar(set(tipos) == {"movil", "hogar"}, f"dos tipos: móvil y del hogar ({set(tipos)})")
        r = await sub.async_init((entrada.entry_id, "movil"), context={"source": "user"})
        comprobar(r["type"] == "form" and r["step_id"] == "user", "móvil: elegir el aparato")
        r = await sub.async_configure(r["flow_id"], {"aparato": ana})
        comprobar(r["type"] == "form" and r["step_id"] == "detalles", "móvil: detalles")
        sugerido = next((k.description or {}).get("suggested_value") for k in r["data_schema"].schema if k == "nombre")
        comprobar(sugerido == "Ana", f"sugiere el nombre del usuario de la app ({sugerido})")
        r = await sub.async_configure(r["flow_id"], {
            "nombre": "Ana", "con_dueno": True, "vista": "/videoportero/ana?kiosk", "aviso_cierre": True,
            "pide_nombre_matricula": True, "boton_abrir": True, "marca": "ana"})
        comprobar(r["type"] == "create_entry" and r["title"] == "Ana (Movil de Ana)", f"crea el móvil ({r.get('title')})")
        await hass.async_block_till_done()
        ids = {d.nombre: d.id for d in sistema.motor.dispositivos.values()}
        comprobar(set(ids) == {"Ana"}, "el motor lo tiene al momento, sin reiniciar")
        sal = sistema.casa.salidas.moviles.get(ids["Ana"])
        comprobar(sal is not None and sal.notify == "mobile_app_movil_de_ana", f"servicio de aviso deducido ({sal})")
        comprobar(sistema.casa.entradas.app.get(sensor_ana) == ids["Ana"], "sensor last_used_app deducido")
        comprobar(sistema.casa.entradas.aparatos.get("app-ana") == ids["Ana"], "device_id del botón ABRIR deducido")

        r = await sub.async_init((entrada.entry_id, "movil"), context={"source": "user"})
        r = await sub.async_configure(r["flow_id"], {"aparato": ana})
        comprobar(r["type"] == "abort" and r["reason"] == "ya_esta", "el mismo aparato dos veces: no")

        r = await sub.async_init((entrada.entry_id, "movil"), context={"source": "user"})
        r = await sub.async_configure(r["flow_id"], {"aparato": luis})
        r = await sub.async_configure(r["flow_id"], {
            "nombre": "Luis", "con_dueno": True, "aviso_cierre": True, "pide_nombre_matricula": False,
            "boton_abrir": False})
        r = await sub.async_init((entrada.entry_id, "movil"), context={"source": "user"})
        r = await sub.async_configure(r["flow_id"], {"aparato": reloj})
        r = await sub.async_configure(r["flow_id"], {
            "nombre": "Ana", "con_dueno": True, "aviso_cierre": True, "pide_nombre_matricula": False, "boton_abrir": True})
        comprobar(r["type"] == "create_entry", "un aparato iOS también vale (sin last_used_app)")
        await hass.async_block_till_done()
        comprobar(usuario_ana not in sistema.casa.entradas.usuarios,
                  "un usuario con dos aparatos no sirve para saber quién (solo el device_id)")

        r = await sub.async_init((entrada.entry_id, "hogar"), context={"source": "user"})
        comprobar(r["type"] == "form", "hogar: formulario")
        r = await sub.async_configure(r["flow_id"], {
            "nombre": "Tablet salón", "aparato": tableta, "panel": "sensor.salon_ruta", "scripts_inicio": ["script.salon_timbre"]})
        comprobar(r["type"] == "create_entry", "crea el dispositivo del hogar")
        await hass.async_block_till_done()
        comprobar(len(sistema.motor.dispositivos) == 4, f"cuatro dispositivos ({len(sistema.motor.dispositivos)})")
        salon = next(d.id for d in sistema.motor.dispositivos.values() if d.tipo == "hogar")
        comprobar(sistema.casa.entradas.panel.get("sensor.salon_ruta") == salon, "panel del hogar")

        # ── Una visita ──
        print("\nUna visita (en sombra)")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        comprobar(hass.states.get("sensor.videoportero_visita").state == "en_curso", "timbre: visita en curso")
        esperadas = list(sistema.comparador.esperadas)
        servicios = sorted({a.clave[1] for a in esperadas if a.clave[0] == "notify"})
        comprobar(servicios == ["mobile_app_movil_de_ana", "mobile_app_movil_de_luis", "mobile_app_reloj"],
                  f"habría avisado a los tres móviles ({servicios})")
        comprobar(any(a.clave[:3] == ("script", "turn_on", "script.salon_timbre") for a in esperadas),
                  "y lanzado el script de la tablet")
        hass.states.async_set(sensor_luis, APP_HA)
        await hass.async_block_till_done()
        estado = hass.states.get("sensor.videoportero_visita")
        comprobar(estado.state == "atendida", f"Luis abre la app: atendida ({estado.state})")
        comprobar(estado.attributes.get("ultima_atendida_por") == "Luis", f"y se sabe quién ({estado.attributes})")
        comprobar(len(sistema.historial.visitas) == 1 and sistema.historial.visitas[0]["como"] == "app",
                  "queda en el historial")

        # ── Comparación ──
        print("\nComparación con la automatización")
        from homeassistant.core import Context

        ctx = Context()
        hass.bus.async_fire("automation_triggered", {"entity_id": "automation.visita"}, context=ctx)
        await hass.async_block_till_done()
        # La automatización hace justo lo que esperaba la integración...
        for a in esperadas:
            dominio, servicio, entidad, datos = a.clave
            d = json.loads(datos)
            if entidad:
                d["entity_id"] = entidad
            if dominio == "notify" and isinstance(d.get("data"), dict) and d["data"].get("tag") == "visita-*":
                d["data"]["tag"] = "visita-20261003100000"
            hass.bus.async_fire("call_service", {"domain": dominio, "service": servicio, "service_data": d}, context=ctx)
        # ...más una llamada de más, y otra de otra automatización (no cuenta)
        hass.bus.async_fire("call_service", {"domain": "script", "service": "turn_on",
                                             "service_data": {"entity_id": "script.otro"}}, context=ctx)
        hass.bus.async_fire("call_service", {"domain": "script", "service": "turn_on",
                                             "service_data": {"entity_id": "script.ajeno"}}, context=Context())
        await hass.async_block_till_done()
        sistema._al_revisar()
        comprobar(sistema.historial.comparadas >= len(esperadas), f"empareja lo que coincide ({sistema.historial.comparadas})")
        sistema.comparador.plazo = 0
        sistema._al_revisar()
        await hass.async_block_till_done()
        resumenes = [d["resumen"] for d in sistema.historial.diferencias]
        comprobar(any("script.otro" in r for r in resumenes), f"apunta lo que solo hizo la automatización ({resumenes})")
        comprobar(not any("script.ajeno" in r for r in resumenes), "ignora las demás automatizaciones")
        comprobar(any("Luis ha atendido" not in r for r in resumenes), "el cierre se compara sin el «quién»")
        comprobar(hass.states.get("sensor.videoportero_diferencias").state == str(len(resumenes)),
                  "el sensor cuenta las diferencias")

        # ── Cambios en caliente ──
        print("\nCambiar y quitar dispositivos, y opciones")
        hogar_sub = next(s for s in entrada.subentries.values() if s.subentry_type == "hogar")
        r = await sub.async_init((entrada.entry_id, "hogar"), context={"source": "reconfigure", "subentry_id": hogar_sub.subentry_id})
        comprobar(r["type"] == "form" and r["step_id"] == "reconfigure", "cambiar un dispositivo del hogar")
        r = await sub.async_configure(r["flow_id"], {"nombre": "Tablet del salón", "panel": "sensor.salon_ruta"})
        comprobar(r["type"] == "abort" and r["reason"] == "reconfigure_successful", "se guarda")
        await hass.async_block_till_done()
        comprobar(any(d.nombre == "Tablet del salón" for d in sistema.motor.dispositivos.values()), "el motor lo ve al momento")
        hass.config_entries.async_remove_subentry(entrada, hogar_sub.subentry_id)
        await hass.async_block_till_done()
        comprobar(len(sistema.motor.dispositivos) == 3, "quitar un dispositivo también")
        r = await hass.config_entries.options.async_init(entrada.entry_id)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {
            "timbre": "binary_sensor.timbre", "puerta": "binary_sensor.puerta", "umbral_cara": 0.9,
            "vista_llamada": "videoportero"})
        r = await hass.config_entries.options.async_configure(r["flow_id"], {"comparar": ["automation.visita"]})
        await hass.async_block_till_done()
        comprobar(sistema.motor.ajustes.umbral_cara == 0.9, "las opciones se aplican sin reiniciar")
        comprobar(not sistema.casa.salidas.banner, "lo que se deja vacío desaparece")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        comprobar(hass.states.get("sensor.videoportero_visita").state == "en_curso", "y sigue escuchando tras el cambio")

        comprobar(await hass.config_entries.async_unload(entrada.entry_id), "se descarga limpia")
    finally:
        await hass.async_stop(force=True)


def test_traducciones() -> None:
    print("\nTraducciones")
    from custom_components.videoportero import config_flow as cf

    base = RAIZ / "custom_components" / "videoportero"
    es = json.loads((base / "strings.json").read_text("utf-8"))
    comprobar(es == json.loads((base / "translations" / "es.json").read_text("utf-8")), "strings.json = es.json")
    en = json.loads((base / "translations" / "en.json").read_text("utf-8"))

    def claves(esquema):
        return {str(k) for k in esquema.schema}

    def tiene(textos, ruta, campos):
        nodo = textos
        for p in ruta:
            nodo = nodo.get(p, {})
        return campos <= set(nodo.get("data", {}))

    for textos, idioma in ((es, "es"), (en, "en")):
        comprobar(tiene(textos, ["config", "step", "user"], claves(cf.esquema_videoportero({}))), f"{idioma}: alta 1")
        comprobar(tiene(textos, ["config", "step", "acciones"], claves(cf.esquema_acciones({}))), f"{idioma}: alta 2")
        comprobar(tiene(textos, ["config_subentries", "movil", "step", "reconfigure"], claves(cf.esquema_movil({}, True))),
                  f"{idioma}: móvil")
        comprobar(tiene(textos, ["config_subentries", "hogar", "step", "user"], claves(cf.esquema_hogar({}))), f"{idioma}: hogar")


if __name__ == "__main__":
    try:
        import homeassistant  # noqa: F401
    except ImportError:
        print("Sin Home Assistant: crea el venv (ver CLAUDE.md)")
        sys.exit(1)
    test_traducciones()
    directorio = Path(tempfile.mkdtemp(prefix="videoportero_"))
    try:
        (directorio / "custom_components").mkdir()
        (directorio / "custom_components" / "videoportero").symlink_to(RAIZ / "custom_components" / "videoportero")
        asyncio.run(recorrido(directorio))
    finally:
        shutil.rmtree(directorio, ignore_errors=True)
    print(f"\n{'TODO BIEN' if not fallos else f'{len(fallos)} FALLOS'}")
    sys.stdout.flush()
    os._exit(1 if fallos else 0)  # segfault de Python 3.14 al cerrar con HA (ver Matrículas, DECISIONES §6)
