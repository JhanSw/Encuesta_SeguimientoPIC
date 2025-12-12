\
import io
import datetime
import streamlit as st
import pandas as pd
import db



def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Convierte columnas datetime con timezone a naive (Excel no soporta tz-aware)."""
    df = df.copy()
    for col in df.columns:
        s = df[col]
        try:
            if pd.api.types.is_datetime64tz_dtype(s):
                df[col] = s.dt.tz_convert(None)
        except Exception:
            pass
        # object dtype con datetimes tz-aware
        if df[col].dtype == "object":
            def _fix(v):
                if isinstance(v, (datetime.datetime,)):
                    if v.tzinfo is not None:
                        return v.replace(tzinfo=None)
                return v
            df[col] = df[col].map(_fix)
    return df

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
                df = _excel_safe(df)
                df.to_excel(output, index=False, sheet_name="respuestas")
        output.seek(0)
        st.download_button(
            label="Descargar Excel",
            data=output,
            file_name="respuestas_encuesta_pic.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        st.dataframe(df.head(20), use_container_width=True)
