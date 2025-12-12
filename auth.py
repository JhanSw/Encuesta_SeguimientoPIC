\
import os
import bcrypt
import streamlit as st
import db

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def check_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except Exception:
        return False

def ensure_default_admin():
    """
    Crea admin inicial si no existe ningún usuario.
    Usa env vars si están definidas:
      ADMIN_USER / ADMIN_PASSWORD
    """
    users = db.fetchall("SELECT 1 AS ok FROM users LIMIT 1;")
    if users:
        return
    username = os.getenv("ADMIN_USER", "admin")
    password = os.getenv("ADMIN_PASSWORD", "Admin2025!")
    db.insert_user(username, hash_password(password), "admin")

def login_box():
    with st.expander("Ingreso administrador / editor", expanded=False):
        username = st.text_input("Usuario", key="login_username")
        password = st.text_input("Contraseña", type="password", key="login_password")
        if st.button("Ingresar", type="primary"):
            user = db.get_user_by_username(username)
            if not user or not user.get("is_active"):
                st.error("Usuario no encontrado o inactivo.")
                return
            if not check_password(password, user["password_hash"]):
                st.error("Contraseña incorrecta.")
                return
            st.session_state.user = {"id": user["id"], "username": user["username"], "role": user["role"]}
            st.success(f"Bienvenido(a), {user['username']} ({user['role']})")

def logout_button():
    if st.button("Cerrar sesión"):
        st.session_state.user = None
        st.rerun()

def require_login():
    return bool(st.session_state.get("user"))

def require_role(roles):
    user = st.session_state.get("user")
    if not user:
        return False
    return user.get("role") in set(roles)
