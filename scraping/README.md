# 🕷️ Steam Scraper

Módulo de web scraping para recopilar información detallada de juegos desde Steam Store.

> ⚠️ **Este módulo está en reserva.** El scraper existe y funciona, pero la app principal
> usa la [Steam Web API](https://store.steampowered.com/api/appdetails) directamente.
> Este scraper se activará en una fase futura para enriquecer los datos con campos
> que la API no expone (descripción HTML, tags de usuario, Metacritic, etc.).

---

## ¿Qué hace?

Combina tres fuentes de datos por cada juego:

| Fuente | Técnica | Datos obtenidos |
|---|---|---|
| Steam Search | HTML scraping (BeautifulSoup) | Descubrimiento de App IDs |
| Steam App Details API | HTTP JSON | Precio, géneros, desarrollador, capturas |
| Steam Reviews API | HTTP JSON | Total reseñas, % positivo |
| Steam Store Page | HTML scraping (BeautifulSoup) | Tags, descripción, Metacritic, categorías |

---

## Instalación

Las dependencias ya están en `requirements.txt` del proyecto:
- `httpx` — cliente HTTP asíncrono
- `beautifulsoup4` — parser HTML

```powershell
# Desde la raíz del proyecto con el venv activo:
.\venv\Scripts\activate
```

---

## Uso

```powershell
# Top Sellers (por defecto, 150 juegos)
python -m scraping.steam_scraper

# Ofertas activas
python -m scraping.steam_scraper --mode specials --limit 100

# Mejor valorados
python -m scraping.steam_scraper --mode toprated --limit 200

# Lanzamientos recientes
python -m scraping.steam_scraper --mode newreleases --limit 50

# Con delay personalizado (más lento = más seguro contra rate limit)
python -m scraping.steam_scraper --mode topsellers --limit 150 --delay 2.5
```

---

## Modos disponibles

| Modo | Descripción |
|---|---|
| `topsellers` | Juegos más vendidos, ordenados por reseñas |
| `specials` | Juegos con descuento activo, ordenados por % de descuento |
| `toprated` | Juegos recomendados con mejor reputación |
| `newreleases` | Lanzamientos recientes y trending |

---

## Salida (JSON)

Los resultados se guardan en `scraping/output/steam_games_{mode}_{timestamp}.json`:

```json
{
  "meta": {
    "source": "Steam Store (Web Scraping + API)",
    "mode": "specials",
    "total_games": 148,
    "scraped_at": "2025-01-15T22:30:00Z"
  },
  "games": [
    {
      "steam_app_id": "1245620",
      "steam_url": "https://store.steampowered.com/app/1245620",
      "name": "Elden Ring",
      "developers": ["FromSoftware Inc."],
      "publishers": ["Bandai Namco Entertainment"],
      "genres": ["Action", "RPG"],
      "user_tags": ["Souls-like", "Open World", "Dark Fantasy", "..."],
      "categories": ["Single-player", "Steam Achievements", "..."],
      "release_date": "Feb 25, 2022",
      "platforms": ["Windows"],
      "is_free": false,
      "short_description": "A vast world where open fields...",
      "price": {
        "currency": "USD",
        "initial_usd": 59.99,
        "final_usd": 35.99,
        "discount_percent": 40
      },
      "reputation": {
        "total_reviews": 250000,
        "total_positive": 237500,
        "positive_percent": 95.0,
        "review_score_desc": "Overwhelmingly Positive"
      },
      "metacritic_score": 96,
      "images": {
        "header": "https://cdn.akamai.steamstatic.com/steam/apps/1245620/header.jpg",
        "capsule": "https://cdn.akamai.steamstatic.com/steam/apps/1245620/capsule_616x353.jpg",
        "library": "https://cdn.akamai.steamstatic.com/steam/apps/1245620/library_600x900.jpg"
      },
      "screenshots": ["https://..."],
      "scraped_at": "2025-01-15T22:30:15Z"
    }
  ]
}
```

---

## Uso futuro planeado

Cuando se active, este scraper alimentará la base de datos con:
- Descripciones enriquecidas para una página de detalle más completa
- Tags de usuario para filtros más precisos en el catálogo
- Puntuación de Metacritic como segunda métrica de reputación
- Capturas de pantalla para un carrusel en la página de juego
- Categorías (Single-player, Co-op, etc.) como filtros adicionales

---

## Notas importantes

- El scraper respeta los rate limits de Steam con delays configurables.
- Los archivos JSON generados están en `.gitignore` para evitar subir datos voluminosos.
- Steam puede bloquear IPs con muchas peticiones rápidas — usa `--delay 2.0` o más si hay problemas.
- Los juegos de tipo DLC, soundtrack o herramienta se omiten automáticamente.
