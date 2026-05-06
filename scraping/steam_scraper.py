#!/usr/bin/env python3
"""
scraping/steam_scraper.py
─────────────────────────
Web scraper para obtener información detallada de juegos desde Steam Store.

Fuentes de datos:
  1. Steam Search (HTML scraping con BeautifulSoup)
     → Descubre App IDs de top-sellers, ofertas y más votados
  2. Steam App Details API (JSON)
     → Metadatos completos: precio, desarrollador, género, descripción
  3. Steam Reviews API (JSON)
     → Conteo de reseñas positivas/negativas
  4. Página de tienda individual (HTML scraping)
     → Tags de usuario, descripción corta, capturas

Uso:
    # Desde la raíz del proyecto (con venv activo):
    python -m scraping.steam_scraper
    python -m scraping.steam_scraper --mode specials --limit 100
    python -m scraping.steam_scraper --mode topsellers --limit 200

Salida:
    scraping/output/steam_games_YYYYMMDD_HHMMSS.json

Notas:
  - Respeta los rate limits de Steam (1-2 segundos entre peticiones)
  - Maneja páginas de verificación de edad automáticamente
  - Los juegos fallidos se omiten sin detener el proceso
"""

import argparse
import asyncio
import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

import httpx
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────────────────────
# Configuración
# ──────────────────────────────────────────────────────────────

