# auto-info.gratis — llamadas observadas

Reconocimiento hecho el **2026-11-03** contra `https://auto-info.gratis`.
Todo lo que sigue son peticiones HTTP normales, sin autenticación previa más
allá de las credenciales que se indican.

---

## 1. Búsqueda pública (formulario)

```http
GET /es/sprawdzam/            -> 200, Set-Cookie: PHPSESSID=...
```

```http
POST /es/sprawdzam/
Content-Type: application/x-www-form-urlencoded
Cookie: PHPSESSID=...
Referer: https://auto-info.gratis/es/

numer=6110DMV&kraj=ES&g-recaptcha-response=<token>
```

- `numer` — matrícula.
- `kraj` — país ISO-3166 alpha-2 (ES, PL, DE, FR, IT, NL, NO, SE, UA, CZ, DK, PT...).
- `g-recaptcha-response` — reCAPTCHA v2 con sitekey `6LedQaYoAAAAAOxmjCgIZNM1ANwQ1sQfvLtYDFhi`.

Sin token válido el servidor devuelve **200** y vuelve a pintar el formulario
con `class="g-recaptcha"`. Con un token aceptado devuelve una **página de
espera** ("Espere hasta 30 segundos...") que contiene este script:

```js
$.ajax({
  type: 'POST',
  url: "/es/test/",
  data: { numer: "5545LML", kraj: "ES" },
  success: function (data) { if (data != null) { window.location = data; } }
});
```

### 1.1 El endpoint real: `POST /es/test/`

```http
POST /es/test/
Content-Type: application/x-www-form-urlencoded
X-Requested-With: XMLHttpRequest
Cookie: PHPSESSID=...

numer=5545LML&kraj=ES
```

Respuesta (texto plano, ~10 s porque resuelve contra la fuente):

```
/es/raport/78e5030dd2f4c4c569efade045cb6dd6/
```

Ese hash coincide con el que publica el listado público para la misma
matrícula, así que es estable por vehículo.

### 1.2 La ficha

```http
GET /es/raport/<hash>/
Cookie: PHPSESSID=... (la misma sesión que llamó a /es/test/)
```

Devuelve **200** y una tabla con pares `<td scope="row">etiqueta</td><td>valor</td>`:
Marca, Modelo, Versión, Año de producción, Inicio de producción, Tipo de
combustible, Capacidad del motor, Potencia en kW/hp y Número de puertas.
Sin esa cookie la misma URL devuelve **503** con `Retry-After: 6000`
("Wynik tymczasowo niedostępny"), y `/pl/raport/<hash>/` sirve una plantilla
vacía.

Observación de seguridad: el servidor solo comprueba que
`g-recaptcha-response` **no esté vacío**; no valida el token contra Google.
Con un token inventado la consulta se ejecuta igual. Documentado como hallazgo,
no como vía recomendada: el flujo implementado usa el token real del widget.


---

## 2. API JSON (`/api.php`) — requiere cuenta profesional

```
GET /api.php
```

Sin parámetros:

```json
{"status":false,"refid":"","results":null,"job_status":"","error":{"error":"use GET method","error_number":2}}
```

El método se valida primero (`POST` → *use GET method*), luego la versión:

```json
{"status":false,...,"error":{"error":"wrong version","error_number":1}}
```

`version=2` es la única aceptada. Con ella, y sin el resto de variables:

```json
{"status":false,...,"error":{"error":"some variables are missing","error_number":3}}
```

### Descubrimiento de parámetros

El script pasa cada valor por `mysqli_real_escape_string()` y
`substr()`. En PHP 7, pasar un array a esas funciones emite un `Warning` con
el fichero y la línea. Enviando `?version=2&<candidato>[]=x` se obtiene un
oráculo que confirma el nombre y el orden de lectura:

| línea de `/public_html/api.php` | parámetro |
| --- | --- |
| 17 | `version` |
| 18 | `pin` |
| 19 | `access` |
| 20 | `plate` |
| 23 | `country` (pasa por `substr(..., 0, 2)`) |
| 24 | `action` |
| 26 | `lang` |

Ejemplo de fuga:

```http
GET /api.php?version=2&plate[]=x
```

```
<br /><b>Warning</b>: mysqli_real_escape_string() expects parameter 2 to be string,
array given in <b>/public_html/api.php</b> on line <b>20</b><br />
{"status":false,...,"error":{"error":"some variables are missing","error_number":3}}
```

### Firma

```
GET /api.php?version=2&pin=<PIN>&access=<CLAVE>&plate=6110DMV&country=ES&action=check&lang=es
```

Respuesta:

```json
{
  "status": true,
  "refid": "...",
  "results": { "...": "..." },
  "job_status": "...",
  "error": null
}
```

- `pin` + `access` son las credenciales de **Cuenta Profesional**
  (`/konto_pro/`): la web las llama "clave de acceso" y exime de captcha.
- Sin credenciales válidas la respuesta es siempre `error_number: 3`
  (*some variables are missing*), aunque se envíen todos los parámetros.
- `refid`/`job_status` indican una cola de trabajos: la consulta se encola y el
  resultado se recupera después.
- `results` está anidado y los nombres de campo varían por país/fuente. El
  cliente de este repo recorre el árbol y mapea alias
  (`marka`/`marca`/`make` → `make`, `pojemnosc`/`cilindrada` → `engine_cc`...).

### Códigos de error

| `error_number` | `error` | significado |
| --- | --- | --- |
| 1 | `wrong version` | `version` ausente o distinta de 2 |
| 2 | `use GET method` | se envió otro método |
| 3 | `some variables are missing` | faltan variables **o** credenciales inválidas |

---

## 3. Volcado de datos sin captcha

Los listados públicos no piden captcha y publican matrícula + marca/modelo +
hash del informe:

```
GET /es/list/ES/?page=1..N
GET /es/list/PL/
...
```

Cada página trae ~320 filas:

```html
<a href="/es/raport/3d308da0931847ab35c76672b2cfb67a/" title="ALFA ROMEO 147">6110DMV</a>
```

Países con listado: ES, PL, DE, FR, IT, NL, NO, SE, UA, CZ, DK, PT, GB, BE, AT, CH.

Los `sitemaps` (`/sitemaps/sitemap-raporty-00NN.xml.gz`, 64 ficheros) listan
además todas las URLs de informes, pero sin matrícula ni marca.

`collector/harvest_autoinfo.py` consume estos listados respetando
`Crawl-delay: 5`.

---

## 4. Resumen para el cliente

| ruta | auth | datos |
| --- | --- | --- |
| `POST /{lang}/sprawdzam/` | reCAPTCHA v2 | marca la sesión como verificada |
| `POST /{lang}/test/` | sesión verificada | ruta del informe |
| `GET /{lang}/raport/<hash>/` | misma sesión | ficha del vehículo (HTML) |
| `GET /api.php?version=2...` | `pin` + `access` | JSON con `results` |
| `GET /{lang}/list/{CC}/?page=N` | ninguna | matrícula + marca/modelo |
