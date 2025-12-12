\
import streamlit as st
import db
import auth

def users_page():
    st.title("Usuarios")
    users = db.list_users()

    st.subheader("Crear usuario")
    username = st.text_input("Usuario", key="new_user")
    password = st.text_input("Contraseña", type="password", key="new_pass")
    role = st.selectbox("Rol", options=["editor","admin"], index=0, key="new_role")
    if st.button("Crear usuario", type="primary"):
        if not username.strip() or not password:
            st.error("Usuario y contraseña requeridos.")
        else:
            if db.get_user_by_username(username):
                st.error("Ese usuario ya existe.")
            else:
                db.insert_user(username.strip(), auth.hash_password(password), role)
                st.success("Usuario creado.")
                st.rerun()

    st.markdown("---")
    st.subheader("Listado")
    for u in users:
        with st.expander(f"{u['username']} ({u['role']})", expanded=False):
            role2 = st.selectbox("Rol", options=["editor","admin"], index=["editor","admin"].index(u["role"]), key=f"role_{u['id']}")
            active = st.checkbox("Activo", value=bool(u["is_active"]), key=f"active_{u['id']}")
            col1,col2 = st.columns(2)
            with col1:
                if st.button("Guardar cambios", key=f"save_{u['id']}"):
                    db.update_user_role(int(u["id"]), role2, bool(active))
                    st.success("Actualizado.")
                    st.rerun()
            with col2:
                if st.button("Eliminar usuario", key=f"del_{u['id']}"):
                    db.delete_user(int(u["id"]))
                    st.success("Eliminado.")
                    st.rerun()
