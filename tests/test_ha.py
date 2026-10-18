"""La integración en un Home Assistant real (el del venv), sin pytest:

    /tmp/hav/bin/python tests/test_ha.py

Arranca HA en un directorio temporal con la integración enlazada en
`custom_components/`, la da de alta con sus formularios, añade dispositivos
(subentradas) y comprueba que escucha, decide y hace las llamadas. Todos los
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
    import logging

    from homeassistant.config_entries import ConfigEntryState

    # Lo que HA avisa que la integración usa y está obsoleto (p. ej. `via_device`)
    avisos_obsoletos: list[str] = []

    class Obsoletos(logging.Handler):
        def emit(self, registro: logging.LogRecord) -> None:
            texto = registro.getMessage()
            if "videoportero" in texto and "deprecated" in texto:
                avisos_obsoletos.append(texto[:200])

    logging.getLogger().addHandler(Obsoletos(logging.WARNING))
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
            "al_empezar": ["script.zoom"], "silenciar": "script.silencia", "al_timbre": ["script.foto"]})
        comprobar(r["type"] == "create_entry", f"crea la entrada ({r.get('type')})")
        await hass.async_block_till_done()
        entrada = hass.config_entries.async_entries("videoportero")[0]
        comprobar(entrada.state is ConfigEntryState.LOADED, f"carga ({entrada.state})")
        r = await fl.async_init("videoportero", context={"source": "user"})
        comprobar(r["type"] == "abort", "no admite una segunda entrada")
        sistema = entrada.runtime_data
        comprobar(hass.states.get("sensor.videoportero_visita").state == "sin_visita", "sensor de visita: sin visita")
        comprobar(hass.states.get("sensor.videoportero_diferencias") is None, "sin sensor de diferencias (no hay modo sombra)")

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
            "boton_abrir": False, "panel": "sensor.browsermod_luis_browser_path"})
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

        # ── Reparaciones ──
        print("\nReparaciones")
        from homeassistant.helpers import issue_registry as ir

        avisos = {i for (d, i) in ir.async_get(hass).issues if d == "videoportero"}
        comprobar(any(i.endswith("_sin_servicio_avisos") for i in avisos), f"avisa de que falta el servicio de avisos ({sorted(avisos)})")
        comprobar(any(i.endswith("_sin_browsermod") for i in avisos), "y de que falta el sensor de BrowserMod de Luis")
        llamadas_hechas: list[tuple[str, str, dict]] = []

        async def capturar(call):
            llamadas_hechas.append((call.domain, call.service, dict(call.data)))

        # (switch.turn_on se captura después de probar los interruptores «Avisos»)
        for dominio, servicio in (("script", "turn_on"), ("input_text", "set_value")):
            hass.services.async_register(dominio, servicio, capturar)
        for s in ("mobile_app_movil_de_ana", "mobile_app_movil_de_luis", "mobile_app_reloj", "mobile_app_tableta"):
            hass.services.async_register("notify", s, capturar)
        hass.states.async_set("sensor.browsermod_luis_browser_path", "/marco")
        sistema._al_revisar_requisitos(None)
        avisos = {i for (d, i) in ir.async_get(hass).issues if d == "videoportero"}
        comprobar(not any(i.endswith("_sin_servicio_avisos") or i.endswith("_sin_browsermod") for i in avisos),
                  f"al arreglarlo, los avisos desaparecen solos ({sorted(avisos)})")

        # ── Una visita ──
        print("\nUna visita")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        comprobar(hass.states.get("sensor.videoportero_visita").state == "en_curso", "timbre: visita en curso")
        avisos = [(s, d.get("message")) for dom, s, d in llamadas_hechas if dom == "notify"]
        comprobar(sorted(s for s, _ in avisos) == ["mobile_app_movil_de_ana", "mobile_app_movil_de_luis", "mobile_app_reloj"]
                  and all("llamando al timbre" in (m or "") for _, m in avisos),
                  f"avisa a los tres móviles, no a la tablet ({avisos})")
        hechas = {d.get("entity_id") for dom, s, d in llamadas_hechas if dom != "notify"}
        comprobar({"script.salon_timbre", "script.silencia", "script.zoom", "script.foto", "input_text.banner"} <= hechas,
                  f"lanza el script de la tablet, silencia (nadie hablaba), zoom, foto y vacía el banner ({sorted(map(str, hechas))})")
        llamadas_hechas.clear()
        hass.states.async_set(sensor_luis, APP_HA)
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        estado = hass.states.get("sensor.videoportero_visita")
        comprobar(estado.state == "atendida", f"Luis abre la app: atendida ({estado.state})")
        comprobar(estado.attributes.get("ultima_atendida_por") == "Luis", f"y se sabe quién ({estado.attributes})")
        comprobar("modo" not in estado.attributes and estado.attributes.get("llamadas_fallidas") == 0,
                  f"el sensor cuenta las llamadas, sin «modo» ({estado.attributes})")
        cierre = [(s, d.get("message")) for dom, s, d in llamadas_hechas
                  if dom == "notify" and d.get("message") != "clear_notification"]
        comprobar(cierre and all(m.startswith("Luis ha atendido") for _, m in cierre)
                  and "mobile_app_movil_de_luis" not in [s for s, _ in cierre],
                  f"«Luis ha atendido» a los demás, a él no ({cierre})")
        retirado = [(s, d.get("data", {}).get("tag", "")) for dom, s, d in llamadas_hechas
                    if dom == "notify" and d.get("message") == "clear_notification"]
        comprobar(len(retirado) == 1 and retirado[0][0] == "mobile_app_movil_de_luis" and retirado[0][1].startswith("visita-"),
                  f"y a Luis, que ha contestado, se le retira el aviso de la visita ({retirado})")
        comprobar(any(dom == "input_text" and d.get("value") == "Llamada ya atendida" for dom, s, d in llamadas_hechas),
                  "y escribe el banner")
        comprobar(len(sistema.historial.visitas) == 1 and sistema.historial.visitas[0]["como"] == "app",
                  "queda en el historial")
        vis = "sensor.browsermod_luis_browser_visibility"
        comprobar(sistema.casa.entradas.visible.get(vis) is not None,
                  "encuentra sola la visibilidad de BrowserMod junto al sensor de ruta")
        hass.states.async_set(vis, "hidden")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        comprobar(hass.states.get("sensor.videoportero_visita").state == "en_curso", "otra visita (HA ya era su última app)")
        hass.states.async_set(vis, "visible")
        await hass.async_block_till_done()
        estado = hass.states.get("sensor.videoportero_visita")
        comprobar(estado.state == "atendida" and estado.attributes.get("ultima_atendida_por") == "Luis",
                  f"la página de HA pasa a verse en su móvil: atendida por Luis ({estado.state})")
        hass.states.async_set("binary_sensor.timbre", "off")
        await hass.async_block_till_done()

        # ── Interruptores de avisos ──
        print("\nInterruptores «Avisos»")
        interruptores = sorted(e.entity_id for e in hass.states.async_all("switch") if e.entity_id.startswith("switch.videoportero_avisos_"))
        comprobar(len(interruptores) == 4 and "switch.videoportero_avisos_ana_movil_de_ana" in interruptores,
                  f"un interruptor por dispositivo, con entity_id fijo ({interruptores})")
        comprobar(all(hass.states.get(i).state == "on" for i in interruptores), "encendidos por defecto")
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.videoportero_avisos_ana_movil_de_ana"}, blocking=True)
        await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.videoportero_avisos_tablet_salon_tableta"}, blocking=True)
        await hass.async_block_till_done()
        ana_id = next(i for i, d in sistema.motor.dispositivos.items() if d.nombre == "Ana" and sistema.casa.salidas.moviles.get(i) and sistema.casa.salidas.moviles[i].notify == "mobile_app_movil_de_ana")
        comprobar(ana_id in sistema.apagados, "apagar el interruptor apaga ese dispositivo")
        llamadas_hechas.clear()
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        servicios = sorted({s for dom, s, _ in llamadas_hechas if dom == "notify"})
        comprobar("mobile_app_movil_de_ana" not in servicios and "mobile_app_movil_de_luis" in servicios,
                  f"en la visita, Ana no recibe avisos y Luis sí ({servicios})")
        comprobar(not any(d.get("entity_id") == "script.salon_timbre" for _, _, d in llamadas_hechas),
                  "y la tablet apagada no lanza su script")
        await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.videoportero_avisos_ana_movil_de_ana"}, blocking=True)
        await hass.async_block_till_done()
        comprobar(ana_id not in sistema.apagados, "encenderlo lo vuelve a activar")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.services.async_register("switch", "turn_on", capturar)  # el motor de la puerta

        # ── Dispositivos en el registro ──
        print("\nDispositivos en el registro")
        from homeassistant.helpers import device_registry as dr

        registro = dr.async_get(hass)
        principal = registro.async_get(sistema.dispositivo_id)
        comprobar(principal is not None and principal.identifiers == {("videoportero", entrada.entry_id)},
                  "el dispositivo principal existe desde el arranque")
        hijos = [d for d in dr.async_entries_for_config_entry(registro, entrada.entry_id) if d.id != principal.id]
        comprobar(len(hijos) == 4 and all(d.via_device_id == principal.id for d in hijos),
                  f"los de cada móvil y del hogar cuelgan de él ({len(hijos)})")
        comprobar(not avisos_obsoletos, f"sin avisos de HA por usar algo obsoleto ({avisos_obsoletos})")

        # ── Conversación ──
        print("\nMientras se habla por el videoportero")
        import json as _json
        from datetime import timedelta as _td

        from custom_components.videoportero.motor import Tick

        def cara(ident):
            sistema._al_mqtt(type("M", (), {"payload": _json.dumps(
                {"type": "face", "camera": "Portal", "name": "", "score": 0.0, "id": ident})})())

        sistema.motor.puerta_cambio = sistema.motor.audio_cambio = None
        hass.states.async_set("input_boolean.audio", "on")
        await hass.async_block_till_done()
        comprobar(sistema.motor.hablando, "encender el audio: se está hablando")
        cara("c1")
        comprobar(sistema.motor.visita is None, "hablando, una cara no empieza visita")
        llamadas_hechas.clear()
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        await asyncio.sleep(0.2)
        comprobar(sistema.motor.visita is not None, "un timbre sí")
        comprobar(not any(d.get("entity_id") == "script.silencia" for _, _, d in llamadas_hechas),
                  "pero sin silenciar el altavoz: no corta la conversación")
        sistema.motor.procesar(Tick(sistema.motor.visita.ultimo_evento + _td(minutes=4)))
        hass.states.async_set("input_boolean.audio", "off")
        await hass.async_block_till_done()
        comprobar(not sistema.motor.hablando, "colgar: ya no se habla")
        cara("c2")
        comprobar(sistema.motor.visita is None, "recién colgado, una cara tampoco")
        sistema.motor.audio_cambio -= _td(seconds=61)
        sistema.motor.puerta_cambio = None
        cara("c3")
        comprobar(sistema.motor.visita is not None, "al minuto de colgar, sí")
        sistema.motor.procesar(Tick(sistema.motor.visita.ultimo_evento + _td(minutes=4)))
        hass.states.async_set("binary_sensor.timbre", "off")

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
        comprobar(hass.states.get("switch.videoportero_avisos_tablet_salon_tableta") is None, "y su interruptor desaparece")
        r = await sub.async_init((entrada.entry_id, "hogar"), context={"source": "user"})
        r = await sub.async_configure(r["flow_id"], {"nombre": "Tablet cocina"})
        await hass.async_block_till_done()
        comprobar(hass.states.get("switch.videoportero_avisos_tablet_cocina") is not None,
                  "un dispositivo nuevo trae su interruptor, sin reiniciar")
        r = await hass.config_entries.options.async_init(entrada.entry_id)
        r = await hass.config_entries.options.async_configure(r["flow_id"], {
            "timbre": "binary_sensor.timbre", "puerta": "binary_sensor.puerta", "umbral_cara": 0.9,
            "vista_llamada": "videoportero"})
        r = await hass.config_entries.options.async_configure(r["flow_id"], {})
        await hass.async_block_till_done()
        comprobar(sistema.motor.ajustes.umbral_cara == 0.9, "las opciones se aplican sin reiniciar")
        comprobar(not sistema.casa.salidas.banner, "lo que se deja vacío desaparece")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        comprobar(hass.states.get("sensor.videoportero_visita").state == "en_curso", "y sigue escuchando tras el cambio")

        # ── Botón ABRIR, apertura automática y orden de las llamadas ──
        print("\nBotón ABRIR, apertura automática y orden de las llamadas")
        acciones = {"abrir_boton": "script.abrir", "abrir_automatica": "switch.motor", "audio": "input_boolean.audio",
                    "marca_audio": "input_text.marca", "banner": "input_text.banner", "al_empezar": ["script.zoom"],
                    "silenciar": "script.silencia", "al_timbre": ["script.foto"]}
        videoportero = {"timbre": "binary_sensor.timbre", "puerta": "binary_sensor.puerta", "umbral_cara": 0.95,
                        "vista_llamada": "videoportero"}
        sistema._procesar([Tick(sistema.motor.visita.ultimo_evento + _td(minutes=4))])
        hass.states.async_set("binary_sensor.timbre", "off")
        r = await hass.config_entries.options.async_init(entrada.entry_id)
        r = await hass.config_entries.options.async_configure(r["flow_id"], videoportero)
        r = await hass.config_entries.options.async_configure(r["flow_id"], acciones)
        await hass.async_block_till_done()
        comprobar(r["type"] == "create_entry" and sistema.casa.salidas.abrir_boton == "script.abrir",
                  "(vuelven las acciones a las opciones)")
        llamadas_hechas.clear()
        hass.bus.async_fire("mobile_app_notification_action", {"action": "ABRIR_PUERTA", "device_id": "app-ana", "tag": "x"})
        await hass.async_block_till_done()
        await asyncio.sleep(0.2)
        comprobar(("script", "turn_on", {"entity_id": "script.abrir"}) in llamadas_hechas, "el botón ABRIR abre")
        comprobar(not any(d.get("message") == "clear_notification" for _, _, d in llamadas_hechas),
                  "y a quien abre no se le retira el aviso")

        # 15/10, 17:14: abre con ABRIR (termina la visita) y luego contesta.
        hass.states.async_set(sensor_luis, "com.otra")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        hass.bus.async_fire("mobile_app_notification_action", {"action": "ABRIR_PUERTA", "device_id": "app-luis", "tag": "x"})
        await hass.async_block_till_done()
        hass.states.async_set("binary_sensor.puerta", "on")
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        comprobar(hass.states.get("sensor.videoportero_visita").state == "atendida"
                  and not any(d.get("message") == "clear_notification" for _, _, d in llamadas_hechas),
                  "Luis abre con ABRIR: termina la visita y el aviso se le queda")
        llamadas_hechas.clear()
        hass.states.async_set(sensor_luis, APP_HA)
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        retirado = [(s, d.get("data", {}).get("tag", "")) for dom, s, d in llamadas_hechas
                    if dom == "notify" and d.get("message") == "clear_notification"]
        comprobar(len(retirado) == 1 and retirado[0][0] == "mobile_app_movil_de_luis" and retirado[0][1].startswith("visita-")
                  and len(llamadas_hechas) == 1,
                  f"si luego contesta, se le retira, y nada más ({llamadas_hechas})")
        hass.states.async_set("binary_sensor.puerta", "off")
        await hass.async_block_till_done()

        # 15/10, 17:51: otra visita, con el banner de la anterior aún puesto,
        # que nadie atiende: el sensor no se queda con el estado anterior.
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        sistema._procesar([Tick(sistema.motor.visita.ultimo_evento + _td(minutes=4))])
        await hass.async_block_till_done()
        await asyncio.sleep(0.2)
        estado = hass.states.get("sensor.videoportero_visita")
        comprobar(estado.state == "sin_visita" and estado.attributes.get("ultima_estado") == "sin_respuesta",
                  f"una visita sin respuesta tras una atendida: sin visita ({estado.state})")

        # 18/10, 13:16: el timbre abre solo y, 20 ms después, llega otra cara de
        # la misma persona con la puerta aún sin abrir: no empieza otra visita.
        def cara_aqui(ident):
            sistema._al_mqtt(type("M", (), {"payload": _json.dumps(
                {"type": "face", "camera": sistema.casa.entradas.camara_caras, "name": "", "score": 0.0, "id": ident})})())

        sistema.motor.apertura_automatica = True
        sistema.motor.puerta_cambio = sistema.motor.audio_cambio = None
        hass.states.async_set("binary_sensor.timbre", "off")
        cara_aqui("d1")
        await hass.async_block_till_done()
        comprobar(sistema.motor.visita is not None, "(una cara empieza la visita)")
        llamadas_hechas.clear()
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        cara_aqui("d1")
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        abre = [d for dom, _, d in llamadas_hechas if dom == "switch" and d.get("entity_id") == "switch.motor"]
        empieza = [d for _, _, d in llamadas_hechas if d.get("entity_id") == "script.zoom"]
        comprobar(abre and not empieza and sistema.motor.visita is None,
                  f"el timbre abre solo y la cara de después no empieza otra visita ({len(abre)} aperturas, "
                  f"{len(empieza)} visitas nuevas)")
        hass.states.async_set("binary_sensor.puerta", "on")
        await hass.async_block_till_done()
        comprobar(sistema.motor.abriendo_hasta is None and hass.states.get("sensor.videoportero_visita").state
                  == "abierta_automaticamente", "se abre la puerta: manda el sensor y queda «abierta automáticamente»")
        hass.states.async_set("binary_sensor.puerta", "off")
        hass.states.async_set("binary_sensor.timbre", "off")
        await hass.async_block_till_done()
        sistema.motor.apertura_automatica = False

        # Un aviso que tarda (el 15/10 uno tardó 10 s) no frena el botón ABRIR
        # ni los avisos a los demás móviles; los de ese móvil siguen en orden.
        async def aviso_lento(call):
            llamadas_hechas.append((call.domain, call.service, dict(call.data)))
            await asyncio.sleep(1.5)

        hass.services.async_register("notify", "mobile_app_movil_de_ana", aviso_lento)
        llamadas_hechas.clear()
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        hass.bus.async_fire("mobile_app_notification_action", {"action": "ABRIR_PUERTA", "device_id": "app-luis", "tag": "x"})
        await asyncio.sleep(0.3)
        comprobar(("script", "turn_on", {"entity_id": "script.abrir"}) in llamadas_hechas,
                  "con el aviso de Ana tardando, el ABRIR abre al momento")
        comprobar(any(s == "mobile_app_movil_de_luis" for _, s, _ in llamadas_hechas), "y a Luis le llega su aviso al momento")
        hass.states.async_set("binary_sensor.timbre", "off")
        hass.states.async_set("binary_sensor.timbre", "on")
        await hass.async_block_till_done()
        await asyncio.sleep(0.3)
        de_ana = [d.get("message") for _, s, d in llamadas_hechas if s == "mobile_app_movil_de_ana"]
        comprobar(len(de_ana) == 1, f"el segundo aviso a Ana espera a que acabe el primero ({len(de_ana)} empezados)")
        await asyncio.sleep(3.2)
        de_ana = [d.get("data", {}).get("alert_once") for _, s, d in llamadas_hechas if s == "mobile_app_movil_de_ana"]
        comprobar(de_ana == [False, True], f"y le llegan en orden: primero el que suena ({de_ana})")
        hass.services.async_register("notify", "mobile_app_movil_de_ana", capturar)
        hass.states.async_set("binary_sensor.timbre", "off")
        estado = hass.states.get("sensor.videoportero_visita")
        comprobar(estado.attributes.get("llamadas_hechas", 0) > 0 and estado.attributes.get("llamadas_fallidas") == 0,
                  f"y lleva la cuenta de sus llamadas ({estado.attributes.get('llamadas_hechas')} hechas, "
                  f"{estado.attributes.get('llamadas_fallidas')} fallidas)")

        hass.states.async_set("input_text.banner", "Llamada ya atendida")
        await hass.config_entries.async_reload(entrada.entry_id)
        await hass.async_block_till_done()
        sistema = entrada.runtime_data
        comprobar(sistema.banner == "Llamada ya atendida" and sistema.motor.banner_hasta is not None,
                  "un banner que quedó escrito antes de reiniciar se borrará a su hora")
        hass.states.async_set("binary_sensor.timbre", "off")

        # ── Migración de una instalación con modo sombra (hasta la v0.2.3) ──
        print("\nMigración: fuera el modo sombra")
        from homeassistant.helpers import entity_registry as er

        comprobar(entrada.minor_version == 2, f"una entrada nueva ya es la 1.2 ({entrada.version}.{entrada.minor_version})")
        comprobar(await hass.config_entries.async_unload(entrada.entry_id), "(se descarga)")
        registro_e = er.async_get(hass)
        registro_e.async_get_or_create("sensor", "videoportero", f"{entrada.entry_id}_diferencias", config_entry=entrada,
                                       suggested_object_id="videoportero_diferencias")
        hass.config_entries.async_update_entry(
            entrada, options={**entrada.options, "comparar": ["automation.visita"], "activa": True}, minor_version=1)
        await hass.config_entries.async_setup(entrada.entry_id)
        await hass.async_block_till_done()
        comprobar(entrada.state is ConfigEntryState.LOADED and entrada.minor_version == 2,
                  f"migra a la 1.2 y carga ({entrada.state}, {entrada.version}.{entrada.minor_version})")
        comprobar("comparar" not in entrada.options and "activa" not in entrada.options
                  and entrada.options.get("abrir_boton") == "script.abrir",
                  f"quita «comparar» y «activa» y deja lo demás ({sorted(entrada.options)})")
        comprobar(registro_e.async_get_entity_id("sensor", "videoportero", f"{entrada.entry_id}_diferencias") is None,
                  "y el sensor de diferencias")

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
