import os
import streamlit as st
import db

YES_NO = ["Sí", "No"]

PLACEHOLDER = "Seleccione..."

from pathlib import Path
import json
import unicodedata
import re

@st.cache_data(show_spinner=False)
def _load_muni_program_map():
    """Carga el mapeo Municipio -> Secciones habilitadas."""
    p = Path(__file__).resolve().parent.parent / "data" / "municipio_programas.json"
    if not p.exists():
        return {}
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("municipality_to_sections", {})

def _norm_key(s: str | None) -> str:
    if not s:
        return ""
    s = str(s).strip().upper()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s)
    return s



def _yes_no_toggle(label: str, key: str, help_text: str | None = None):
    """Selector Sí/No sin valor por defecto.
    Nota: usamos 3 opciones (Sin respuesta/Sí/No) para que el usuario pueda limpiar
    sin necesidad de 'doble clic' y con feedback inmediato en pantalla.
    """
    # Guardamos el valor real en `key` como: None | "Sí" | "No"
    current = st.session_state.get(key)
    opts = ["Sin respuesta", "Sí", "No"]
    if current == "Sí":
        idx = 1
    elif current == "No":
        idx = 2
    else:
        idx = 0

    sel = st.radio(label, opts, index=idx, horizontal=True, key=f"{key}__yn", help=help_text)
    val = None if sel == "Sin respuesta" else sel
    st.session_state[key] = val
    return val

def _clear_button(key: str, label: str = "Limpiar"):
    if st.button(label, key=f"{key}__clear"):
        st.session_state[key] = None
        st.rerun()

def _render_question(q, answers, ctx):
    qid = q["id"]
    qtype = q["qtype"]
    qtext = (q.get("label") or q["text"]).strip()
    qhelp = (q.get("help_text") or "").strip() or None
    key = f"q_{qid}"

    config = q.get("config") or {}

    # dependency filter example: municipality depends on province
    if config.get("depends_on"):
        dep_code = config["depends_on"]
        dep_answer = st.session_state.get(f"code_{dep_code}")
        if dep_answer is None:
            dep_answer = ctx.get(dep_code)
        if dep_answer is None:
            st.info("Seleccione primero la provincia para ver los municipios.")
            return

        meta_key = config.get("filter_option_meta_key")
        filtered = []
        for opt in q.get("options", []):
            meta = opt.get("meta") or {}
            if meta.get(meta_key) == dep_answer:
                filtered.append(opt)

        options = [o["label"] for o in filtered]
        if not options:
            st.warning("No hay municipios configurados para esa provincia.")
            return

        # Si había un valor anterior que ya no aplica, lo limpiamos
        prev = st.session_state.get(key)
        if prev is not None and prev not in options:
            st.session_state[key] = None

        val = st.selectbox(qtext, options=options, key=key, index=None, placeholder=PLACEHOLDER, help=qhelp)
        answers[qid] = val
        _clear_button(key, "Quitar selección")
        if q.get("code"):
            ctx[q["code"]] = val
            st.session_state[f"code_{q['code']}"] = val
        return

    if qtype == "yes_no":
        val = _yes_no_toggle(qtext, key, qhelp)
        answers[qid] = val
    elif qtype == "text":
        val = st.text_input(qtext, key=key, help=qhelp)
        answers[qid] = val
    elif qtype == "number":
        # text_input para permitir vacío (no marcar por defecto)
        val = st.text_input(qtext, key=key, placeholder="(opcional)", help=qhelp)
        answers[qid] = val
    elif qtype == "single_choice":
        options = [o["label"] for o in q.get("options", [])]
        val = (
            st.selectbox(qtext, options=options, key=key, index=None, placeholder=PLACEHOLDER, help=qhelp)
            if options
            else st.text_input(qtext, key=key, help=qhelp)
        )
        answers[qid] = val
        if qtype == "single_choice" and (q.get("options") or []):
            _clear_button(key, "Quitar selección")

        if config.get("has_other") and (val == config.get("other_label", "OTRA")):
            other = st.text_input(config.get("other_text_prompt", "¿Cuál?"), key=f"{key}_other")
            answers[qid] = f"{val}: {other}".strip()
    elif qtype == "multi_choice":
        options = [o["label"] for o in q.get("options", [])]
        val = st.multiselect(qtext, options=options, key=key, help=qhelp)
        answers[qid] = val
        if val:
            _clear_button(key, "Quitar selección")
    else:
        val = st.text_input(qtext, key=key, help=qhelp)
        answers[qid] = val

    if q.get("code"):
        ctx[q["code"]] = answers[qid]
        st.session_state[f"code_{q['code']}"] = answers[qid]

    ctx[q.get("code") or key] = answers[qid]

@st.cache_data(ttl=60)
def _get_form_cached(version_id: int):
    return db.get_form(version_id)

