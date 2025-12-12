\
import streamlit as st

def help_deploy_page():
    st.title("Ayuda (Deploy en Heroku desde cero)")
    st.markdown("""
### 1) Requisitos
- Git instalado
- Cuenta en Heroku
- Heroku CLI instalado

### 2) Crear repo y subir código
En tu carpeta del proyecto:

```bash
git init
git add .
git commit -m "init encuesta"
```

### 3) Crear app en Heroku y agregar Postgres
```bash
heroku login
heroku create NOMBRE-DE-TU-APP
heroku addons:create heroku-postgresql:mini
```

> El addon crea automáticamente la variable `DATABASE_URL`.

### 4) Variables de entorno recomendadas
Crea el admin inicial (si no hay usuarios en BD):

```bash
heroku config:set ADMIN_USER=admin
heroku config:set ADMIN_PASSWORD="TuClaveFuerte"
```

(El proyecto también funciona sin esto; por defecto crea `admin / Admin2025!` si la tabla users está vacía.)

### 5) Deploy
```bash
git branch -M main
git push heroku main
```

### 6) Abrir la app
```bash
heroku open
```

### 7) Ver logs (si algo falla)
```bash
heroku logs --tail
```

### Notas sobre la base de datos
- No tienes que “configurar” la BD a mano: Heroku define `DATABASE_URL`.
- La app crea tablas automáticamente al iniciar (si no existen) y carga el seed inicial de preguntas.
""")
