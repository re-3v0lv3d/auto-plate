# auto-plate

Identificación de coches por matrícula. Sin publicidad, sin ruido: metes la
matrícula y ves marca, modelo, versión, motor, año y VIN si están disponibles.

Es el mismo tipo de consulta que ofrece `auto-info.gratis`, pero con interfaz
propia, caché local y una sola llamada por matrícula.

```
┌─────────────────────────────────────────────┐
│ 1234 ABC   →   SEAT León 1.6 TDI 110 CV     │
│                2019 · Diésel · VIN...       │
└─────────────────────────────────────────────┘
```

## Cómo funciona

```
navegador → FastAPI → caché SQLite → proveedor 1 (API pro) → proveedor 2 (web)
```

1. **Caché** — toda matrícula consultada se guarda. Si la ficha es completa y
   tiene menos de `CACHE_TTL_DAYS` días, no se llama a nadie.
2. **API pro** (`AUTOINFO_PIN` + `AUTOINFO_ACCESS`) — JSON directo, sin captcha.
   Es la vía buena si tienes cuenta profesional en el sitio de origen.
3. **Flujo web** — reproduce la búsqueda pública completa:
   `POST /es/sprawdzam/` (captcha) → `POST /es/test/` (devuelve el hash del
   informe) → `GET /es/raport/<hash>/` (ficha). El primer resultado tarda
   ~15-20 s; luego queda en caché.

   Modos de captcha (`CAPTCHA_PROVIDER`):
   - `site` (por defecto): replica la petición del navegador. El backend del
     sitio solo comprueba que `g-recaptcha-response` no esté vacío, así que no
     hace falta resolver el widget. Es lo que hace el propio sitio.
   - `2captcha`: resuelve el reCAPTCHA v2 en servidor con `CAPTCHA_API_KEY`.
   - `manual`: exige que el cliente envíe `captcha_token` en el POST.
   - `none`: desactiva el flujo web.

Verificado con datos reales: `5545LML` → MERCEDES C (205) 200 D 9G-TRONIC,
2018, Diésel, 1597 cc, 160 CV, 5 puertas.

Además, `collector/harvest_autoinfo.py` llena la caché con los listados
públicos (matrícula + marca/modelo), así que miles de matrículas responden al
instante y sin captcha.

## Arranque

```bash
cd auto-plate
cp .env.example .env          # opcional: credenciales / captcha
./run.sh                      # http://127.0.0.1:8000
```

Sin `.env` arranca en modo caché (y el flujo web pedirá captcha en la UI).

### Poblar la caché

```bash
./.venv/bin/python collector/harvest_autoinfo.py --countries ES --pages 1-20
./.venv/bin/python collector/harvest_autoinfo.py --countries ALL --pages 1-50 --delay 5
```

### API

```bash
curl -s localhost:8000/api/lookup \
  -H 'Content-Type: application/json' \
  -d '{"plate":"1234ABC","country":"ES"}'
```

```json
{
  "ok": true,
  "found": true,
  "plate": {"normalized":"1234ABC","display":"1234 ABC","country":"ES"},
  "vehicle": {"make":"SEAT","model":"León","year":2019,"fuel":"Diésel", "...":"..."},
  "cached": true, "partial": false, "captcha_required": false,
  "attempts": [{"provider":"autoinfo-web","status":"ok","ms":812}]
}
```

Endpoints: `POST /api/lookup`, `GET /api/vehicle/{matricula}`,
`GET /api/stats`, `GET /api/config`, `GET /api/health`, docs en `/api/docs`.

## Configuración

| variable | por defecto | qué hace |
| --- | --- | --- |
| `AUTOINFO_PIN` / `AUTOINFO_ACCESS` | vacío | credenciales de la cuenta profesional |
| `CAPTCHA_PROVIDER` | `site` | `site` / `manual` / `2captcha` / `none` |
| `CAPTCHA_API_KEY` | vacío | clave de 2captcha si usas ese modo |
| `DB_PATH` | `data/vehicles.db` | SQLite |
| `STORAGE` | `sqlite` | `sqlite` / `firestore` |
| `GCP_PROJECT` | autodetectado | proyecto para Firestore |
| `FIRESTORE_PREFIX` | vacío | prefijo de colecciones |
| `CACHE_TTL_DAYS` | `30` | frescura de la caché |
| `ALLOW_WEB_PROVIDER` | `1` | desactiva el flujo web |
| `RATE_LIMIT_PER_MINUTE` | `20` | límite por IP |
| `CORS_ORIGINS` | `*` | orígenes permitidos (coma-separados) |

