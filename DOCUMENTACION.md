# 🎮 GameDeal Insight — Documentación Técnica v4.0

## ¿Qué es este proyecto?

**GameDeal Insight** es una aplicación web de inteligencia de precios para videojuegos. Su objetivo es responder a la pregunta: *¿dónde compro este juego más barato ahora mismo, y realmente vale la pena?*

Para eso, el sistema:

1. **Descubre juegos automáticamente** scrapeando Steam Search al arrancar, sin necesidad de una lista manual.
2. **Sincroniza precios y reputación** usando la API oficial de Steam.
3. **Compara precios entre tiendas** (Steam, GOG, Epic, Humble, Fanatical, etc.) usando la API gratuita de CheapShark.
4. **Convierte precios a 12 monedas** en tiempo real con tasas cacheadas desde open.er-api.com.
5. **Expone páginas web** (dashboard, catálogo, detalle) y una API REST que alimenta esas páginas.

Toda la recolección de datos ocurre en segundo plano sin bloquear el servidor.

---

## 🏗️ Arquitectura general

```
┌─────────────────────────────────────────────────────────────────┐
│                        FastAPI (src/main.py)                    │
│   /dashboard   /catalog   /game/{slug}   /api/...   /health     │
└────────────────────────────┬────────────────────────────────────┘
                             │ lee de
                    ┌────────▼────────┐
                    │   PostgreSQL    │
                    │  (SQLAlchemy)   │
                    └────────▲────────┘
                             │ escribe
┌────────────────────────────┴────────────────────────────────────┐
│               Scheduler (src/scheduler.py) — daemon thread      │
│                                                                  │
│  Al arrancar (paralelo, no bloquea el servidor):                 │
│  ├── SteamSyncInit     → Steam API → games + snapshots          │
│  ├── AppIDDiscovery    → Steam Search HTML → discovered_app_ids │
│  └── PlatformPricesInit→ CheapShark API → price_snapshots       │
│                                                                  │
│  Recurrente:                                                     │
│  ├── Steam sync        cada 6h                                   │
│  ├── Platform prices   cada 12h                                  │
│  └── Currency rates    cada 12h                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Stack tecnológico

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12 · FastAPI · Uvicorn |
| ORM / BD | SQLAlchemy 2.0 · PostgreSQL 15 |
| HTTP / Scraping | httpx · BeautifulSoup4 |
| Scheduler | `schedule` library · `threading` |
| Frontend | HTML + CSS + JavaScript vanilla · Chart.js |
| Contenedores | Docker · Docker Compose |

---

## 📁 Estructura de archivos clave

```
src/
├── main.py                     FastAPI: rutas HTML, API REST, lifespan
├── scheduler.py                Orquestador de todos los jobs en background
├── models/
│   └── models.py               Modelos SQLAlchemy (5 tablas)
├── db/
│   ├── database.py             Engine + SessionLocal + Base
│   └── init_db.py              create_all + migración automática de columnas
├── collectors/
│   ├── steam_collector.py      Recolector Steam con lógica delta
│   ├── platform_collector.py   Precios multi-tienda via CheapShark
│   └── itad_collector.py       Mock — no se usa en producción
├── services/
│   └── currency_service.py     Conversión de monedas on-the-fly
└── static/
    ├── dashboard.html
    ├── catalog.html
    └── game.html

