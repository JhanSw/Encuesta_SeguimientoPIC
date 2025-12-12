import streamlit as st
import db

YES_NO = ["Sí", "No"]

def _render_question(q, answers, ctx):
    qid = q["id"]
    qtype = q["qtype"]
    qtext = q["text"]
    key = f"q_{qid}"

    config = q.get("config") or {}

    # dependency filter example: municipality depends on province
    if config.get("depends_on"):
        dep_code = config["depends_on"]
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

        val = st.selectbox(qtext, options=options, key=key)
        answers[qid] = val
        ctx[q.get("code") or key] = val
        return

    if qtype == "yes_no":
        val = st.radio(qtext, YES_NO, horizontal=True, key=key)
        answers[qid] = val
    elif qtype == "text":
        val = st.text_input(qtext, key=key)
        answers[qid] = val
    elif qtype == "number":
        val = st.number_input(qtext, key=key)
        answers[qid] = val
    elif qtype == "single_choice":
        options = [o["label"] for o in q.get("options", [])]
        val = st.selectbox(qtext, options=options, key=key) if options else st.text_input(qtext, key=key)
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

    ctx[q.get("code") or key] = answers[qid]

def survey_page(version_id: int):
    st.title("Encuesta - Comunidad General")
    st.caption("Herramienta de seguimiento del PIC 2025")

    form = db.get_form(version_id)

    answers = {}
    ctx = {}

    with st.expander("Información adicional (opcional)"):
        encuestador = st.text_input("Nombre del encuestador(a) (opcional)")
        observaciones = st.text_area("Observaciones (opcional)")
        metadata = {"encuestador": encuestador, "observaciones": observaciones}
    st.divider()

    # Render dinámico (SIN st.form) para permitir dependencias en vivo (Provincia -> Municipio)
    for sec in form:
        st.header(sec["name"])
        for grp in sec.get("groups", []):
            st.subheader(grp["title"])
            for q in grp.get("questions", []):
                _render_question(q, answers, ctx)
            st.markdown("---")

    submitted = st.button("Enviar encuesta", type="primary")

    if submitted:
        missing = []
        for sec in form:
            for grp in sec.get("groups", []):
                for q in grp.get("questions", []):
                    if q.get("required") and (q["id"] not in answers or answers[q["id"]] in (None, "", [], {})):
                        missing.append(q["text"])
        if missing:
            st.error("Faltan preguntas obligatorias:\n- " + "\n- ".join(missing[:12]) + ("" if len(missing)<=12 else "\n..."))
            return

        resp_id = db.create_response(version_id, metadata)

        for sec in form:
            for grp in sec.get("groups", []):
                for q in grp.get("questions", []):
                    val = answers.get(q["id"])
                    db.save_answer(resp_id, q, val)

        st.success(f"¡Gracias! Encuesta guardada con ID #{resp_id}.")
        st.info("Puedes diligenciar otra encuesta recargando la página.")