## Ingeniería inversa

Todo lo observado sobre las llamadas del sitio original (formulario, `/api.php`,
parámetros descubiertos por el oráculo de warnings de PHP, hashes de informe,
503 por locale, listados y sitemaps) está en
[`docs/api-autoinfo.md`](docs/api-autoinfo.md).

Puedes reproducir el descubrimiento de parámetros:

```bash
./.venv/bin/python tools/probe_api.py
```

## Despliegue

### Opción gratis sin tarjeta — Render (recomendada)

Render free: 512 MB, 0.1 CPU, 750 h/mes, sin método de pago. Se duerme a los
15 min de inactividad; el workflow `keepalive.yml` lo mantiene despierto.

1. https://dashboard.render.com → **New → Blueprint**.
2. Conecta el repo `re-3v0lv3d/auto-plate`. Render lee `render.yaml`.
3. Te pedirá `API_USER` y `API_PASSWORD`: pon `ay` y tu contraseña.
4. Deploy. Te da una URL tipo `https://auto-plate-xxxx.onrender.com`.
5. GitHub → *Settings → Variables*:

   ```
   AUTOPLATE_API = https://auto-plate-xxxx.onrender.com
   ```

6. Relanza el workflow `pages` (*Actions → pages → Run workflow*).

Listo: UI en Pages, API en Render, login validado en servidor.

Notas del plan free:

- Disco efímero: la caché vive mientras el servicio está despierto.
- Primer arranque tras dormir: ~50 s. El keepalive (cron cada 10 min) lo evita.
- 750 h/mes cubren 24/7 (720 h). Cloud Run no entra aquí: exige facturación.

### GitHub Pages: qué se puede y qué no

GitHub Pages **solo sirve ficheros estáticos**. No ejecuta Python, no hay
FastAPI, no hay SQLite y no se puede llamar a auto-info.gratis desde el
navegador (CORS). Por tanto:

| escenario | ¿funciona al 100%? |
| --- | --- |
| Solo `web/` en Pages, sin backend | No. La UI carga, pero no hay datos. |
| `web/` en Pages + backend en otro host | Sí. La UI llama a la API por HTTPS con CORS. |
| Todo en un host con Python/Docker | Sí. Es la opción recomendada. |

### Opción A — todo en un host (recomendado)

```bash
docker compose up -d --build
# http://IP:8000
```

O en un PaaS con Python (`render.yaml` incluido):

```bash
# Render / Railway / Fly: build con requirements.txt y
# start: uvicorn plate_lookup.web:app --host 0.0.0.0 --port $PORT
```

Guarda `data/` en un volumen: es la caché de matrículas.

### Opción B — UI en GitHub Pages + API aparte

Es la combinación que preguntaste: **Pages para el frontend, Cloud Run para el
backend**. Verificada sirviendo la UI en una subcarpeta (`/repo/`), como hace
Pages en proyectos.

1. Despliega el backend en Cloud Run (o Docker, Render, VPS...):

   ```bash
   PROJECT=mi-proyecto ./deploy/gcp.sh
   ```

2. En GitHub → *Settings → Pages*, elige **GitHub Actions** como source.
3. En *Settings → Secrets and variables → Actions → Variables*, crea:

   | nombre | valor |
   | --- | --- |
   | `AUTOPLATE_API` | `https://auto-plate-xxxx.europe-west1.run.app` |

   El workflow `pages.yml` inyecta esa URL en `web/static/config.js` antes de
   publicar. Si cambias de backend, solo actualizas la variable.

4. En el backend, permite el origen de Pages (sin ruta):

   ```
   CORS_ORIGINS=https://tuusuario.github.io
   ```

5. Push a `main`. La UI queda en `https://tuusuario.github.io/<repo>/`.

Requisitos: Pages es HTTPS, así que el backend también (Cloud Run lo da).
Cloud Run necesita cuenta de facturación, aunque el tramo siempre gratis
(2 M peticiones/mes) cubre de sobra este uso.

### Opción C — Google Cloud (Cloud Run + Firebase Hosting)

Google no tiene un "Firebase que ejecute Python" gratis sin tarjeta: Firebase
Hosting es solo estático y Cloud Functions exige Blaze. Lo que sí encaja es
**Cloud Run** (ejecuta este mismo contenedor) con **Firebase Hosting** delante.

