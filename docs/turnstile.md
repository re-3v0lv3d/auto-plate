# Turnstile: qué funciona y qué no (2026-11-03)

Probado contra el Turnstile de `historialvehiculo.com`
(sitekey `0x4AAAAAAA1fwEz8c6iW2gXh`, página `/informes-gratis-vehiculos`).

| método | resultado |
| --- | --- |
| Widget en nuestro dominio | `400070` / "no es posible conectarse" → sitekey atado a su dominio |
| Chrome headless (Playwright) | reto de página 403 |
| Chrome headed con Playwright | 403 igual (detecta CDP) |
| nodriver (Chrome real) | la página carga, pero el widget lanza `TurnstileError` y no emite token |
| EzSolver (nodriver) | `Turnstile error 600010` |
| **cfsolve (Rust, sin navegador)** | **token válido en ~4,6 s** |

cfsolve impersona Safari iOS a nivel de protocolo y resuelve el widget sin navegador.
Su API aceptó el token (HTTP 200, sin `Turnstile token validation failed`).

## Configuración

```bash
git clone https://github.com/chris124567/cfsolve.git
cd cfsolve && cargo build --release --bin challenge

export CAPTCHA_PROVIDER=cfsolve
export CFSOLVE_BIN=/ruta/cfsolve/target/release/challenge
export CFSOLVE_PROFILE=/ruta/cfsolve/profiles/safari-26-ios.json
```

Cada token tarda ~5 s y es de un solo uso.

## El bloqueo real

Con token válido, `POST /v2/vehicle/search` responde:

```json
{"bastidorItv":"","message":"ERROR_CONEXION"}
```

También con `cf_clearance` obtenido por cfsolve y el mismo User-Agent del perfil.
Su propia web lo anuncia: *"Las búsquedas por matrícula tienen un coste y las
limitamos por franja horaria"*.

Es decir: el captcha ya no es el problema; el backend no sirve búsquedas por
matrícula. La única vía automatizada es su API de pago (APIVehículo).
