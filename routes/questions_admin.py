\
import json
import streamlit as st
import db

Q_TYPES = [
    ("yes_no", "Sí/No"),
    ("text", "Texto"),
    ("number", "Número"),
    ("single_choice", "Selección única"),
    ("multi_choice", "Selección múltiple"),
]

def _safe_json(text):
    try:
        return json.loads(text) if text.strip() else {}
    except Exception as e:
        raise ValueError(str(e))

def questions_admin_page(version_id: int):
    st.title("Gestión de preguntas (CRUD)")

    form = db.get_form(version_id)
    sections = [(s["id"], s["name"]) for s in form]

    tab1, tab2, tab3 = st.tabs(["Secciones", "Grupos", "Preguntas"])

    with tab1:
        st.subheader("Secciones")
        for s in form:
            with st.expander(f"Editar: {s['name']}", expanded=False):
                name = st.text_input("Nombre", value=s["name"], key=f"sec_name_{s['id']}")
                order = st.number_input("Orden", min_value=1, value=int(s["sort_order"]), key=f"sec_ord_{s['id']}")
                active = st.checkbox("Activa", value=bool(s["is_active"]), key=f"sec_act_{s['id']}")
                if st.button("Guardar sección", key=f"sec_save_{s['id']}"):
                    db.upsert_section(version_id, s["id"], name, int(order), bool(active))
                    st.success("Guardado.")
                    st.rerun()

        st.markdown("---")
        st.subheader("Crear sección")
        name = st.text_input("Nombre nueva sección", key="sec_new_name")
        order = st.number_input("Orden nueva sección", min_value=1, value=1, key="sec_new_order")
        if st.button("Crear sección", type="primary"):
            if not name.strip():
                st.error("Nombre requerido.")
            else:
                db.upsert_section(version_id, None, name.strip(), int(order), True)
                st.success("Sección creada.")
                st.rerun()

    with tab2:
        st.subheader("Grupos (pregunta grande / actividad)")
        if not sections:
            st.warning("Crea una sección primero.")
        else:
            sec_id = st.selectbox("Sección", options=[s[0] for s in sections], format_func=lambda i: dict(sections)[i])
            # listar grupos de esa sección
            groups = []
            for s in form:
                if s["id"] == sec_id:
                    groups = s.get("groups", [])
            for g in groups:
                with st.expander(f"Editar grupo: {g['title']}", expanded=False):
                    title = st.text_area("Título", value=g["title"], key=f"grp_title_{g['id']}")
                    order = st.number_input("Orden", min_value=1, value=int(g["sort_order"]), key=f"grp_ord_{g['id']}")
                    active = st.checkbox("Activo", value=bool(g["is_active"]), key=f"grp_act_{g['id']}")
                    if st.button("Guardar grupo", key=f"grp_save_{g['id']}"):
                        db.upsert_group(version_id, g["id"], sec_id, title.strip(), int(order), bool(active))
                        st.success("Guardado.")
                        st.rerun()

            st.markdown("---")
            st.subheader("Crear grupo")
            title = st.text_area("Título nuevo grupo", key="grp_new_title")
            order = st.number_input("Orden nuevo grupo", min_value=1, value=1, key="grp_new_order")
            if st.button("Crear grupo", type="primary", key="grp_new_btn"):
                if not title.strip():
                    st.error("Título requerido.")
                else:
                    db.upsert_group(version_id, None, sec_id, title.strip(), int(order), True)
                    st.success("Grupo creado.")
                    st.rerun()

    with tab3:
        st.subheader("Preguntas")
        # seleccionar sección y grupo
        if not sections:
            st.warning("Crea una sección primero.")
            return
        sec_id = st.selectbox("Sección", options=[s[0] for s in sections], format_func=lambda i: dict(sections)[i], key="q_sec")
        groups = []
        for s in form:
            if s["id"] == sec_id:
                groups = s.get("groups", [])
        if not groups:
            st.warning("Crea un grupo primero.")
            return
        group_map = {g["id"]: g["title"] for g in groups}
        grp_id = st.selectbox("Grupo", options=list(group_map.keys()), format_func=lambda i: group_map[i], key="q_grp")

        # obtener preguntas del grupo
        qs = []
        for g in groups:
            if g["id"] == grp_id:
                qs = g.get("questions", [])

        for q in qs:
            with st.expander(f"Editar pregunta: {q['text'][:80]}", expanded=False):
                text = st.text_area("Texto", value=q["text"], key=f"q_text_{q['id']}")
                code = st.text_input("Code (opcional, único por versión)", value=q.get("code") or "", key=f"q_code_{q['id']}")
                qtype = st.selectbox("Tipo", options=[t[0] for t in Q_TYPES], format_func=lambda v: dict(Q_TYPES)[v], index=[t[0] for t in Q_TYPES].index(q["qtype"]), key=f"q_type_{q['id']}")
                required = st.checkbox("Obligatoria", value=bool(q["required"]), key=f"q_req_{q['id']}")
                order = st.number_input("Orden", min_value=1, value=int(q["sort_order"]), key=f"q_ord_{q['id']}")
                active = st.checkbox("Activa", value=bool(q["is_active"]), key=f"q_act_{q['id']}")

                config_txt = st.text_area("Config (JSON) - opcional", value=json.dumps(q.get("config") or {}, ensure_ascii=False, indent=2), height=120, key=f"q_cfg_{q['id']}")
                if st.button("Guardar pregunta", key=f"q_save_{q['id']}"):
                    try:
                        config = _safe_json(config_txt)
                        db.upsert_question(version_id, q["id"], grp_id, code.strip() or None, text.strip(), qtype, bool(required), int(order), bool(active), config)
                        st.success("Guardado.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Config JSON inválida: {e}")

                # Opciones
                if qtype in ("single_choice","multi_choice"):
                    st.markdown("**Opciones** (se reemplazan al guardar)")
                    # mostrar actuales
                    cur_opts = q.get("options", [])
                    opts_txt = "\n".join([o["label"] for o in cur_opts]) if cur_opts else ""
                    new_opts = st.text_area("Una opción por línea", value=opts_txt, height=150, key=f"q_opts_{q['id']}")
                    meta_note = st.info("Si necesitas meta (ej. municipios por provincia), edita el JSON en la BD o en el seed. Para el caso municipio, ya viene configurado.")
                    if st.button("Guardar opciones", key=f"q_opts_save_{q['id']}"):
                        db.delete_options_for_question(q["id"])
                        lines = [l.strip() for l in new_opts.splitlines() if l.strip()]
                        for idx, label in enumerate(lines, start=1):
                            db.insert_option(q["id"], label, label, idx, {})
                        st.success("Opciones guardadas.")
                        st.rerun()

        st.markdown("---")
        st.subheader("Crear pregunta")
        text = st.text_area("Texto nueva pregunta", key="q_new_text")
        code = st.text_input("Code (opcional)", key="q_new_code")
        qtype = st.selectbox("Tipo", options=[t[0] for t in Q_TYPES], format_func=lambda v: dict(Q_TYPES)[v], key="q_new_type")
        required = st.checkbox("Obligatoria", value=False, key="q_new_req")
        order = st.number_input("Orden", min_value=1, value=1, key="q_new_order")
        config_txt = st.text_area("Config JSON (opcional)", value="{}", height=90, key="q_new_cfg")

        if st.button("Crear pregunta", type="primary", key="q_new_btn"):
            if not text.strip():
                st.error("Texto requerido.")
                return
            try:
                config = _safe_json(config_txt)
                db.upsert_question(version_id, None, grp_id, code.strip() or None, text.strip(), qtype, bool(required), int(order), True, config)
                st.success("Pregunta creada.")
                st.rerun()
            except Exception as e:
                st.error(f"Config JSON inválida: {e}")
