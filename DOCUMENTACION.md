# 🎮 GameDeal Insight — Documentación Técnica v2.0

## Resumen

**GameDeal Insight** evolucionó a una experiencia multi-página con estética gaming, catálogo ampliado y una API REST más rica. El sistema ahora:

- Monitorea **120+ juegos reales de Steam** (122 App IDs en `TARGET_APP_IDS`)
- Guarda metadatos extra (`steam_app_id`, `imagen_url`) para enlazar y mostrar assets oficiales de Steam CDN
- Expone páginas dedicadas para dashboard, catálogo y detalle individual
- Inicia el scheduler automáticamente cuando FastAPI arranca

---

## 🏗️ Arquitectura actual

```text
[Steam App Details API] ----┐
[Steam Reviews API] --------┼--> [src/collectors/steam_collector.py] --> [PostgreSQL]
                            │
                            └--> [src/scheduler.py] (cada 6 horas + arranque inmediato)

[FastAPI src/main.py]
    ├── Páginas HTML estáticas gamer
    │   ├── /dashboard
    │   ├── /catalog
    │   └── /game/{slug}
    └── API JSON
        ├── /api/deals
        ├── /api/stats
        ├── /api/games
        └── /api/game/{slug}/data
```

### Archivos clave

| Archivo | Rol |
|---|---|
| `src/models/models.py` | Modelos SQLAlchemy con columnas nuevas para Steam (`steam_app_id`, `imagen_url`) |
| `src/db/init_db.py` | Crea tablas y ejecuta migración ligera de columnas faltantes |
| `src/collectors/steam_collector.py` | Recolector principal con 120+ App IDs, precio, reputación, género e imágenes |
| `src/scheduler.py` | Programación cada 6 horas y ejecución inmediata al iniciar |
| `src/main.py` | FastAPI + lifespan para autoarranque del scheduler |
| `src/static/dashboard.html` | Home visual con hero, métricas y rankings |
| `src/static/catalog.html` | Catálogo completo con búsqueda, filtros y ordenamiento |
| `src/static/game.html` | Vista individual del juego con Chart.js |
| `DOCUMENTACION.md` | Esta documentación |

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
steam_app_id   <- NUEVO
imagen_url     <- NUEVO
```

### `price_snapshots`

```text
id (PK)
game_id (FK)
source_id
precio_actual
precio_base
descuento_porcentaje
moneda
fecha_captura
```

> `fecha_captura` ahora usa `datetime.datetime.now(datetime.timezone.utc)` para evitar el uso obsoleto de `utcnow`.

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

---

## 🔄 Inicialización y migración ligera

`src/db/init_db.py` hace dos cosas:

1. `Base.metadata.create_all(bind=engine)`
2. `_migrate_columns()` para agregar `steam_app_id` e `imagen_url` si la tabla `games` ya existía sin esas columnas

Esto evita tener que borrar la base para adoptar el rediseño del modelo.

---

## 🎯 Recolección de Steam

El recolector usa dos endpoints oficiales:

- `https://store.steampowered.com/api/appdetails`
- `https://store.steampowered.com/appreviews/{app_id}`

### Qué guarda por juego

- Nombre del juego
- Slug para navegación `/game/{slug}`
- Género principal desde `genres[0].description`
- Desarrollador y publisher
- `steam_app_id`
- `imagen_url` (`https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg`)
- Snapshot de precio actual/base/descuento
- Snapshot de reputación (% positivas y volumen de reseñas)

### Catálogo monitorizado

`TARGET_APP_IDS` contiene **122 App IDs** repartidos entre:

- Souls / Action RPG
- Cyberpunk / Sci-Fi RPG
- CRPG / RPG
- Open World
- FPS / Action
- Horror
- Indie / Roguelikes
- Strategy
- Sony ports
- Competitive / Live Service
- Sim / Strategy / Survival
- Xbox / Capcom / Action

---

## ⏱️ Scheduler

El scheduler ahora está configurado para producción:

- **Primera sincronización inmediata** al iniciar la app
- **Frecuencia posterior:** cada **6 horas**

### Flujo

