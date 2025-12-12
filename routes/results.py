\
import io
import streamlit as st
import db

def results_page(version_id: int):
    st.title("Respuestas y exportación")
    n = db.count_responses(version_id)
    st.metric("Encuestas registradas", n)

    st.caption("Exporta en formato ancho: 1 fila = 1 encuesta; columnas = preguntas.")

    if st.button("Generar Excel", type="primary", disabled=(n==0)):
        df = db.export_answers_wide(version_id)
        if df.empty:
            st.warning("No hay datos para exportar.")
            return
        output = io.BytesIO()
        with st.spinner("Generando Excel..."):
            with st.container():
                df.to_excel(output, index=False, sheet_name="respuestas")
        output.seek(0)
        st.download_button(
            label="Descargar Excel",
            data=output,
            file_name="respuestas_encuesta_pic.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.dataframe(df.head(20), use_container_width=True)
