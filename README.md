# Encuesta PIC (Streamlit + Heroku + Postgres)

App de encuestas con:
- Encuesta pública (sin login)
- Módulo admin/editor: CRUD de preguntas, exportación a Excel, gestión de usuarios
- Base de datos Postgres (Heroku Postgres) con seed inicial desde `data/seed_questions.json`

## Correr local
1. Crear y activar venv
2. `pip install -r requirements.txt`
3. Crear `.env` (opcional) con `DATABASE_URL=postgresql://...`
4. `streamlit run main.py`

## Deploy en Heroku (resumen)
Ver la guía detallada dentro de la app en la página **Admin → Ayuda (Deploy)**.
