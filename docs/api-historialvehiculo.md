# historialvehiculo.com — llamadas observadas

Reconocimiento hecho el **2026-11-03**. La web es una SPA React (Vite) que habla
con `https://api.historialvehiculo.com/v2`.

## 1. Bundle

```
GET /assets/index-C0p7eS3E.js    ~505 KB
```

Dentro, el cliente axios:

```js
const Ew = "https://api.historialvehiculo.com/v2";
const gf = "vehicle";

GET  `${gf}/${id}`      -> t.data.infoVehicle
POST `${gf}/search`     -> { identificationNumber, token }
GET  `${gf}/model/${e}`
```

Servicios de pago: `dgt-report/price` (13,67 €) y `maintenance-report/price`.

## 2. El endpoint gratuito

```http
GET https://api.historialvehiculo.com/v2/vehicle/<id>
```

- **Sin captcha y sin autenticación.** Responde 200 desde cualquier cliente.
- `<id>` es un SHA-256 (`bastidorItvEncrypt`) de 64 hex.
- Devuelve `{"infoVehicle": {...}}` con 45 campos + `vehicleTransfers`.

Ejemplo de campos:

```
marcaItv, modeloItv, cilindradaItv, potenciaItv (fiscal), kwItv,
co2Itv, numPlazas, categoriaHomologacionEuropeaItv, nivelEmisionesEuroItv,
tara, pesoMax, masaOrdenMarchaItv, distanciaEjes12, viaAnteriorItv, viaPosteriorItv,
fecMatricula, fecPrimMatriculacion, codPropulsionItv, bastidorItv (enmascarado),
etiquetaAmbiental, bastidorItvEncrypt
```

`vehicleTransfers[]` trae los trámites:

```
claveTramite (1 matriculación, 2 transferencia, 3 baja definitiva, 6 baja temporal...)
fecTramitacion, municipio, personaFisicaJuridica (D particular / X empresa),
numTransmisiones, numTitulares, indBajaDef, indBajaTemp, indSustraccion,
indEmbargo, indPrecinto
```

Códigos usados por su frontend:

| campo | valores |
| --- | --- |
| `codPropulsionItv` | 0 Gasolina, 1 Diésel, 2 Eléctrico, 3 Otros, 4 Butano, 5 Solar, 6 GLP, 7 GNC, 8 GNL, 9 Hidrógeno, A Biometano, B Etanol, C Biodiésel |
| `claveTramite` | 1 Matriculación, 2 Transferencia, 3 Baja definitiva, 4 Baja Plan Renove, 5 Rematriculación, 6 Baja temporal, 7 Baja por exportación |
| `personaFisicaJuridica` | D Particular, X Empresa |

CV = `ceil(kW × 1.35962)`.

## 3. La búsqueda por matrícula (protegida)

```http
POST /v2/vehicle/search
Content-Type: application/json

{"identificationNumber":"5545LML","token":"<turnstile>"}
```

- Sin token: `400 {"message":"token should not be empty..."}`.
- Token falso: `400 {"success":false,"error":"Turnstile token validation failed"}`.
- Turnstile sitekey: `0x4AAAAAAA1fwEz8c6iW2gXh`.
- La página `/informes-gratis-vehiculos` está además detrás de un reto
  gestionado de Cloudflare (403 "Un momento…" a clientes no-navegador).
- Límite: `TOO_MANY_REQUESTS` por matrícula.
- Devuelve el `bastidorItv` que se usa como `<id>` en la ruta.

Conclusión: **matrícula → id no es automatizable** sin resolver el Turnstile.
Por eso el proveedor de este repo no busca por matrícula: recibe el enlace que
el usuario obtiene tras hacer la consulta a mano en el navegador.

## 4. API comercial del mismo ecosistema

`apivehiculo.com` ofrece una API REST con clave:

```http
GET https://api.apivehiculo.com/v1/vehicles/lookup?plate=5847GKZ&country=ES
Authorization: Bearer av_live_xxx
```

Aviso en su portada: *"la búsqueda gratuita se ha limitado a 1 por usuario"*.
Es la vía sancionada si se quiere automatizar por matrícula.

## 5. Qué aporta al fusionar

| campo | origen |
| --- | --- |
| propietarios (nº) | `vehicleTransfers` expandido |
| movimientos (fecha/tipo/localidad/titular) | `vehicleTransfers` |
| etiqueta ambiental | `etiquetaAmbiental` |
| 1ª matriculación | `fecPrimMatriculacion` |
| datos técnicos (masas, ejes, CO₂, EURO) | `infoVehicle` |
| baja | `indBajaDef` / `claveTramite` 3, 4, 7 |

No incluye nombres de titulares: los datos son agregados/estadísticos y el
propietario aparece solo como "Particular" o "Empresa".
