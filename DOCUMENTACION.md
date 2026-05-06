# 🎮 GameDeal Insight — Documentación Técnica

## ¿Qué es este proyecto?

**GameDeal Insight** es una plataforma de inteligencia de mercado para videojuegos. Recolecta automáticamente precios y reseñas de Steam, los almacena en una base de datos PostgreSQL y los presenta en un dashboard web en tiempo real.

---

## 🏗️ Arquitectura General

```
┌─────────────────────────────────────────────────────────┐
│                    FLUJO DEL SISTEMA                    │
│                                                         │
│  [Steam API] ──► [SteamCollector] ──► [PostgreSQL DB]  │
│  [ITAD API]  ──► [ITADCollector]  ──►    (Docker)      │
│                        │                    │           │
│              [scheduler.py]        [FastAPI Server]     │
│            (cada 1 minuto)               │              │
│                                   [Dashboard HTML]      │
│                               http://localhost:8000     │
└─────────────────────────────────────────────────────────┘
```

### Componentes principales

| Archivo | Rol |
|---|---|
| `src/main.py` | Servidor web FastAPI con los endpoints REST |
| `src/scheduler.py` | Proceso independiente que recolecta datos periódicamente |
| `src/collectors/steam_collector.py` | Llama a la API de Steam para precios y reseñas |
| `src/collectors/itad_collector.py` | Conector con IsThereAnyDeal (actualmente con datos de prueba) |
| `src/models/models.py` | Definición de tablas: `games`, `price_snapshots`, `reputation_snapshots` |
| `src/db/database.py` | Conexión a PostgreSQL via SQLAlchemy |
| `src/db/init_db.py` | Script que crea las tablas en la base de datos |
| `src/static/index.html` | Dashboard frontend (HTML + JS puro) |
| `limpiar_db.py` | Utilidad para eliminar datos de prueba |

---

## 🗄️ Modelo de Datos

```
games
├── id (PK)
├── nombre
├── slug (único)
├── genero
├── desarrollador
├── publisher
├── fecha_lanzamiento
└── plataforma

price_snapshots
├── id (PK)
├── game_id (FK → games.id)
├── source_id (1 = Steam)
├── precio_actual
├── precio_base
├── descuento_porcentaje
├── moneda
└── fecha_captura

reputation_snapshots
├── id (PK)
├── game_id (FK → games.id)
├── source_id (1 = Steam)
├── score_promedio  (% reseñas positivas)
├── cantidad_reseñas
├── score_tipo
└── fecha_captura
```

---

## 🔄 Flujo Detallado del Sistema

### 1. Recolección de datos (`scheduler.py` + `steam_collector.py`)

```
scheduler.py
    │
    ├─ Cada 1 minuto llama a job_steam_sync()
    │
    └─ SteamCollector.fetch_app_data(app_id)
            │
            ├─ GET https://store.steampowered.com/api/appdetails?appids={id}&cc=us
            │       └─ Devuelve: nombre, precio base, precio actual, % descuento
            │
            └─ GET https://store.steampowered.com/appreviews/{id}?json=1
                    └─ Devuelve: total reseñas, reseñas positivas
                         │
                         └─ SteamCollector.save_to_db()
                                 │
                                 ├─ Crea o reutiliza registro en `games`
                                 ├─ Inserta fila en `price_snapshots`
                                 └─ Inserta fila en `reputation_snapshots`
```

**Juegos monitoreados actualmente (Steam App IDs):**
| App ID | Juego |
|---|---|
| 1091500 | Cyberpunk 2077 |
| 1245620 | Elden Ring |
| 271590 | GTA V |
| 1086940 | Baldur's Gate 3 |
| 1174180 | Red Dead Redemption 2 |
| 379720 | DOOM (2016) |

### 2. Servidor web (`main.py`)

FastAPI expone tres endpoints:

| Endpoint | Descripción |
|---|---|
| `GET /health` | Estado del servicio |
| `GET /dashboard` | Sirve el HTML del dashboard |
| `GET /games` | Lista todos los juegos registrados |
| `GET /deals` | Retorna el precio y reputación más reciente de cada juego |

El endpoint `/deals` es el motor del dashboard: busca el **último snapshot** de precio y reputación para cada juego y los combina en un solo objeto JSON.

### 3. Dashboard (`index.html`)

El frontend hace un `fetch('/deals')` al cargar la página y renderiza tarjetas con:
- Nombre del juego y desarrollador
- Score de reputación (% positivo) y cantidad de reseñas
- Precio original y precio con descuento
- Badge verde si hay descuento activo

---

## 🚀 Pasos para ejecutar el proyecto

### Prerrequisitos
- Python 3.12+
- Docker Desktop corriendo
- El contenedor de PostgreSQL creado

### Paso 1 — Verificar que la base de datos Docker esté activa

```powershell
docker start gamedealdb_container
```

Verifica que esté corriendo:
```powershell
docker ps
```
Debes ver `gamedealdb_container` en estado `Up`.

### Paso 2 — Activar el entorno virtual

```powershell
cd C:\Users\Usuario\Downloads\gamedeal_insight_v1
.\venv\Scripts\activate
```

El prompt cambiará a `(venv)` confirmando que está activo.

### Paso 3 — Crear las tablas (solo la primera vez)

```powershell
python -m src.db.init_db
```

### Paso 4 — Iniciar el servidor web

En una terminal:
```powershell
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

### Paso 5 — Iniciar el recolector de datos

En **otra terminal separada** (con el venv activado):
```powershell
python -m src.scheduler
```

Este proceso hace la primera recolección inmediatamente y luego cada 1 minuto.

### Paso 6 — Abrir el dashboard

```
http://localhost:8000/dashboard
```

> **Nota:** El dashboard mostrará datos vacíos hasta que el scheduler complete su primera ejecución (~15 segundos).

---

## ⚠️ Problemas conocidos y mejoras recomendadas

Ver sección de mejoras en el README o en los comentarios del código.
