# 🎮 GameDeal Insight

Plataforma de inteligencia de mercado para videojuegos que compara precios y reputación en tiempo real.

## 🚀 Requisitos
* Tener instalado **Docker** y **Docker Compose**.

## 🛠️ Instalación y Ejecución
1. Descarga y descomprime este proyecto.
2. Abre una terminal dentro de la carpeta.
3. Ejecuta el siguiente comando para levantar la base de datos y la app:
   ```bash
   docker-compose up --build
   ```
4. Una vez que veas que el servidor inició, abre tu navegador en:
   **http://localhost:8000/dashboard**

## 📊 Notas
El sistema incluye un **recolector automático** que descarga precios de Steam y analiza las reseñas de los usuarios para mostrarte qué ofertas valen realmente la pena.
