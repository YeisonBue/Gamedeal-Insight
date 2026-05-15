# 🎮 GameDeal Insight — Documentación Técnica v3.0

## Resumen

**GameDeal Insight** es un sistema de inteligencia de precios gaming que:

- **Descubre App IDs de Steam dinámicamente** mediante scraping en segundo plano al iniciar
- Sincroniza **precio, metadata y reputación** para cada juego usando la API oficial de Steam
- Aplica **actualización inteligente**: solo registra un nuevo snapshot cuando el precio o descuento cambia
- Compara precios de un mismo juego en **múltiples plataformas** (Steam, GOG, Epic, Humble, etc.) vía [CheapShark API](https://apidocs.cheapshark.com/)
- Soporta **conversión de moneda en tiempo real** (USD, COP, EUR, GBP, BRL, MXN, ARS, CLP, CAD, JPY, AUD) con tasas cacheadas desde `open.er-api.com`
- Expone páginas HTML gaming para dashboard, catálogo y detalle individual

---

## 🏗️ Arquitectura

```text
Al iniciar:
  [Steam Search HTML scraping] ──► [DiscoveredAppId table]  (hilo daemon, no bloquea)
  [static TARGET_APP_IDS]      ──► [DiscoveredAppId table]  (seed inmediato)

Ciclo Steam (cada 6h + inmediato):
  [DiscoveredAppId table] ──► [Steam App Details API] ──► [games + price_snapshots + reputation_snapshots]
                                                            ↑ solo si precio/descuento cambió

Ciclo multi-plataforma (cada 12h):
  [games table] ──► [CheapShark API] ──► [price_snapshots] (platform = "Steam"/"GOG"/"Epic"…)

Ciclo monedas (cada 12h):
  [open.er-api.com] ──► [currency_rates table]

FastAPI src/main.py
    ├── Páginas HTML estáticas
    │   ├── /dashboard  (con selector de moneda y live refresh)
    │   ├── /catalog    (filtros, búsqueda, ordenamiento)
    │   └── /game/{slug}  (precio, reputación, historial, comparativa multi-plataforma)
    └── API JSON
        ├── /api/deals?currency=COP
        ├── /api/stats?currency=COP
        ├── /api/games?currency=COP
        ├── /api/game/{slug}/data?currency=COP
        ├── /api/game/{slug}/platform-prices?currency=COP   ← NUEVO
        ├── /api/currency/rates                             ← NUEVO
        └── /api/currency/convert?amount=59.99&to=COP       ← NUEVO
```

### Archivos clave

| Archivo | Rol |
|---|---|
| `src/models/models.py` | Modelos SQLAlchemy: `Game`, `PriceSnapshot`, `ReputationSnapshot`, `DiscoveredAppId`, `CurrencyRate` |
| `src/db/init_db.py` | Crea tablas + migración automática de columnas nuevas |
| `src/collectors/steam_collector.py` | Recolector Steam con lógica delta (no duplica snapshots iguales) |
| `src/collectors/platform_collector.py` | Precios multi-plataforma via CheapShark API |
| `src/services/currency_service.py` | Tasas de cambio en vivo cacheadas en BD |
| `src/scheduler.py` | Orquestador: discovery + sync Steam + plataformas + monedas |
| `src/main.py` | FastAPI con lifespan, todos los endpoints y conversión de moneda |
| `src/static/dashboard.html` | Dashboard con selector de moneda persistido en localStorage |
| `src/static/catalog.html` | Catálogo con selector de moneda |
| `src/static/game.html` | Detalle con tabla de comparativa multi-plataforma |
| `scraping/steam_scraper.py` | Descubrimiento de App IDs desde Steam Search (scraping HTML) |

---

## 🗄️ Modelo de datos

### `games`

```text
id (PK)
nombre
slug (único)
genero
desarrollador
publisher
fecha_lanzamiento
plataforma
steam_app_id
imagen_url
descripcion          ← NUEVO (short_description de Steam)
last_scraped_at      ← NUEVO (timestamp de última sincronización)
```

### `price_snapshots`

```text
id (PK)
game_id (FK)
source_id
platform             ← NUEVO (ej. "steam", "GOG", "Epic Games", "Humble Store"…)
precio_actual
precio_base
descuento_porcentaje
moneda               (siempre USD en origen; conversión on-the-fly en API)
fecha_captura
```

> Solo se inserta un nuevo row si `|precio_actual_nuevo - precio_actual_anterior| > 0.01` o el descuento cambió en más de 0.5 puntos.

### `reputation_snapshots`

```text
id (PK)
game_id (FK)
source_id
score_promedio
cantidad_reseñas
score_tipo
fecha_captura
```

### `discovered_app_ids` ← NUEVA

```text
id (PK)
app_id (único)          Steam App ID descubierto
discovered_at
processed               bool — true una vez sincronizado
last_check              timestamp del último fetch
```

### `currency_rates` ← NUEVA

```text
id (PK)
code (único)            ej. "COP", "EUR"
rate_from_usd           cuántas unidades de esta moneda equivalen a 1 USD
updated_at
```

---

## 🔄 Inicialización y migración automática

`src/db/init_db.py` realiza:

1. `Base.metadata.create_all(bind=engine)` — crea todas las tablas nuevas
2. `_migrate_columns()` — agrega columnas nuevas con `ALTER TABLE` si la tabla ya existía sin ellas:
   - `games`: `descripcion`, `last_scraped_at`
   - `price_snapshots`: `platform` (default `'steam'`)

Nunca es necesario borrar la BD para adoptar el nuevo esquema.

---

## 🔍 Descubrimiento de App IDs

### Flujo al iniciar

```text
1. seed_static_app_ids()
       └── Inserta TARGET_APP_IDS (~122 IDs) en discovered_app_ids si no existen

2. job_discover_app_ids() [hilo daemon, no bloquea el servidor]
       ├── scraping/steam_scraper.discover_app_ids(mode="topsellers", limit=150)
       ├── scraping/steam_scraper.discover_app_ids(mode="specials", limit=100)
       └── register_discovered_ids() → inserta los nuevos en discovered_app_ids
```

### Qué se scrapeea

`scraping/steam_scraper.py` hace scraping de `https://store.steampowered.com/search/results/` extrayendo el atributo `data-ds-appid` de cada tarjeta de resultado. Soporta 4 modos:

| Modo | Descripción |
|---|---|
| `topsellers` | Top ventas |
| `specials` | Ofertas con mayor descuento |
| `toprated` | Mejor valorados |
| `newreleases` | Lanzamientos recientes |

---

## ⚙️ Sincronización Steam (lógica delta)

`SteamCollector.save_to_db()` ahora:

1. Hace upsert de metadata del juego (incluye `descripcion` y `last_scraped_at`)
2. Antes de insertar un `PriceSnapshot`, llama a `_price_changed()`:
   - Si el precio varió en más de $0.01 → inserta nuevo snapshot
   - Si el descuento cambió en más de 0.5% → inserta nuevo snapshot
   - Si nada cambió → no toca la BD (ahorra espacio y queries innecesarios)
3. Marca el `DiscoveredAppId` como `processed=True` con `last_check` actual

### Ciclo de re-verificación

`get_pending_app_ids()` devuelve los App IDs que:
- Nunca fueron procesados (`processed=False`), **o**
- Su `last_check` es anterior a las últimas **24 horas**

Esto garantiza que cada juego se actualiza como mínimo una vez al día.

---

## 💰 Precios multi-plataforma

**Fuente:** [CheapShark API](https://apidocs.cheapshark.com/) — gratuita, sin API key.

### Plataformas rastreadas

| ID CheapShark | Tienda |
|---|---|
| 1 | Steam |
| 7 | GOG |
| 11 | Humble Store |
| 3 | Green Man Gaming |
| 13 | Fanatical |
| 25 | Epic Games |
| 2 | GamersGate |
| 23 | GameBillet |
| 31 | IndieGala |

### Flujo

```text
collect_and_store_platform_prices(game_id, name, steam_app_id)
    ├── Busca el juego en CheapShark por nombre / Steam App ID
    ├── Obtiene deals de todas las tiendas disponibles
    └── Para cada tienda: inserta PriceSnapshot(platform=nombre_tienda) solo si el precio cambió
```

Los precios se almacenan **siempre en USD**. La conversión a otras monedas es on-the-fly en la API.

---

## 🌍 Conversión de monedas

**Fuente:** `https://open.er-api.com/v6/latest/USD` — gratuita, sin API key.

### Monedas soportadas

`USD`, `COP`, `EUR`, `GBP`, `BRL`, `MXN`, `ARS`, `CLP`, `PEN`, `CAD`, `JPY`, `AUD`

### Tasas de emergencia

Si la API externa no responde, `_seed_fallback_rates()` usa tasas aproximadas hardcodeadas para que la aplicación siga funcionando sin errores.

### Lógica

```python
convert(amount_usd, "COP")  # → amount_usd * rate_from_usd["COP"]
```

Las tasas se refrescan automáticamente cada 12 horas si han pasado más de 12 horas desde la última actualización.

---

## ⏱️ Scheduler

Todos los jobs corren en un thread daemon lanzado desde el lifespan de FastAPI.

| Job | Frecuencia | Descripción |
|---|---|---|
| `seed_static_app_ids` | Al iniciar | Siembra IDs estáticos en BD |
| `job_currency_rates` | Al iniciar + cada 12h | Refresca tasas de cambio |
| `job_steam_sync` | Al iniciar + cada 6h | Sincroniza precios y metadata de Steam |
| `job_discover_app_ids` | Al iniciar (hilo separado) | Scraping de Steam Search para nuevos juegos |
| `job_platform_prices` | Cada 12h | Recorre todos los juegos y actualiza precios en otras tiendas |

### Flujo de arranque

```text
FastAPI lifespan
    └── thread daemon → scheduler.run_scheduler()
            ├── 1. seed_static_app_ids()
            ├── 2. job_currency_rates()
            ├── 3. job_steam_sync()
            ├── 4. thread daemon → job_discover_app_ids() (no bloquea el loop)
            └── 5. bucle schedule.run_pending()
```

---

## 🌐 Rutas HTML

| Ruta | Descripción |
|---|---|
| `GET /` | Redirige a `/dashboard` |
| `GET /dashboard` | Dashboard con métricas, HOT DEALS, TOP RATED y selector de moneda |
| `GET /catalog` | Catálogo con búsqueda, filtros de género y selector de moneda |
| `GET /game/{slug}` | Detalle del juego con comparativa multi-plataforma y selector de moneda |
| `GET /health` | Estado del servicio |

---

## 🔌 API REST

Todos los endpoints de precios aceptan el query param `?currency=` (default `USD`).

### `GET /api/deals?currency=COP`

Devuelve deals ordenados por descuento y reputación, con precios convertidos.

```json
{
  "juego": "Elden Ring",
  "slug": "elden-ring",
  "descripcion": "The critically acclaimed action RPG...",
  "precio_original": "COP 249.958",
  "precio_oferta": "COP 149.975",
  "precio_original_valor": 249958.0,
  "precio_oferta_valor": 149975.0,
  "moneda": "COP",
  "descuento": 40,
  "reputacion_score": 95.0,
  "reputacion_reviews": 250000
}
```

### `GET /api/stats?currency=COP`

```json
{
  "total_games": 200,
  "games_on_sale": 60,
  "best_discount": { ... },
  "avg_reputation": 89.7,
  "currency": "COP"
}
```

### `GET /api/games?currency=EUR`

Lista todos los juegos con último snapshot de precio (convertido) y reputación.

### `GET /api/game/{slug}/data?currency=EUR`

Detalle completo: metadata, precio, reputación e historial de precios (todos convertidos a la moneda solicitada).

```json
{
  "game": { "nombre": "...", "descripcion": "...", ... },
  "latest_price": {
    "precio_actual": 33.52,
    "precio_base": 55.87,
    "moneda": "EUR",
    "precio_actual_formateado": "EUR 33.52",
    ...
  },
  "price_history": [
    { "fecha": "2025-01-01", "precio": 33.52, "descuento": 40, "moneda": "EUR" }
  ]
}
```

### `GET /api/game/{slug}/platform-prices?currency=COP` ← NUEVO

Tabla comparativa del precio más reciente por tienda.

```json
{
  "game": "Elden Ring",
  "slug": "elden-ring",
  "currency": "COP",
  "platforms": [
    { "platform": "GOG",          "price": 141972, "base_price": 249958, "discount": 43.2, "price_formatted": "COP 141.972", "captured_at": "..." },
    { "platform": "Steam",        "price": 149975, "base_price": 249958, "discount": 40.0, "price_formatted": "COP 149.975", "captured_at": "..." },
    { "platform": "Humble Store", "price": 155972, "base_price": 249958, "discount": 37.6, "price_formatted": "COP 155.972", "captured_at": "..." }
  ]
}
```

Los resultados vienen ordenados de menor a mayor precio.

### `GET /api/currency/rates` ← NUEVO

```json
{
  "base": "USD",
  "rates": { "USD": 1.0, "COP": 4100.0, "EUR": 0.92, ... },
  "supported": {
    "COP": { "name": "Colombian Peso", "rate": 4100.0 },
    ...
  }
}
```

### `GET /api/currency/convert?amount=59.99&to=COP` ← NUEVO

```json
{
  "original": 59.99,
  "from": "USD",
  "to": "COP",
  "converted": 245959.0,
  "formatted": "COP 245.959"
}
```

### Rutas heredadas (compatibilidad)

- `GET /games` → alias de `/api/games`
- `GET /deals` → alias de `/api/deals`

---

## 🖥️ Frontend

### Selector de moneda

Las tres páginas (dashboard, catálogo, juego) tienen un `<select>` en el navbar con las monedas soportadas. La selección se guarda en `localStorage` bajo la clave `gamedeal_currency` y persiste entre páginas y sesiones.

### Dashboard

- Hero con panel de "Focus deal" (mejor descuento del momento)
- 4 contadores: Total juegos, En oferta, Mejor descuento, Promedio reputación
- Sección **🔥 HOT DEALS** (top 8 por descuento)
- Sección **⭐ TOP RATED** (top 8 por reputación)
- Auto-refresh cada 5 minutos respetando la moneda seleccionada

### Catálogo

- Búsqueda en vivo por nombre o desarrollador
- Chips de género generados dinámicamente desde `/api/games`
- Ordenamiento por descuento, rating, precio (asc/desc) y nombre
- Precios en la moneda activa

### Detalle individual

- Hero con imagen `capsule_616x353.jpg` de Steam CDN
- Descripción corta del juego
- Precio con descuento, botón directo a Steam
- Módulo de reputación con barra de progreso
- Gráfico de historial de precios con **Chart.js** (eje Y en moneda activa)
- **Tabla "💰 Comparativa de precios por plataforma"** — muestra precio, precio base, descuento y fecha de captura por tienda; la más barata se resalta con 🏆

### Manejo de errores

- Todas las llamadas `fetch` validan `response.ok` antes de parsear
- Mensajes amigables en caso de error de red o datos vacíos
- Fallback visual si la imagen de Steam CDN no carga

---

## 🚀 Ejecución del proyecto

### 1. Activar entorno virtual

```powershell
cd G:\Proyectos\gamedeal_insight_v1
.\venv\Scripts\activate
```

### 2. Inicializar / migrar esquema

```powershell
.\venv\Scripts\python -m src.db.init_db
```

### 3. Levantar FastAPI

```powershell
.\venv\Scripts\uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Abrir la app

```text
http://localhost:8000/dashboard
```

> Al iniciar, el scheduler arranca automáticamente:
> - Siembra los IDs estáticos
> - Descarga tasas de cambio
> - Ejecuta la primera sincronización de Steam
> - Lanza el descubrimiento de nuevos App IDs en segundo plano

---

## 🧪 Verificación recomendada

```powershell
# Compilación
python -m compileall src scraping

# Esquema
python -m src.db.init_db

# Imports
python -c "from src.main import app; print('OK')"
```

Endpoints a verificar manualmente:

- `GET /health`
- `GET /api/stats?currency=COP`
- `GET /api/deals?currency=EUR`
- `GET /api/game/{slug}/data?currency=GBP`
- `GET /api/game/{slug}/platform-prices?currency=COP`
- `GET /api/currency/rates`
- `GET /api/currency/convert?amount=59.99&to=COP`

---

## 📌 Notas

- `src/collectors/itad_collector.py` sigue siendo mock; no se usa en el flujo principal.
- Los precios se almacenan siempre en **USD** en la BD; la conversión es siempre on-the-fly.
- El scraping de Steam usa cookies `birthtime=0` y `mature_content=1` para evitar bloqueos de verificación de edad.
- CheapShark no requiere API key y tiene rate limit generoso para uso personal.
- Si `open.er-api.com` no responde, se usan tasas de emergencia hardcodeadas para evitar errores.

