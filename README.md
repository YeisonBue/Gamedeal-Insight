# 🎮 GameDeal Insight

**Plataforma de inteligencia de mercado para videojuegos** que compara precios en tiempo real en Steam, GOG, Epic Games, Humble Store y más, combinando el análisis de reputación para ayudarte a identificar qué ofertas realmente valen la pena.

---

## ✨ ¿Qué hace?

- 🔍 **Descubre juegos automáticamente** scrapeando Steam Search al iniciar
- 💰 **Compara precios** en hasta 15 tiendas usando la API gratuita de CheapShark
- ⭐ **Analiza reputación** con datos de reseñas de Steam
- 🌍 **Convierte precios** a 12 monedas en tiempo real (COP, EUR, USD, MXN, BRL, y más)
- 📈 **Historial de precios** por juego con gráfico interactivo
- 🔄 **Actualización inteligente**: solo guarda un nuevo snapshot cuando el precio realmente cambia

---

## 🚀 Requisitos

- [Docker](https://www.docker.com/) y Docker Compose instalados

---

## 🛠️ Instalación y ejecución

```bash
# 1. Clona o descarga el proyecto y entra a la carpeta
cd Gamedeal-Insight

# 2. Levanta la base de datos y la aplicación
docker-compose up --build
```

El servidor arranca en segundos. En paralelo, el sistema comienza a sincronizar juegos y precios en segundo plano.

Abre tu navegador en: **http://localhost:8000/dashboard**

> **Primera ejecución:** los precios de otras plataformas (GOG, Epic, etc.) aparecen ~10-15 minutos después del arranque, mientras el sistema consulta CheapShark en segundo plano.

---

## 📺 Páginas disponibles

| Ruta | Descripción |
|------|-------------|
| `/dashboard` | Panel principal: mejores ofertas, juegos mejor valorados, estadísticas globales |
| `/catalog` | Catálogo completo con búsqueda, filtros por género y ordenamiento |
| `/game/{slug}` | Detalle de un juego: precio, reputación, historial y comparativa por tienda |

---

## 🌍 Monedas soportadas

`USD` · `COP` · `EUR` · `GBP` · `BRL` · `MXN` · `ARS` · `CLP` · `PEN` · `CAD` · `JPY` · `AUD`

La moneda seleccionada se guarda automáticamente en el navegador y persiste entre páginas.

---

## 🐳 Comandos útiles

```bash
# Correr en segundo plano
docker-compose up --build -d

# Ver logs en tiempo real
docker-compose logs -f web

# Detener
docker-compose down

# Detener y borrar la base de datos
docker-compose down -v
```

---

## 🔌 API REST

Todos los endpoints de precios aceptan `?currency=` (default `USD`).

```
GET /api/deals?currency=COP          — Mejores ofertas ordenadas por descuento y reputación
GET /api/stats?currency=COP          — Estadísticas globales
GET /api/games?currency=EUR          — Catálogo completo
GET /api/game/{slug}/data            — Detalle y historial de un juego
GET /api/game/{slug}/platform-prices — Comparativa de precios por tienda
GET /api/currency/rates              — Tasas de cambio actuales
GET /api/currency/convert?amount=59.99&to=COP
GET /health                          — Estado del servicio
```

---

## 🏗️ Stack tecnológico

| Componente | Tecnología |
|---|---|
| Backend | Python 3.12 · FastAPI · SQLAlchemy |
| Base de datos | PostgreSQL 15 |
| Scraping / HTTP | httpx · BeautifulSoup4 |
| Frontend | HTML + CSS + JavaScript vanilla · Chart.js |
| Scheduler | `schedule` library · threading |
| Contenedores | Docker · Docker Compose |

> Sin API keys externas requeridas. CheapShark y open.er-api.com son gratuitas y de acceso abierto.
