\
import os
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

import db
import auth
from routes.survey import survey_page
from routes.questions_admin import questions_admin_page
from routes.results import results_page
from routes.users import users_page
from routes.help_deploy import help_deploy_page

load_dotenv()

st.set_page_config(page_title="Encuesta PIC", layout="wide")

# --- DB init + seed ---
db.init_database()
auth.ensure_default_admin()
seed_path = str(Path(__file__).parent / "data" / "seed_questions.json")
version_id = db.ensure_seed(seed_path)

# --- Session init ---
if "user" not in st.session_state:
    st.session_state.user = None

# --- Sidebar ---
st.sidebar.title("Encuesta PIC")

page = st.sidebar.radio(
    "Menú",
    options=[
        "Encuesta (público)",
        "Admin: Gestión de preguntas",
        "Admin: Respuestas / Exportar",
        "Admin: Usuarios",
        "Admin: Ayuda (Deploy)",
    ],
)

# Login box always visible, but only affects admin pages
auth.login_box()
if st.session_state.user:
    st.sidebar.success(f"Sesión: {st.session_state.user['username']} ({st.session_state.user['role']})")
    auth.logout_button()

# --- Routing ---
if page == "Encuesta (público)":
    survey_page(version_id)
elif page == "Admin: Gestión de preguntas":
    if not auth.require_role(["admin","editor"]):
        st.error("Debes iniciar sesión como admin o editor.")
    else:
        questions_admin_page(version_id)
elif page == "Admin: Respuestas / Exportar":
    if not auth.require_role(["admin"]):
        st.error("Solo admin puede exportar respuestas.")
    else:
        results_page(version_id)
elif page == "Admin: Usuarios":
    if not auth.require_role(["admin"]):
        st.error("Solo admin puede gestionar usuarios.")
    else:
        users_page()
elif page == "Admin: Ayuda (Deploy)":
    help_deploy_page()
