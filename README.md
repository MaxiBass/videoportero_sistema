# Videoportero

Integración para Home Assistant que lleva la visita a un videoportero: cuándo
empieza y acaba, a quién se avisa y con qué texto, cuándo se abre sola la
puerta, quién ha atendido, y un historial de visitas.

No habla con el videoportero: usa los sensores de timbre y puerta de la
integración Dahua, las caras de Frigate (MQTT) y las matrículas de la
integración Matrículas.

**Estado: fase 0** (motor y pruebas). Todavía no se puede instalar. El diseño
y las fases están en [`docs/DECISIONES.md`](docs/DECISIONES.md).

## Pruebas

```bash
python3 tests/test_motor.py
```