scraping/
└── steam_scraper.py            Descubrimiento de App IDs desde Steam Search
```

---

## 🗄️ Modelo de datos

### `games`
Representa un videojuego sincronizado desde Steam.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | PK | |
| `nombre` | TEXT | Nombre del juego |
| `slug` | TEXT UNIQUE | URL-friendly, ej. `elden-ring` |
| `genero` | TEXT | |
| `desarrollador` | TEXT | |
| `publisher` | TEXT | |
| `fecha_lanzamiento` | TEXT | |
| `plataforma` | TEXT | Siempre `"PC"` |
| `steam_app_id` | TEXT | ID de Steam (clave para buscar en CheapShark) |
| `imagen_url` | TEXT | CDN de Steam |
| `descripcion` | TEXT | Short description de Steam |
| `last_scraped_at` | TIMESTAMP | Última sincronización exitosa |

### `price_snapshots`
Historial de precios. Solo se inserta una fila nueva cuando el precio o descuento realmente cambia.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | PK | |
| `game_id` | FK → games | |
| `source_id` | INT | 1 = Steam API, 2 = CheapShark |
| `platform` | TEXT | `"steam"` (Steam API) o nombre de tienda (`"GOG"`, `"Epic Games Store"`, etc.) |
| `precio_actual` | FLOAT | Precio con descuento, **siempre en USD** |
| `precio_base` | FLOAT | Precio sin descuento, **siempre en USD** |
| `descuento_porcentaje` | FLOAT | Ej. `40.0` = 40% |
| `moneda` | TEXT | Siempre `"USD"` en BD; conversión es on-the-fly |
| `fecha_captura` | TIMESTAMP | |

> **Regla delta:** se inserta nuevo snapshot solo si `|precio_nuevo - precio_anterior| > $0.01` o `|descuento_nuevo - descuento_anterior| > 0.5%`.

### `reputation_snapshots`
Reseñas de Steam por juego.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | PK | |
| `game_id` | FK → games | |
| `score_promedio` | FLOAT | Ej. `95.0` = 95% positivo |
| `cantidad_reseñas` | INT | Total de reseñas |
| `score_tipo` | TEXT | `"Overwhelmingly Positive"`, `"Mixed"`, etc. |
| `fecha_captura` | TIMESTAMP | |

### `discovered_app_ids`
Catálogo dinámico de App IDs de Steam. Es la fuente de verdad para qué juegos sincronizar.

| Columna | Tipo | Descripción |
|---|---|---|
| `id` | PK | |
| `app_id` | TEXT UNIQUE | Steam App ID |
| `discovered_at` | TIMESTAMP | |
| `processed` | BOOL | `True` = ya fue sincronizado al menos una vez |
| `last_check` | TIMESTAMP | Última sincronización con Steam API |

> El scheduler sincroniza los App IDs con `processed=False` **o** con `last_check` anterior a 24 horas.

### `currency_rates`
Tasas de cambio relativas a USD, cacheadas en BD.

| Columna | Tipo | Descripción |
|---|---|---|
| `code` | TEXT UNIQUE | Ej. `"COP"`, `"EUR"` |
| `rate_from_usd` | FLOAT | Unidades de esta moneda por 1 USD |
| `updated_at` | TIMESTAMP | |

---

## ⚙️ Inicialización y migración automática de BD

`src/db/init_db.py` hace dos cosas al ejecutarse:

1. **`Base.metadata.create_all()`** — crea todas las tablas si no existen.
2. **`_migrate_columns()`** — agrega columnas nuevas con `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` si la tabla ya existía con un esquema anterior:
   - `games`: `descripcion`, `last_scraped_at`
   - `price_snapshots`: `platform` (default `'steam'`)

**Nunca destruye datos.** Se puede re-ejecutar de forma segura.

---

## 🔄 Flujo de arranque (Scheduler)

Al iniciar FastAPI, el lifespan lanza un único hilo daemon que ejecuta `run_scheduler()`. Este hilo:

1. **`seed_static_app_ids()`** *(síncrono, rápido)* — inserta ~122 App IDs conocidos en `discovered_app_ids` si no existen.
2. **`job_currency_rates()`** *(síncrono, rápido)* — descarga tasas de cambio o aplica fallback hardcodeado.
3. Lanza **3 hilos daemon en paralelo**:

| Hilo | Qué hace | Tiempo aprox. |
|---|---|---|
| `SteamSyncInit` | Sincroniza metadata, precio y reputación para todos los App IDs pendientes | ~2-3 min |
| `AppIDDiscovery` | Scrapea Steam Search (top sellers + specials) para descubrir nuevos App IDs | ~1-2 min |
| `PlatformPricesInit` | Bulk fetch de CheapShark + fallback per-game para los no encontrados | ~10-15 min |

El servidor queda disponible inmediatamente. Los datos se van poblando en background.

### Jobs recurrentes

| Job | Frecuencia |
|---|---|
| Steam sync | Cada 6 horas |
| Platform prices | Cada 12 horas |
| Currency rates | Cada 12 horas |

---

## 🔍 Recolector de Steam (`steam_collector.py`)

Usa la API oficial `https://store.steampowered.com/api/appdetails?appids={id}`.