```bash
chmod +x deploy/gcp.sh
PROJECT=mi-proyecto ./deploy/gcp.sh --with-hosting
```

- `firebase.json` publica `web/` y reescribe `/api/**` hacia Cloud Run, así que
  la UI y la API comparten origen (sin CORS).
- `seed/vehicles.jsonl` se importa al arrancar si la base está vacía: el disco
  de Cloud Run es efímero, pero nunca arrancas en frío. No está en el repo;
  genéralo con `python tools/export_seed.py` y móntalo en el despliegue.
- Regenera el seed cuando quieras: `python tools/export_seed.py`.

Tramos gratuitos (2026):

| servicio | gratis | requisito |
| --- | --- | --- |
| Cloud Run | 2 M peticiones, 180k vCPU-s, 360k GiB-s/mes | cuenta de facturación |
| Firebase Hosting (Spark) | 10 GB, 360 MB/día de tráfico | ninguna tarjeta |
| Firestore (Spark) | 1 GiB, 50k lecturas, 20k escrituras/día | ninguna tarjeta |
| Cloud Functions | requiere Blaze (cuotas gratis dentro) | tarjeta |
| Cloud Storage | 5 GB estándar/mes | cuenta de facturación |

Alternativa sin tarjeta: **Google Apps Script** (UrlFetchApp + una hoja de
cálculo como caché) puede hacer de proxy, pero tiene cuotas diarias, tiempos de
2-5 s y CORS incómodo con POST JSON.

## Estado (baja) y titulares

El informe gratuito **no** trae estos datos. Lo que existe:

| dato | dónde | coste |
| --- | --- | --- |
| baja del vehículo | Informe verificado de auto-info | de pago |
| baja + ITV + cargas | Informe **reducido** de la DGT | gratis, pero exige **Cl@ve** |
| titulares (nombre) | Informe completo de la DGT | 8,67 € + datos personales |
| número de titulares | Informe completo de la DGT | 8,67 € |

auto-info lo dice en su FAQ: *"No publicamos datos personales del propietario"*.
Publicar titulares en una web abierta sería un problema de RGPD, así que el
sistema **no** los busca ni los almacena.

El modelo y la UI ya soportan `status` (`baja`/`alta`) y `owners_count`, y el
parser reconoce las etiquetas (`Baja`, `Número de titulares`). Si algún día
conectas una fuente que los dé, aparecen solos: badge rojo "de baja" y celda
"Titulares". Mientras no haya fuente, la ficha muestra un enlace al trámite
oficial de la DGT.

## Fusión con HistorialVehículo

`providers/historialvehiculo.py` añade propietarios, movimientos, etiqueta
ambiental y datos técnicos desde `api.historialvehiculo.com/v2`.

Su búsqueda por matrícula está protegida con Cloudflare Turnstile.

**Modo automático (flujo idéntico):** con un resolvedor configurado, el
proveedor resuelve el Turnstile, obtiene el ID y fusiona todo en la misma
consulta:

```bash
CAPTCHA_PROVIDER=2captcha CAPTCHA_API_KEY=... ./run.sh
```

Requiere una clave de 2captcha (Turnstile, ~2-3 USD por 1000 resoluciones).
Cuando está activo, la UI oculta la caja de fusión manual y todo va por
matrícula.

**Modo manual (sin coste):** buscas a mano en historialvehiculo.com, copias la
URL `/vehiculo/<sha256>` y la pegas en la ficha → **Fusionar**.

El endpoint `GET /v2/vehicle/<sha256>` es libre: no hay captcha al leer una
ficha concreta, solo para obtener el ID desde la matrícula.

```bash
curl -u ay:... -X POST localhost:8000/api/merge \
  -H 'Content-Type: application/json' \
  -d '{"plate":"1234ABC","country":"ES","source_url":"https://www.historialvehiculo.com/vehiculo/<id>"}'
```

Detalle completo en [`docs/api-historialvehiculo.md`](docs/api-historialvehiculo.md).

## Turnstile de HistorialVehículo

