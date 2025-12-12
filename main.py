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

st.set_page_config(
    page_title="Encuesta PIC",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Pastel blue feel (extra CSS on top of theme) ---
st.markdown(
    """
    <style>
      .stApp { background-color: #f2f7ff; }
      [data-testid="stSidebar"] > div:first-child { background-color: #e6f0ff; }
      .stButton>button { border-radius: 10px; }
      .stDownloadButton>button { border-radius: 10px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# --- DB init + seed ---
db.init_database()
auth.ensure_default_admin()
seed_path = str(Path(__file__).parent / "data" / "seed_questions.json")
version_id = db.ensure_seed(seed_path)

# Asegura campos de identificación (para BD ya sembradas)
db.ensure_initial_identity_questions(version_id)

# Regla PIC: todos estos bloques (todo menos "PREGUNTAS INICIALES") NO deben ser obligatorios.
db.set_required_for_sections(
    version_id,
    [
        "ENFERMEDADES NO TRANSMISIBLES",
        "SEGURIDAD ALIMENTARIA",
        "ENFERMEDADES TRANSMISIBLES",
        "ENFERMEDADES TRANSMITIDAS POR VECTORES – ETV",
        "SALUD MENTAL Y SUSTANCIAS PSICOACTIVAS",
        "SALUD INFANTIL",
        "SALUD SEXUAL Y REPRODUCTIVA",
        "SALUD LABORAL",
        "SALUD AMBIENTAL Y ZOONOSIS",
    ],
    required=False,
)

# --- Session init ---
if "user" not in st.session_state:
    st.session_state.user = None

# --- Sidebar (hidden by default, admin can open) ---
st.sidebar.title("Encuesta PIC")

# Login box in sidebar
auth.login_box(in_sidebar=True)
if st.session_state.user:
    st.sidebar.success(f"Sesión: {st.session_state.user['username']} ({st.session_state.user['role']})")
    auth.logout_button(in_sidebar=True)

menu_options = ["Encuesta (público)"]
if st.session_state.user:
    menu_options += [
        "Admin: Gestión de preguntas",
        "Admin: Respuestas / Exportar",
        "Admin: Usuarios",
        "Admin: Ayuda (Deploy)",
    ]

page = st.sidebar.radio("Menú", options=menu_options)

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