OUTPUT_DIR = Path(__file__).parent / "output"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/json,*/*;q=0.8",
}

# Cookies para saltarse la verificación de edad y contenido maduro
AGE_BYPASS_COOKIES = {
    "birthtime": "0",
    "mature_content": "1",
    "lastagecheckage": "1-0-1990",
}

STEAM_SEARCH_URL   = "https://store.steampowered.com/search/results/"
STEAM_API_DETAILS  = "https://store.steampowered.com/api/appdetails"
STEAM_API_REVIEWS  = "https://store.steampowered.com/appreviews/{app_id}"
STEAM_STORE_PAGE   = "https://store.steampowered.com/app/{app_id}"
STEAM_CDN_HEADER   = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/header.jpg"
STEAM_CDN_CAPSULE  = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/capsule_616x353.jpg"
STEAM_CDN_LIBRARY  = "https://cdn.akamai.steamstatic.com/steam/apps/{app_id}/library_600x900.jpg"
STEAM_APP_URL      = "https://store.steampowered.com/app/{app_id}"

SEARCH_MODES = {
    "topsellers": {"sort_by": "Reviews_DESC", "filter": "topsellers"},
    "specials":   {"sort_by": "Discount_DESC", "specials": "1"},
    "toprated":   {"sort_by": "Reviews_DESC", "filter": "recommended"},
    "newreleases":{"sort_by": "Released_DESC", "filter": "new_and_trending"},
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("steam_scraper")


# ──────────────────────────────────────────────────────────────
# Descubrimiento de App IDs (HTML scraping)
# ──────────────────────────────────────────────────────────────

def discover_app_ids(mode: str = "topsellers", limit: int = 150) -> list[str]:
    """
    Scrape Steam Search para obtener una lista de App IDs.

    Steam devuelve bloques de HTML con los resultados. Cada tarjeta
    de juego tiene el atributo `data-ds-appid` con el App ID.
    """
    logger.info(f"Descubriendo App IDs — modo: {mode}, límite: {limit}")

    params = {
        "os": "win",
        "count": 50,
        "start": 0,
        "infinite": 1,
        "force_infinite": 1,
        **SEARCH_MODES.get(mode, SEARCH_MODES["topsellers"]),
    }

    app_ids: list[str] = []
    page = 0

    with httpx.Client(headers=HEADERS, cookies=AGE_BYPASS_COOKIES, timeout=20, follow_redirects=True) as client:
        while len(app_ids) < limit:
            params["start"] = page * 50
            try:
                res = client.get(STEAM_SEARCH_URL, params=params)
                res.raise_for_status()

                # Steam puede devolver JSON con campo "results_html" o HTML directo
                content_type = res.headers.get("content-type", "")
                if "json" in content_type:
                    data = res.json()
                    html = data.get("results_html", "")
                    remaining = data.get("total_count", 0) - params["start"]
                else:
                    html = res.text
                    remaining = 50  # asumir que hay más

                soup = BeautifulSoup(html, "html.parser")
                rows = soup.select("a[data-ds-appid]")

                if not rows:
                    logger.info("Sin más resultados en búsqueda.")
                    break

                for row in rows:
                    raw_ids = row.get("data-ds-appid", "")
                    # Algunos resultados son bundles con múltiples IDs separados por coma
                    for aid in raw_ids.split(","):
                        aid = aid.strip()
                        if aid and aid not in app_ids:
                            app_ids.append(aid)
                            if len(app_ids) >= limit:
                                break
                    if len(app_ids) >= limit:
                        break

                logger.info(f"  Página {page + 1}: {len(rows)} resultados → {len(app_ids)} acumulados")

                if remaining <= 0:
                    break

                page += 1
                time.sleep(1.2)  # rate limiting

            except Exception as e:
                logger.error(f"Error en página {page}: {e}")
                break

    logger.info(f"Total App IDs descubiertos: {len(app_ids)}")
    return app_ids[:limit]


# ──────────────────────────────────────────────────────────────
# Obtención de detalles via API (JSON)
# ──────────────────────────────────────────────────────────────

def fetch_api_details(client: httpx.Client, app_id: str) -> dict | None:
    """Llama a la API oficial de Steam para metadatos y precio."""
    try:
        res = client.get(
            STEAM_API_DETAILS,
            params={"appids": app_id, "cc": "us", "l": "english"},
        )
        res.raise_for_status()
        payload = res.json()

        if not payload.get(app_id, {}).get("success"):
            return None

        return payload[app_id]["data"]
    except Exception as e:
        logger.warning(f"  API details error [{app_id}]: {e}")
        return None


def fetch_reviews(client: httpx.Client, app_id: str) -> dict:
    """Obtiene el resumen de reseñas de Steam."""
    try:
        res = client.get(
            STEAM_API_REVIEWS.format(app_id=app_id),
            params={"json": 1, "language": "all", "filter": "summary", "purchase_type": "all"},
        )
        res.raise_for_status()
        return res.json().get("query_summary", {})
    except Exception:
        return {}


# ──────────────────────────────────────────────────────────────
# Scraping HTML de la página de tienda individual
# ──────────────────────────────────────────────────────────────

def scrape_store_page(client: httpx.Client, app_id: str) -> dict:
    """
    Hace scraping de la página de tienda de un juego específico.
    Extrae: descripción corta, tags de usuario, puntuación de reseñas en texto,
    número de capturas de pantalla, plataformas soportadas.
    """
    result = {
        "short_description": None,
        "user_tags": [],
        "review_summary_text": None,
        "screenshot_count": 0,
        "supported_platforms": [],
        "metacritic_score": None,
        "categories": [],
    }

    try:
        res = client.get(
            STEAM_STORE_PAGE.format(app_id=app_id),
            cookies={**AGE_BYPASS_COOKIES, "wants_mature_content": "1"},
        )
        res.raise_for_status()
        soup = BeautifulSoup(res.text, "html.parser")

        # Descripción corta
        desc_el = soup.select_one(".game_description_snippet")
        if desc_el:
            result["short_description"] = desc_el.get_text(strip=True)

        # Tags de usuario (géneros personalizados)
        tags = soup.select("a.app_tag")
        result["user_tags"] = [t.get_text(strip=True) for t in tags[:10]]

        # Texto del resumen de reseñas (ej. "Very Positive", "Overwhelmingly Positive")
        review_el = soup.select_one(".game_review_summary:not(.not_enough_reviews)")
        if review_el:
            result["review_summary_text"] = review_el.get_text(strip=True)

        # Capturas de pantalla
        screenshots = soup.select(".highlight_screenshot_link, .screenshot_holder a")
        result["screenshot_count"] = len(screenshots)

        # Plataformas (Windows/Mac/Linux)
        platforms = []
        if soup.select_one(".platform_img.win"):
            platforms.append("Windows")
        if soup.select_one(".platform_img.mac"):
            platforms.append("Mac")
        if soup.select_one(".platform_img.linux"):
            platforms.append("Linux")
        result["supported_platforms"] = platforms

        # Puntuación Metacritic (si aparece en la página)
        meta_el = soup.select_one(".metacritic_score .score")
        if meta_el:
            try:
                result["metacritic_score"] = int(meta_el.get_text(strip=True))
            except ValueError:
                pass

        # Categorías (Single-player, Multi-player, co-op, etc.)
        cat_els = soup.select("#category_block .game_area_details_specs_ctn .label")
        result["categories"] = [c.get_text(strip=True) for c in cat_els[:8]]

    except Exception as e:
        logger.debug(f"  Store page scrape error [{app_id}]: {e}")

    return result


# ──────────────────────────────────────────────────────────────
# Construcción del registro completo de un juego
# ──────────────────────────────────────────────────────────────

def build_game_record(app_id: str, api_data: dict, reviews: dict, store_data: dict) -> dict:
    """Combina todos los datos en un dict estructurado listo para guardar en JSON."""

    pricing = api_data.get("price_overview") or {}
    release = (api_data.get("release_date") or {}).get("date")
    genres  = [g.get("description") for g in api_data.get("genres", [])]
    devs    = api_data.get("developers") or []
    pubs    = api_data.get("publishers") or []

    total_reviews  = reviews.get("total_reviews", 0)
    total_positive = reviews.get("total_positive", 0)
    review_score   = round(total_positive / total_reviews * 100, 1) if total_reviews > 0 else None

    return {
        # ── Identificación ──────────────────────────────────────
        "steam_app_id":     app_id,
        "steam_url":        STEAM_APP_URL.format(app_id=app_id),

        # ── Metadatos ───────────────────────────────────────────
        "name":             api_data.get("name"),
        "type":             api_data.get("type"),         # "game", "dlc", "demo"...
        "developers":       devs,
        "publishers":       pubs,
        "genres":           genres,
        "user_tags":        store_data.get("user_tags", []),
        "categories":       store_data.get("categories", []),
        "release_date":     release,
        "platforms":        store_data.get("supported_platforms", []),
        "is_free":          api_data.get("is_free", False),

        # ── Descripción ─────────────────────────────────────────
        "short_description":    (
            store_data.get("short_description")
            or api_data.get("short_description")
        ),
        "detailed_description": _strip_html(api_data.get("detailed_description", "")),

        # ── Precio ──────────────────────────────────────────────
        "price": {
            "currency":          pricing.get("currency", "USD"),
            "initial_usd":       round(pricing.get("initial", 0) / 100, 2),
            "final_usd":         round(pricing.get("final", 0) / 100, 2),
            "discount_percent":  pricing.get("discount_percent", 0),
            "initial_formatted": pricing.get("initial_formatted", ""),
            "final_formatted":   pricing.get("final_formatted", ""),
        } if pricing else None,

        # ── Reputación ──────────────────────────────────────────
        "reputation": {
            "total_reviews":        total_reviews,
            "total_positive":       total_positive,
            "total_negative":       reviews.get("total_negative", 0),
            "positive_percent":     review_score,
            "review_score_desc":    reviews.get("review_score_desc"),
            "summary_text":         store_data.get("review_summary_text"),
        },

        # ── Metacritic ──────────────────────────────────────────
        "metacritic_score": (
            store_data.get("metacritic_score")
            or (api_data.get("metacritic") or {}).get("score")
        ),

        # ── Imágenes ────────────────────────────────────────────
        "images": {
            "header":   STEAM_CDN_HEADER.format(app_id=app_id),
            "capsule":  STEAM_CDN_CAPSULE.format(app_id=app_id),
            "library":  STEAM_CDN_LIBRARY.format(app_id=app_id),
            "background": api_data.get("background"),
        },

        # ── Capturas ────────────────────────────────────────────
        "screenshots": [
            s.get("path_full")
            for s in api_data.get("screenshots", [])[:6]
        ],

        # ── Extras ──────────────────────────────────────────────
        "screenshot_count":       store_data.get("screenshot_count", 0),
        "required_age":           api_data.get("required_age", 0),
        "content_descriptors":    api_data.get("content_descriptors", {}).get("notes"),

        # ── Timestamp ───────────────────────────────────────────
        "scraped_at": datetime.utcnow().isoformat() + "Z",
    }


def _strip_html(html: str) -> str:
    """Elimina etiquetas HTML y limpia espacios."""
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text(separator=" ", strip=True)
    return re.sub(r"\s{2,}", " ", text)[:2000]  # máx 2000 chars


# ──────────────────────────────────────────────────────────────
# Pipeline principal
# ──────────────────────────────────────────────────────────────

def run_scraper(mode: str = "topsellers", limit: int = 150, delay: float = 1.5) -> list[dict]:
    """
    Pipeline completo:
      1. Descubrir App IDs haciendo scraping del buscador de Steam
      2. Para cada App ID: obtener detalles API + reseñas API + scraping de tienda
      3. Construir el registro completo
      4. Devolver lista de dicts

    Args:
        mode:  Modo de búsqueda ("topsellers", "specials", "toprated", "newreleases")
        limit: Número máximo de juegos a procesar
        delay: Segundos de espera entre peticiones (respetar rate limit)
    """

    # 1. Descubrir App IDs
    app_ids = discover_app_ids(mode=mode, limit=limit)

    if not app_ids:
        logger.error("No se encontraron App IDs. Verifica conectividad o intenta más tarde.")
        return []

    games: list[dict] = []
    failed: list[str] = []

    logger.info(f"\nProcesando {len(app_ids)} juegos...")

    with httpx.Client(
        headers=HEADERS,
        cookies=AGE_BYPASS_COOKIES,
        timeout=httpx.Timeout(25.0),
        follow_redirects=True,
    ) as client:

        for i, app_id in enumerate(app_ids, start=1):
            logger.info(f"[{i:>3}/{len(app_ids)}] App ID: {app_id}")

            # 2a. Detalles de API
            api_data = fetch_api_details(client, app_id)
            if not api_data:
                logger.warning(f"  ✗ Saltando {app_id} (sin datos de API)")
                failed.append(app_id)
                time.sleep(delay * 0.5)
                continue

            # Solo juegos (no DLCs, soundtracks, etc.) — comentar si se quieren incluir
            if api_data.get("type") not in ("game", "demo"):
                logger.info(f"  ↷ Omitido — tipo: {api_data.get('type')}")
                time.sleep(delay * 0.3)
                continue

            # 2b. Reseñas
            time.sleep(delay * 0.4)
            reviews = fetch_reviews(client, app_id)

            # 2c. Scraping de tienda
            time.sleep(delay * 0.6)
            store_data = scrape_store_page(client, app_id)

            # 3. Construir registro
            record = build_game_record(app_id, api_data, reviews, store_data)
            games.append(record)
            logger.info(f"  ✓ {record['name']} | {record['price']['final_usd'] if record['price'] else 'Free'} USD | {record['reputation']['positive_percent']}% positivo")

            time.sleep(delay)

    logger.info(f"\nResumen: {len(games)} juegos recopilados, {len(failed)} fallidos")
    if failed:
        logger.info(f"App IDs fallidos: {failed}")

    return games


# ──────────────────────────────────────────────────────────────
# Guardar JSON
# ──────────────────────────────────────────────────────────────

def save_json(games: list[dict], mode: str) -> Path:
    """Guarda la lista de juegos en un archivo JSON con formato legible."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = OUTPUT_DIR / f"steam_games_{mode}_{timestamp}.json"

    output = {
        "meta": {
            "source":      "Steam Store (Web Scraping + API)",
            "mode":        mode,
            "total_games": len(games),
            "scraped_at":  datetime.utcnow().isoformat() + "Z",
            "fields": [
                "steam_app_id", "name", "developers", "publishers",
                "genres", "user_tags", "categories", "release_date",
                "platforms", "is_free", "short_description",
                "price", "reputation", "metacritic_score",
                "images", "screenshots",
            ],
        },
        "games": games,
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logger.info(f"\n✅ JSON guardado en: {filename}")
    logger.info(f"   Tamaño: {filename.stat().st_size / 1024:.1f} KB")

    return filename


# ──────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Web scraper de juegos de Steam → JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python -m scraping.steam_scraper
  python -m scraping.steam_scraper --mode specials --limit 100
  python -m scraping.steam_scraper --mode toprated --limit 200 --delay 2.0
  python -m scraping.steam_scraper --mode newreleases --limit 50
        """,
    )
    parser.add_argument(
        "--mode",
        choices=list(SEARCH_MODES.keys()),
        default="topsellers",
        help="Tipo de búsqueda en Steam (default: topsellers)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=150,
        help="Número máximo de juegos a recopilar (default: 150)",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.5,
        help="Segundos de espera entre peticiones (default: 1.5)",
    )

    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info(" GameDeal Insight — Steam Scraper")
    logger.info(f" Modo: {args.mode} | Límite: {args.limit} | Delay: {args.delay}s")
    logger.info("=" * 60)

    games = run_scraper(mode=args.mode, limit=args.limit, delay=args.delay)

    if games:
        output_file = save_json(games, args.mode)
        logger.info(f"\nEjecución completada. {len(games)} juegos en {output_file.name}")
    else:
        logger.error("No se recopilaron juegos. Revisa los logs de error.")


if __name__ == "__main__":
    main()