`CAPTCHA_PROVIDER=cfsolve` usa [cfsolve](https://github.com/chris124567/cfsolve),
un solver libre en Rust que no necesita navegador (~5 s por token):

```bash
CFSOLVE_BIN=/ruta/cfsolve/target/release/challenge
CFSOLVE_PROFILE=/ruta/cfsolve/profiles/safari-26-ios.json
```

El token se acepta, pero su backend responde `ERROR_CONEXION` en las búsquedas
por matrícula. Detalle y pruebas en [`docs/turnstile.md`](docs/turnstile.md).

## Protección de acceso

La API se protege con HTTP Basic si defines `API_USER` y `API_PASSWORD`:

```bash
API_USER=ay API_PASSWORD=yotengoalgo ./run.sh
```

- Se aplica a todo `/api/*` salvo `/api/health`.
- El frontend muestra un login y guarda el token en `sessionStorage` (se borra
  al cerrar la pestaña). No hay credenciales en el código ni en el repo.
- **Un login en el frontend no es seguridad por sí solo**: si la contraseña
  viaja en el JS, cualquiera la lee. Aquí la valida el servidor.
- En GitHub Pages, la UI es pública; lo que queda cerrado son los datos, que
  solo salen del backend autenticado.
- Usa siempre HTTPS (Cloud Run lo da; en local, túnel o red de confianza).

## Almacenamiento: SQLite o Firestore

`STORAGE=sqlite` (por defecto, disco local) o `STORAGE=firestore`.

Firestore guarda las mismas entidades en colecciones:

| colección | doc id | contenido |
| --- | --- | --- |
| `vehicles` | `ES_1234ABC` | ficha del vehículo |
| `lookup_log` | auto | auditoría de consultas |
| `reports` | auto | HTML del informe |
| `crawl_progress` | hash | estado del crawler |

`FIRESTORE_PREFIX` permite compartir proyecto sin colisiones (`autoplate_vehicles`...).

### Probar en local con el emulador

```bash
npx --yes firebase-tools emulators:start --only firestore --project demo-autoplate
STORAGE=firestore FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 \
  GCP_PROJECT=demo-autoplate ./run.sh
```

La suite incluye tests de Firestore que se saltan solos si no hay emulador:

```bash
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 GCP_PROJECT=demo-autoplate \
  ./.venv/bin/python -m pytest -q
```

### En Cloud Run

No hay claves: el cliente usa el service account del servicio. Necesita:

- Firestore en modo **Native** (no Datastore).
- Rol `roles/datastore.user` para el service account.
- `STORAGE=firestore` en las variables de entorno (`deploy/gcp.sh` ya lo pone).

Al arrancar, si la colección `vehicles` está vacía, se importa
`seed/vehicles.jsonl` en lotes de 400. **Ese fichero no está en el repo**
(contiene matrículas): genéralo con `python tools/export_seed.py` y súbelo tú
al entorno de despliegue, o déjalo fuera y deja que la caché se llene con las
consultas.

Tramo gratis de Firestore: 1 GiB, 50k lecturas/día, 20k escrituras/día,
20k borrados/día. Cada consulta escribe 2 documentos (ficha + log), así que
da para ~10k consultas nuevas al día.

Seguridad: el SDK de servidor **se salta las reglas** de Firestore. No expongas
Firestore al navegador; el único punto de entrada es esta API.

## Estructura

```
plate_lookup/         backend (FastAPI)
  store.py            almacenamiento (SQLite | Firestore)
  providers/          autoinfo_api.py, autoinfo_web.py
collector/            recolector de listados públicos + crawler de sitemaps
web/                  interfaz (HTML/CSS/JS, sin dependencias)
  static/             styles.css, app.js, config.js
seed/                 vehicles.jsonl local (ignorado por git)
deploy/gcp.sh         Cloud Run + Firebase Hosting
tools/                probe_api.py, export_seed.py
tests/                pytest
docs/                 notas de ingeniería inversa
```

## Límites honestos

- La API `/api.php` exige credenciales de pago. El cliente está implementado
  según la firma observada, pero no se ha podido validar una respuesta `status:true`
  sin una cuenta.
- El flujo web está verificado de extremo a extremo. Depende de un captcha por
  consulta; con caché, cada matrícula se paga una sola vez.
- El parser extrae pares etiqueta/valor y no depende de clases CSS, pero si
  cambian las etiquetas hay que ampliar los alias de
  `providers/autoinfo_api.py`.
- El informe gratuito no incluye VIN ni color: solo marca, modelo, versión, año,
  primera matriculación, combustible, cilindrada, potencia y puertas.
- Respeta `robots.txt` (`Crawl-delay: 5`) y los términos del servicio de origen.
