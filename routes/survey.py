import streamlit as st
import db

YES_NO = ["Sí", "No"]

PLACEHOLDER = "Seleccione..."

def _render_question(q, answers, ctx):
    qid = q["id"]
    qtype = q["qtype"]
    qtext = q["text"]
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

        val = st.selectbox(qtext, options=options, key=key, index=None, placeholder=PLACEHOLDER)
        answers[qid] = val
        if q.get("code"):
            ctx[q["code"]] = val
            st.session_state[f"code_{q['code']}"] = val
        return

    if qtype == "yes_no":
        val = st.radio(qtext, YES_NO, horizontal=True, key=key, index=None)
        answers[qid] = val
    elif qtype == "text":
        val = st.text_input(qtext, key=key)
        answers[qid] = val
    elif qtype == "number":
        # text_input para permitir vacío (no marcar por defecto)
        val = st.text_input(qtext, key=key, placeholder="(opcional)")
        answers[qid] = val
    elif qtype == "single_choice":
        options = [o["label"] for o in q.get("options", [])]
        val = (
            st.selectbox(qtext, options=options, key=key, index=None, placeholder=PLACEHOLDER)
            if options
            else st.text_input(qtext, key=key)
        )
        answers[qid] = val

        if config.get("has_other") and (val == config.get("other_label", "OTRA")):
            other = st.text_input(config.get("other_text_prompt", "¿Cuál?"), key=f"{key}_other")
            answers[qid] = f"{val}: {other}".strip()
    elif qtype == "multi_choice":
        options = [o["label"] for o in q.get("options", [])]
        val = st.multiselect(qtext, options=options, key=key)
        answers[qid] = val
    else:
        val = st.text_input(qtext, key=key)
        answers[qid] = val

    if q.get("code"):
        ctx[q["code"]] = answers[qid]
        st.session_state[f"code_{q['code']}"] = answers[qid]

    ctx[q.get("code") or key] = answers[qid]

def survey_page(version_id: int):
    st.title("Encuesta - Comunidad General")
    st.caption("Herramienta de seguimiento del PIC 2025")

    form = db.get_form(version_id)
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
        # Validar solo obligatorias (en tus bloques se forzó required=False desde main.py)
        missing = []
        for s in form:
            for grp in s.get("groups", []):
                for q in grp.get("questions", []):
                    if q.get("required"):
                        val = st.session_state.get(f"q_{q['id']}")
                        if val in (None, "", [], {}, " "):
                            missing.append(q["text"])
        if missing:
            st.error("Faltan preguntas obligatorias:\n- " + "\n- ".join(missing[:12]) + ("" if len(missing) <= 12 else "\n..."))
            return

        resp_id = db.create_response(version_id, metadata)
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
        st.success(f"¡Gracias! Encuesta guardada con ID #{resp_id}.")
        st.info("Puedes diligenciar otra encuesta desde el inicio.")