```text
FastAPI lifespan
    └── crea thread daemon
            └── scheduler.run_scheduler()
                    ├── job_steam_sync() inmediato
                    └── schedule.run_pending() en bucle
```

Ya no es obligatorio abrir una segunda terminal para que la recolección empiece cuando el servidor sube.

---

## 🌐 Rutas HTML

| Ruta | Descripción |
|---|---|
| `GET /` | Redirige a `/dashboard` |
| `GET /dashboard` | Dashboard principal con métricas, HOT DEALS y TOP RATED |
| `GET /catalog` | Catálogo completo con búsqueda, filtros y sort |
| `GET /game/{slug}` | Página individual del juego |
| `GET /health` | Estado del servicio |

---

## 🔌 API REST

### `GET /api/deals`
Devuelve los últimos snapshots consolidados por juego.

Ejemplo:

```json
{
  "juego": "Elden Ring",
  "slug": "elden-ring",
  "desarrollador": "FromSoftware",
  "genero": "RPG",
  "steam_app_id": "1245620",
  "imagen_url": "https://cdn.akamai.steamstatic.com/steam/apps/1245620/header.jpg",
  "precio_original": "USD 59.99",
  "precio_oferta": "USD 35.99",
  "descuento": 40,
  "reputacion_score": 95.0,
  "reputacion_reviews": 250000
}
```

### `GET /api/stats`
Devuelve KPIs globales:

```json
{
  "total_games": 122,
  "games_on_sale": 48,
  "best_discount": { ... },
  "avg_reputation": 89.7
}
```

### `GET /api/games`
Devuelve todos los juegos con datos base + último snapshot de precio y reputación.

### `GET /api/game/{slug}/data`
Devuelve detalle para la página individual:

```json
{
  "game": { ... },
  "latest_price": { ... },
  "latest_rep": { ... },
  "price_history": [
    { "fecha": "2025-01-01", "precio": 35.99, "descuento": 40 }
  ]
}
```

### Compatibilidad heredada

Se mantienen:

- `GET /games`
- `GET /deals`

como alias de los endpoints nuevos.

---

## 🖥️ Frontend rediseñado

### Dashboard

- Navbar fija tipo gaming
- Hero con grid animado / scanlines
- 4 contadores (`Total Juegos`, `En Oferta`, `Mejor Descuento`, `Promedio Reputación`)
- Sección **🔥 HOT DEALS**
- Sección **⭐ TOP RATED**
- Auto-refresh cada 5 minutos
- Cards con glow cyan/purple, hover y badge neón

### Catálogo

- Búsqueda en vivo por nombre o desarrollador
- Chips de género generados desde `/api/games`
- Ordenamiento por descuento, rating, precio y nombre
- Contador de resultados
- Estado vacío `No hay resultados`
- Layout responsive con grid auto-fit

### Detalle individual

- Hero con imagen grande desde Steam CDN (`capsule_616x353.jpg`)
- Metadatos principales del juego
- Caja de precio con descuento
- Botón directo a Steam
- Módulo de reputación con barra de progreso
- Historial de precios con **Chart.js**

### Manejo de errores visuales

- Todas las llamadas `fetch` validan `response.ok`
- Mensajes de error amigables en dashboard, catálogo y detalle
- Fallback visual si falla la carga de imágenes de Steam

---

## 🚀 Ejecución del proyecto

### 1. Activar entorno virtual

```powershell
cd C:\Users\Usuario\Downloads\gamedeal_insight_v1
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

> El scheduler arranca automáticamente con el servidor y ejecuta una sincronización inicial en background.

---

## 🧪 Verificación recomendada

- `python -m compileall src limpiar_db.py`
- `python -m src.db.init_db`
- Verificar `/health`
- Verificar `/api/stats`, `/api/deals`, `/api/game/{slug}/data`
- Abrir `/dashboard`, `/catalog`, `/game/{slug}`

---

## 📌 Notas finales

- `src/collectors/itad_collector.py` sigue siendo mock y no fue alterado.
- Las imágenes provienen directamente de Steam CDN.
- La experiencia visual está diseñada para escritorio y móvil usando layouts responsive.
