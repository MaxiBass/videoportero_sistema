"""La visita al videoportero como máquina de estados. No importa nada de HA.

Recibe eventos con su hora (timbre, puerta, cara, matrícula, alguien atiende,
botón ABRIR...) y devuelve decisiones (empezar, avisar, abrir, terminar...).
No llama a nada ni lee estados: lo que necesita saber de la casa le llega como
evento. Así se prueba sin Home Assistant y se puede pasar por él el historial
real.

Las reglas son las de la automatización «Visita unificada» que sustituye,
una a una, y los campos de `Visita` se llaman como sus variables para poder
compararlas. Cambios deliberados respecto a ella (DECISIONES §4):

- No hay `mode: single`: ningún evento se descarta por llegar mientras se
  procesa otro.
- Se sabe quién atendió o abrió (`Atendido.quien`, `Abrir.quien`) y se dice en
  el aviso, y quien pulsa ABRIR no recibe el aviso de cierre.

El tiempo lo marca quien llama: cada evento trae su hora, y `proximo_tick()`
dice cuándo hay que mandar un `Tick` para cerrar visitas o borrar el banner.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Union

from .mensajes import boton, mensaje

# Tipos de dispositivo (DECISIONES §5)
MOVIL = "movil"
HOGAR = "hogar"

# Cómo se atendió una visita
POR_PUERTA = "puerta"  # se abrió la puerta
POR_APP = "app"  # alguien abrió la app de HA en el móvil
POR_PANEL = "panel"  # alguien entró en la vista de llamada
POR_AUDIO = "audio"  # alguien contestó con audio
POR_AUTOMATICA = "automatica"  # la abrió la apertura automática

# Cómo terminó
ATENDIDA = "atendida"
ABIERTA = "abierta_automaticamente"
SIN_RESPUESTA = "sin_respuesta"

TEXTO_BANNER = {
    ATENDIDA: "Llamada ya atendida",
    ABIERTA: "Puerta abierta automáticamente",
    SIN_RESPUESTA: "",
}


# ── Configuración ────────────────────────────────────────────────────


@dataclass(frozen=True)
class Dispositivo:
    """Un móvil (recibe avisos) o un dispositivo del hogar (no los recibe)."""

    id: str
    nombre: str
    tipo: str = MOVIL
    # Con dueño, el aviso dice «Ana ha atendido»; sin dueño (tablet, iPad),
    # «Han atendido desde Tablet salón».
    personal: bool = True
    aviso_cierre: bool = True
    pide_nombre_matricula: bool = False

    @property
    def recibe_avisos(self) -> bool:
        return self.tipo == MOVIL


@dataclass(frozen=True)
class Ajustes:
    espera: timedelta = timedelta(minutes=3)  # sin eventos, la visita termina
    banner: timedelta = timedelta(minutes=3)
    umbral_cara: float = 0.95
    max_eventos: int = 200
    # Si la puerta se abre hasta este tiempo después de pulsar ABRIR, se
    # atribuye a quien lo pulsó.
    ventana_abrir: timedelta = timedelta(seconds=60)
    imagen_camara: str = "/api/camera_proxy/camera.videoportero"
    imagen_frigate: str = "/api/frigate/notifications/{}/snapshot.jpg"


# ── Eventos (entrada) ────────────────────────────────────────────────


@dataclass(frozen=True)
class Timbre:
    hora: datetime


@dataclass(frozen=True)
class Puerta:
    """Estado del sensor de la puerta. `None`: ni abierta ni cerrada (no
    disponible); la automatización no la trataba ni como una ni como otra."""

    hora: datetime
    abierta: bool | None


@dataclass(frozen=True)
class Cara:
    """Una cara de la cámara del videoportero (ya filtrada por cámara)."""

    hora: datetime
    nombre: str
    score: float
    id: str


@dataclass(frozen=True)
class Matricula:
    """Los datos del evento `matriculas_detectada`, tal cual."""

    hora: datetime
    datos: Mapping[str, Any]


@dataclass(frozen=True)
class Atendido:
    """Alguien atiende: abre la app, entra en la vista de llamada o contesta."""

    hora: datetime
    quien: str | None
    como: str


@dataclass(frozen=True)
class Abrir:
    """Alguien pide abrir la puerta.

    Con `ejecutar`, es el botón ABRIR de un aviso y abre el motor (siempre:
    el botón no caduca, DECISIONES §7). Sin él, ya lo ha abierto otro (el
    botón del panel) y solo sirve para saber quién fue.
    """

    hora: datetime
    quien: str | None
    ejecutar: bool = True
    tag: str = ""


@dataclass(frozen=True)
class AperturaAutomatica:
    hora: datetime
    activa: bool


@dataclass(frozen=True)
class Tick:
    hora: datetime


Evento = Union[Timbre, Puerta, Cara, Matricula, Atendido, Abrir, AperturaAutomatica, Tick]


# ── Decisiones (salida) ──────────────────────────────────────────────


@dataclass(frozen=True)
class EmpiezaVisita:
    tag: str
    hora: datetime
    motivo: str


@dataclass(frozen=True)
class Avisar:
    tag: str
    destinatarios: tuple[str, ...]
    mensaje: str
    imagen: str
    suena: bool  # solo el primero de la visita; el resto lo sustituye en silencio
    boton: str
    cierre: bool  # es el aviso de que alguien ha atendido


@dataclass(frozen=True)
class PedirNombre:
    """Pide el nombre del dueño de una matrícula desconocida."""

    tag: str
    matricula: str
    imagen: str
    destinatarios: tuple[str, ...]


@dataclass(frozen=True)
class RetirarAviso:
    tag: str
    destinatarios: tuple[str, ...]


@dataclass(frozen=True)
class AbrirPuerta:
    automatica: bool
    quien: str | None = None


@dataclass(frozen=True)
class GuardarFoto:
    tag: str


@dataclass(frozen=True)
class TerminaVisita:
    visita: Visita


@dataclass(frozen=True)
class Banner:
    texto: str  # "" lo quita


Decision = Union[EmpiezaVisita, Avisar, PedirNombre, RetirarAviso, AbrirPuerta, GuardarFoto, TerminaVisita, Banner]


# ── La visita ────────────────────────────────────────────────────────


@dataclass
class Visita:
    tag: str
    inicio: datetime
    motivo: str
    imagen: str
    fin: datetime | None = None
    estado: str | None = None
    # Variables de la automatización, con su nombre
    coche: str = ""
    coche_abre: bool = False
    coche_desconocido: bool = False
    desconocida_tag: str = ""
    desconocida_frigate_id: str = ""
    persona: str = ""
    persona_desconocida: bool = False
    timbre_pulsado: bool = False
    abrimos: bool = False
    ultima_matricula: str = ""
    ultima_cara: str = ""
    cara_evento: str = ""
    persona_score: float = 0.0
    primera_notif_enviada: bool = False
    atendida: bool = False  # atendido_por != ''
    abierto_boton: bool = False
    dispositivo_atendio: str | None = None
    # Para el historial
    como: str | None = None
    eventos: int = 0
    ultimo_evento: datetime | None = None
    matriculas: list[str] = field(default_factory=list)
    caras: list[str] = field(default_factory=list)
    timbres: list[datetime] = field(default_factory=list)
    avisos: int = 0


class Motor:
    def __init__(
        self,
        dispositivos: Iterable[Dispositivo] = (),
        ajustes: Ajustes | None = None,
        *,
        puerta_abierta: bool | None = False,
        apertura_automatica: bool = False,
    ) -> None:
        self.ajustes = ajustes or Ajustes()
        self.dispositivos: dict[str, Dispositivo] = {}
        self.cambiar_dispositivos(dispositivos)
        self.puerta_abierta = puerta_abierta
        self.apertura_automatica = apertura_automatica
        self.visita: Visita | None = None
        self._banner_hasta: datetime | None = None
        self._ultimo_abrir: Abrir | None = None

    def cambiar_dispositivos(self, dispositivos: Iterable[Dispositivo]) -> None:
        """Se puede llamar en cualquier momento, también con una visita en curso."""
        self.dispositivos = {d.id: d for d in dispositivos}

    def proximo_tick(self) -> datetime | None:
        """Cuándo hay que llamar a `procesar(Tick(...))`, si hay algo pendiente."""
        pendientes = []
        if self.visita is not None and self.visita.ultimo_evento is not None:
            pendientes.append(self.visita.ultimo_evento + self.ajustes.espera)
        if self._banner_hasta is not None:
            pendientes.append(self._banner_hasta)
        return min(pendientes) if pendientes else None

    def procesar(self, ev: Evento) -> list[Decision]:
        salida: list[Decision] = []
        self._vencer(ev.hora, salida)

        if isinstance(ev, Puerta):
            # Solo abrirse cuenta, y solo de cerrada a abierta (el disparador
            # de la automatización es off → on).
            se_abre = self.puerta_abierta is False and ev.abierta is True
            self.puerta_abierta = ev.abierta
            if se_abre and self.visita is not None:
                quien = None
                abrir = self._ultimo_abrir
                if abrir is not None and ev.hora - abrir.hora <= self.ajustes.ventana_abrir:
                    quien = abrir.quien
                self._ultimo_abrir = None
                self._paso(Atendido(ev.hora, quien, POR_PUERTA), salida)
        elif isinstance(ev, Abrir):
            self._ultimo_abrir = ev
            if ev.ejecutar:
                salida.append(AbrirPuerta(automatica=False, quien=ev.quien))
        elif isinstance(ev, AperturaAutomatica):
            self.apertura_automatica = ev.activa
        elif isinstance(ev, Atendido):
            if self.visita is not None:
                self._paso(ev, salida)
        elif isinstance(ev, (Timbre, Cara, Matricula)):
            if self.visita is None:
                if self._empieza(ev):
                    self._abrir_visita(ev, salida)
                    self._paso(ev, salida)
            else:
                self._paso(ev, salida)
        return salida

    # ── Internos ──

    def _empieza(self, ev: Timbre | Cara | Matricula) -> bool:
        """Condiciones de inicio. Dentro de una visita, todo cuenta."""
        if isinstance(ev, Timbre):
            return True
        # Con la puerta abierta solo el timbre empieza una visita. (La
        # condición es «cerrada», así que si no está disponible tampoco.)
        if self.puerta_abierta is not False:
            return False
        if isinstance(ev, Matricula):
            return ev.datos.get("avisar") == True  # noqa: E712  como el filtro event_data del disparador
        return True

    def _abrir_visita(self, ev: Timbre | Cara | Matricula, salida: list[Decision]) -> None:
        motivo = {Timbre: "timbre", Cara: "cara", Matricula: "matricula"}[type(ev)]
        tag = "visita-" + ev.hora.strftime("%Y%m%d%H%M%S")
        self.visita = Visita(tag=tag, inicio=ev.hora, motivo=motivo, imagen=self.ajustes.imagen_camara)
        self._banner_hasta = None  # empezar la visita quita el banner
        salida.append(EmpiezaVisita(tag, ev.hora, motivo))

    def _vencer(self, hora: datetime, salida: list[Decision]) -> None:
        v = self.visita
        if v is not None and v.ultimo_evento is not None:
            limite = v.ultimo_evento + self.ajustes.espera
            if hora >= limite:
                self._terminar(limite, salida)
        if self._banner_hasta is not None and hora >= self._banner_hasta:
            self._banner_hasta = None
            salida.append(Banner(""))

    def _paso(self, ev: Timbre | Cara | Matricula | Atendido, salida: list[Decision]) -> None:
        """Una vuelta del bucle de la automatización con este evento."""
        v = self.visita
        assert v is not None
        if v.eventos > self.ajustes.max_eventos:
            # La automatización sale del bucle tras 201 vueltas y el evento que
            # esperaba se pierde.
            self._terminar(ev.hora, salida)
            return
        v.eventos += 1
        v.ultimo_evento = ev.hora
        notificar = False
        fin = False

        if isinstance(ev, Matricula):
            notificar = self._matricula(v, ev, salida)
        elif isinstance(ev, Cara):
            notificar = self._cara(v, ev)
        elif isinstance(ev, Timbre):
            v.timbre_pulsado = True
            notificar = True
            v.atendida = False
            v.imagen = self.ajustes.imagen_camara
            v.timbres.append(ev.hora)
            salida.append(GuardarFoto(v.tag))
        elif isinstance(ev, Atendido):
            v.atendida = True
            v.abierto_boton = ev.como == POR_PUERTA
            v.dispositivo_atendio = ev.quien
            v.como = ev.como
            notificar = True
            fin = True

        if self.puerta_abierta is True and isinstance(ev, (Matricula, Cara)):
            notificar = False

        if (
            self.apertura_automatica
            and notificar
            and not v.abrimos
            and not v.atendida
            and (v.coche_abre or v.persona or v.timbre_pulsado)
            and self.puerta_abierta is False
        ):
            salida.append(AbrirPuerta(automatica=True))
            v.abrimos = True
            v.como = POR_AUTOMATICA
            fin = True

        if notificar:
            quien = self.dispositivos.get(v.dispositivo_atendio) if v.dispositivo_atendio else None
            destinatarios = tuple(
                d.id
                for d in self.dispositivos.values()
                if d.recibe_avisos
                and d.id != v.dispositivo_atendio
                and (d.aviso_cierre or not v.atendida)
            )
            salida.append(
                Avisar(
                    tag=v.tag,
                    destinatarios=destinatarios,
                    mensaje=mensaje(v, ev.hora, quien),
                    imagen=v.imagen,
                    suena=not v.primera_notif_enviada,
                    boton=boton(v),
                    cierre=v.atendida,
                )
            )
            v.primera_notif_enviada = True
            v.avisos += 1

        if fin:
            self._terminar(ev.hora, salida)

    def _foto(self, frigate_id: Any) -> str:
        # La plantilla de la automatización escribe el id tal cual, falte o no.
        return self.ajustes.imagen_frigate.format("" if frigate_id is None else frigate_id)

    def _pide_nombre(self) -> tuple[str, ...]:
        return tuple(d.id for d in self.dispositivos.values() if d.recibe_avisos and d.pide_nombre_matricula)

    def _matricula(self, v: Visita, ev: Matricula, salida: list[Decision]) -> bool:
        d = ev.datos
        placa = str(d.get("matricula") or "")
        tipo = str(d.get("tipo") or "")
        # La integración Matrículas ya filtra las lecturas repetidas del mismo
        # coche; aquí solo cuenta otra matrícula distinta.
        if not placa or placa == v.ultima_matricula:
            return False
        v.ultima_matricula = placa
        v.imagen = self._foto(d.get("frigate_id"))
        v.matriculas.append(placa)
        frigate_id = str(d.get("frigate_id") or "")

        # El mismo coche leído mejor: se retira la petición de nombre anterior,
        # para que no se guarde nunca la primera lectura errónea.
        if v.desconocida_tag and frigate_id == v.desconocida_frigate_id:
            salida.append(RetirarAviso(v.desconocida_tag, self._pide_nombre()))
            v.desconocida_tag = ""
            v.desconocida_frigate_id = ""

        nombre = str(d.get("nombre") or "")
        if tipo == "conocida":
            # Una lectura aproximada también puede abrir (DECISIONES §7).
            v.coche = nombre
            v.coche_abre = bool(d.get("abrir", False))
            return bool(d.get("avisar", False))
        if tipo == "caducada":
            v.coche = f"{nombre} (autorización caducada)"
            v.coche_abre = False
            return True
        if tipo == "desconocida":
            v.coche_desconocido = True
            tag = f"lpr-{placa}"
            salida.append(PedirNombre(tag, placa, self._foto(d.get("frigate_id")), self._pide_nombre()))
            v.desconocida_tag = tag
            v.desconocida_frigate_id = frigate_id
            return True
        return False  # ignorada u otro tipo: nada

    def _cara(self, v: Visita, ev: Cara) -> bool:
        nombre = ev.nombre or ""
        mismo_objeto = (ev.id or "") == v.cara_evento
        conocida = ev.score > self.ajustes.umbral_cara and nombre != ""
        # Mismo objeto de Frigate: solo cuenta si mejora el score. Objeto
        # nuevo: siempre. Vuelve a avisar solo si cambia el nombre.
        if conocida and (not mismo_objeto or ev.score > v.persona_score):
            notificar = nombre != v.ultima_cara
            if notificar:
                v.caras.append(nombre)
            v.ultima_cara = nombre
            v.persona = nombre
            v.persona_score = ev.score
            v.cara_evento = ev.id or ""
            v.persona_desconocida = False
            v.imagen = self._foto(ev.id)
            return notificar
        # Desconocida: avisa una sola vez por visita.
        if not conocida and not v.persona and not v.persona_desconocida:
            v.persona_desconocida = True
            v.imagen = self._foto(ev.id)
            return True
        return False

    def _terminar(self, hora: datetime, salida: list[Decision]) -> None:
        v = self.visita
        assert v is not None
        v.fin = hora
        if v.atendida:
            v.estado = ATENDIDA
        elif v.abrimos:
            v.estado = ABIERTA
        else:
            v.estado = SIN_RESPUESTA
        self.visita = None
        salida.append(TerminaVisita(v))
        texto = TEXTO_BANNER[v.estado]
        if texto:
            salida.append(Banner(texto))
            self._banner_hasta = hora + self.ajustes.banner