def survey_page(version_id: int):
    st.title("Encuesta - Comunidad General")
    st.caption("Herramienta de seguimiento del PIC 2025")

    # Mensaje post-envío (redirige al inicio automáticamente)
    if st.session_state.get("_just_submitted"):
        resp_id = st.session_state.get("_last_response_id")
        if resp_id:
            st.success(f"¡Gracias! Encuesta guardada con ID #{resp_id}.")
        st.info("Puedes diligenciar otra encuesta desde el inicio.")
        st.session_state.pop("_just_submitted", None)


    form = _get_form_cached(version_id)

    # Filtrar secciones según el municipio (para reducir páginas según programas contratados)
    muni_map = _load_muni_program_map()
    muni = st.session_state.get("code_municipality")
    muni_norm = _norm_key(muni)

    prev_norm = st.session_state.get("_muni_norm_prev")
    if muni_norm and muni_norm != prev_norm:
        st.session_state["_muni_norm_prev"] = muni_norm
        # si el usuario cambió municipio, volvemos al inicio del wizard
        st.session_state.survey_section_idx = 0

    if muni_norm and muni_map:
        allowed_sections = muni_map.get(muni_norm) or []
        # Siempre mostramos PREGUNTAS INICIALES. Si no hay mapeo conocido, mostramos todo.
        if allowed_sections:
            initial = form[:1]
            rest = [s for s in form[1:] if s.get("name") in allowed_sections]
            form = initial + rest


    # Inferir campos iniciales aunque haya preguntas duplicadas sin "code"
    def _norm(x: str) -> str:
        import re, unicodedata
        x = (x or "").lower().strip()
        x = unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode("ascii")
        x = re.sub(r"[^a-z0-9]+", "", x)
        return x

    def _infer_initial_fields(_form):
        out = {}
        for sec in _form:
            if "preguntas iniciales" not in (sec.get("name","").lower()):
                continue
            for grp in sec.get("groups", []):
                gname_n = _norm(grp.get("title",""))
                for q in grp.get("questions", []):
                    qtext_n = _norm(q.get("label") or q.get("text") or "")
                    val = st.session_state.get(f"q_{q['id']}")
                    if val in (None, ""):
                        continue
                    if "ubic" in gname_n:
                        if "provinc" in qtext_n:
                            out.setdefault("province", val)
                        if "municip" in qtext_n:
                            out.setdefault("municipality", val)
                    if "ident" in gname_n:
                        if "nombre" in qtext_n:
                            out.setdefault("full_name", val)
                        if "tipodedocument" in qtext_n or ("tipo" in qtext_n and "document" in qtext_n):
                            out.setdefault("doc_type", val)
                        if "numerodedocument" in qtext_n or ("numero" in qtext_n and "document" in qtext_n):
                            out.setdefault("doc_number", val)
                        if "celular" in qtext_n or "telefono" in qtext_n:
                            out.setdefault("phone", val)
                        if "correo" in qtext_n or "email" in qtext_n:
                            out.setdefault("email", val)
                        if "cargo" in qtext_n or "rol" in qtext_n:
                            out.setdefault("role", val)
        return out

    inferred = _infer_initial_fields(form)
    for k, v in inferred.items():
        ss_key = f"code_{k}"
        if st.session_state.get(ss_key) in (None, "") and v not in (None, ""):
            st.session_state[ss_key] = v

    if not form:
        st.warning("No hay preguntas configuradas.")
        return

    # Wizard por secciones
    if "survey_section_idx" not in st.session_state:
        st.session_state.survey_section_idx = 0

    idx = int(st.session_state.survey_section_idx)
    idx = max(0, min(idx, len(form) - 1))
    st.session_state.survey_section_idx = idx

    # Metadata (persistente)
    with st.expander("Información adicional (opcional)"):
        encuestador = st.text_input("Nombre del encuestador(a) (opcional)", key="meta_encuestador")
        observaciones = st.text_area("Observaciones (opcional)", key="meta_observaciones")
    metadata = {
        "encuestador": st.session_state.get("meta_encuestador", ""),
        "observaciones": st.session_state.get("meta_observaciones", ""),
        # Campos clave (se guardan también en metadata para exportación robusta)
        "province": st.session_state.get("code_province"),
        "municipality": st.session_state.get("code_municipality"),
        "full_name": st.session_state.get("code_full_name"),
        "doc_type": st.session_state.get("code_doc_type"),
        "doc_number": st.session_state.get("code_doc_number"),
        "phone": st.session_state.get("code_phone"),
        "email": st.session_state.get("code_email"),
        "role": st.session_state.get("code_role"),
    }

    st.progress((idx + 1) / max(1, len(form)))
    st.caption(f"Sección {idx + 1} de {len(form)}")
    st.divider()

    answers = {}
    ctx = {}

    sec = form[idx]
    st.header(sec["name"])
    for grp in sec.get("groups", []):
        st.subheader(grp["title"])
        for q in grp.get("questions", []):
            _render_question(q, answers, ctx)
        st.markdown("---")

    col1, col2, col3 = st.columns([1, 1, 2])
    with col1:
        prev_clicked = st.button("Anterior", disabled=(idx == 0))
    with col2:
        if idx < len(form) - 1:
            next_clicked = st.button("Siguiente", type="primary")
        else:
            next_clicked = False
    with col3:
        submit_clicked = st.button("Enviar encuesta", type="primary") if idx == len(form) - 1 else False

    if prev_clicked:
        st.session_state.survey_section_idx = max(0, idx - 1)
        st.rerun()

    if next_clicked:
        st.session_state.survey_section_idx = min(len(form) - 1, idx + 1)
        st.rerun()

    if submit_clicked:
        resp_id = db.create_response(version_id, metadata)

        # Guardar todas las respuestas (incluye vacías como NULL, no se bloquea)
        for s in form:
            for grp in s.get("groups", []):
                for q in grp.get("questions", []):
                    val = st.session_state.get(f"q_{q['id']}")
                    db.save_answer(resp_id, q, val)

# Limpieza para nueva encuesta
        for s in form:
            for grp in s.get("groups", []):
                for q in grp.get("questions", []):
                    st.session_state.pop(f"q_{q['id']}", None)
                    if q.get("code"):
                        st.session_state.pop(f"code_{q['code']}", None)

        st.session_state.survey_section_idx = 0
        st.session_state["_last_response_id"] = resp_id
        st.session_state["_just_submitted"] = True
        # Limpia metadata opcional
        st.session_state.pop("meta_encuestador", None)
        st.session_state.pop("meta_observaciones", None)
        st.rerun()