**`save_to_db()`** por cada App ID:
1. Upsert de metadata del juego (nombre, género, imagen, descripción, `last_scraped_at`).
2. Llama a `_price_changed()` antes de insertar un `PriceSnapshot`. Si el precio y el descuento son iguales al último registrado, **no toca la BD**.
3. Guarda un `ReputationSnapshot` con el conteo y porcentaje de reseñas.
4. Marca el `DiscoveredAppId` como `processed=True` y actualiza `last_check`.

---

## 💰 Recolector multi-plataforma (`platform_collector.py`)

Usa la API gratuita de [CheapShark](https://apidocs.cheapshark.com/). Sin API key.

### Estrategia en dos fases

**Fase 1 — Bulk fetch:**
Pagina por `/api/1.0/deals` en 3 pasadas de ordenamiento (DealRating, Savings, Price), hasta 30 páginas × 60 deals = 1.800 deals por pasada. Construye un índice `{ steamAppID → { tienda → precio } }`. Luego cruza ese índice con los juegos en BD por `steam_app_id`.

**Fase 2 — Fallback per-game:**
Los juegos que no aparecieron en el índice bulk (porque CheapShark no incluyó su `steamAppID` en el feed general) se consultan individualmente con `GET /deals?steamAppID={id}`. Tarda ~2s por juego pero asegura cobertura máxima.

### Tiendas rastreadas

| ID | Tienda | Activa |
|---|---|---|
| 1 | Steam | ✅ |
| 2 | GamersGate | ✅ |
| 3 | Green Man Gaming | ✅ |
| 7 | GOG | ✅ |
| 11 | Humble Store | ✅ |
| 13 | Uplay | ✅ |
| 15 | Fanatical | ✅ |
| 21 | WinGameStore | ✅ |
| 23 | GameBillet | ✅ |
| 25 | Epic Games Store | ✅ |
| 27 | Gamesplanet | ✅ |
| 28 | Gamesload | ✅ |
| 29 | 2Game | ✅ |
| 30 | IndieGala | ✅ |
| 35 | DreamGame | ✅ |

---

## 🌍 Conversión de monedas (`currency_service.py`)

**Fuente:** `https://open.er-api.com/v6/latest/USD` — gratuita, sin API key.

**Monedas soportadas:** `USD`, `COP`, `EUR`, `GBP`, `BRL`, `MXN`, `ARS`, `CLP`, `PEN`, `CAD`, `JPY`, `AUD`

**Lógica:**
- Las tasas se cachean en la tabla `currency_rates` y se refrescan cada 12 horas.
- Si la API externa no responde, `_seed_fallback_rates()` usa tasas aproximadas hardcodeadas para que la app no falle.
- **Los precios en BD siempre están en USD.** La conversión es siempre on-the-fly en los endpoints.

```python
convert(59.99, "COP")  # → 59.99 * tasa_cop ≈ 245.959
```

---

## 🌐 Páginas HTML

Archivos estáticos en `src/static/`. No usan ningún framework frontend — JavaScript vanilla + `fetch()`.

### `/dashboard`
- Panel "Focus Deal": el juego con mayor descuento del momento.
- Contadores: total de juegos, en oferta, mejor descuento, promedio de reputación.
- Sección **🔥 HOT DEALS**: top 8 por descuento.
- Sección **⭐ TOP RATED**: top 8 por reputación.
- Auto-refresh cada 5 minutos respetando la moneda seleccionada.

### `/catalog`
- Búsqueda en vivo por nombre o desarrollador.
- Chips de género generados dinámicamente desde `/api/games`.
- Ordenamiento por descuento, rating, precio y nombre.

### `/game/{slug}`
- Imagen hero desde Steam CDN (`capsule_616x353.jpg`).
- Precio actual, precio base y descuento con botón directo a Steam.
- Barra de reputación con porcentaje y cantidad de reseñas.
- Gráfico de historial de precios con **Chart.js**.
- **Tabla comparativa por tienda**: muestra precio, precio base, descuento y fecha de captura. La tienda más barata se resalta con 🏆.

### Selector de moneda
Disponible en las tres páginas. La selección se persiste en `localStorage` bajo la clave `gamedeal_currency` y se aplica a todas las llamadas a la API automáticamente.

---

## 🔌 API REST

Todos los endpoints de precios aceptan `?currency=` (default `USD`).

### `GET /api/deals?currency=COP`
Devuelve los mejores deals ordenados por descuento × reputación.
```json
{
  "juego": "Elden Ring",
  "slug": "elden-ring",
  "descripcion": "The critically acclaimed...",
  "precio_original": "COP 249.958",
  "precio_oferta": "COP 149.975",
  "descuento": 40,
  "reputacion_score": 95.0,
  "reputacion_reviews": 250000,
  "moneda": "COP"
}
```

### `GET /api/stats?currency=COP`
```json
{
  "total_games": 200,
  "games_on_sale": 60,
  "best_discount": { "...": "..." },
  "avg_reputation": 89.7,
  "currency": "COP"
}
```

### `GET /api/game/{slug}/data?currency=EUR`
Detalle completo con historial de precios.
```json
{
  "game": { "nombre": "...", "descripcion": "...", "steam_app_id": "..." },
  "latest_price": { "precio_actual": 33.52, "precio_base": 55.87, "moneda": "EUR" },
  "price_history": [{ "fecha": "2025-01-01", "precio": 33.52, "descuento": 40 }]
}
```

### `GET /api/game/{slug}/platform-prices?currency=COP`
Tabla comparativa de la última captura por tienda, ordenada de menor a mayor precio.
```json
{
  "game": "Elden Ring",
  "currency": "COP",
  "platforms": [
    { "platform": "GOG",   "price": 141972, "base_price": 249958, "discount": 43.2, "price_formatted": "COP 141.972" },
    { "platform": "Steam", "price": 149975, "base_price": 249958, "discount": 40.0, "price_formatted": "COP 149.975" }
  ]
}
```

### `GET /api/currency/rates`
```json
{ "base": "USD", "rates": { "COP": 4100.0, "EUR": 0.92 }, "supported": { "...": "..." } }
```

### `GET /api/currency/convert?amount=59.99&to=COP`
```json
{ "original": 59.99, "from": "USD", "to": "COP", "converted": 245959.0, "formatted": "COP 245.959" }
```

---

## 🚀 Ejecución del proyecto

### Con Docker (recomendado)

```bash
docker-compose up --build
```

- Levanta PostgreSQL 15 en puerto `5432`.
- Levanta FastAPI en puerto `8000`.
- El contenedor `web` espera a que PostgreSQL esté listo (`healthcheck`) antes de arrancar.
- Ejecuta `init_db` automáticamente antes de iniciar el servidor.

```bash
# Comandos útiles
docker-compose up --build -d          # Modo background
docker-compose logs -f web            # Ver logs en tiempo real
docker-compose down                   # Detener
docker-compose down -v                # Detener y borrar la BD
```

### Local (sin Docker)

Requiere PostgreSQL corriendo localmente.

```powershell
# Activar entorno virtual
.\venv\Scripts\activate

# Configurar BD (opcional si usas otra URL)
$env:DATABASE_URL = "postgresql://usuario:password@localhost/gamedealdb"

# Migrar/crear esquema
python -m src.db.init_db

# Levantar servidor
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## 🧪 Verificación

```powershell
# Verificar que todo compila
python -m compileall src scraping -q

# Verificar imports
python -c "from src.main import app; print('OK')"

# Migrar esquema (seguro re-ejecutar)
python -m src.db.init_db
```

Endpoints a probar manualmente tras el arranque:
```
GET /health
GET /api/stats?currency=COP
GET /api/deals?currency=EUR
GET /api/game/{slug}/platform-prices?currency=COP
GET /api/currency/rates
```

---

## 📌 Notas importantes

- `src/collectors/itad_collector.py` es un mock y **no se usa** en el flujo principal.
- Las cookies `birthtime=0` y `mature_content=1` en el scraper de Steam evitan las páginas de verificación de edad.
- CheapShark no siempre tiene todos los juegos: solo los que están activamente listados en sus tiendas asociadas.
- Si un juego muestra solo Steam en la comparativa, significa que CheapShark no lo tiene registrado en otras tiendas en ese momento.
- Las migraciones de BD nunca eliminan columnas ni tablas existentes.

