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

## Cadena completa (funciona)

Con el token de cfsolve:

```http
POST /v2/vehicle/search {"identificationNumber":"6110DMV","token":"1...."}
-> {"bastidorItv":"73da2aba...","message":""}

GET /v2/vehicle/73da2aba...
-> 200 con marca, modelo, etiqueta, EURO, transfers
```

Resultado real fusionado con auto-info:

```
ALFA ROMEO 147 · 2003 · 13.07.2005 · Diésel · 1910 cc · 100 CV
propietarios 3 · etiqueta SD · 1 transferencia (05/10/2017, Jaén)
```

## Límites reales

- Tokens de un solo uso: uno por consulta (~5 s).
- `WAIT_SEARCH_N`: hay que esperar N segundos entre búsquedas seguidas.
- `ERROR_CONEXION` aparece en algunas matrículas de forma puntual; reintentar.
- Matrículas de series N-Z no están soportadas por su backend.

No hay un "bloqueo" que evadir: es captcha + cooldown.
