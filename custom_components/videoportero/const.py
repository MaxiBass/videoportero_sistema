"""Constantes de la integración Videoportero."""

DOMAIN = "videoportero"

# Tipos de subentrada (DECISIONES §5)
SUB_MOVIL = "movil"
SUB_HOGAR = "hogar"

# Opciones de la entrada: el videoportero
CONF_TIMBRE = "timbre"
CONF_PUERTA = "puerta"
CONF_CAMARA = "camara"
CONF_CAMARA_FRIGATE = "camara_frigate"
CONF_PERSONAS = "personas"  # sensor de Frigate: personas en la cámara
CONF_UMBRAL_CARA = "umbral_cara"
CONF_VISTA_LLAMADA = "vista_llamada"

# Opciones de la entrada: lo que hay hoy en casa (ayudantes y scripts que la
# integración sigue usando hasta la fase 3)
CONF_ABRIR_BOTON = "abrir_boton"
CONF_ABRIR_AUTOMATICA = "abrir_automatica"
CONF_APERTURA_AUTOMATICA = "apertura_automatica"
CONF_AUDIO = "audio"
CONF_MARCA_AUDIO = "marca_audio"
CONF_BANNER = "banner"
CONF_AL_EMPEZAR = "al_empezar"
CONF_AL_TIMBRE = "al_timbre"

# Opciones de la entrada: modo sombra
CONF_COMPARAR = "comparar"  # automatizaciones con las que se compara

# Subentradas
CONF_NOMBRE = "nombre"
CONF_APARATO = "aparato"  # dispositivo de la app de HA
CONF_CON_DUENO = "con_dueno"
CONF_VISTA = "vista"
CONF_PANEL = "panel"  # sensor de ruta de BrowserMod
CONF_AVISO_CIERRE = "aviso_cierre"
CONF_PIDE_NOMBRE = "pide_nombre_matricula"
CONF_BOTON_ABRIR = "boton_abrir"
CONF_MARCA = "marca"  # valor que escriben sus scripts de contestar (hasta la fase 3)
CONF_SCRIPTS_INICIO = "scripts_inicio"

DEFECTO_UMBRAL_CARA = 0.95
DEFECTO_VISTA_LLAMADA = "videoportero"

TOPIC_CARAS = "frigate/tracked_object_update"
EVENTO_MATRICULA = "matriculas_detectada"
EVENTO_ACCION_AVISO = "mobile_app_notification_action"

DIAS_HISTORIAL = 90  # decisión de Maxi (DECISIONES §7)

SENAL_CAMBIO = f"{DOMAIN}_cambio"
