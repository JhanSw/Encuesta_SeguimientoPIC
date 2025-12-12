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

    # --- Administración: borrar registros ---
    with st.expander("Borrar registros", expanded=False):
        st.warning("⚠️ Esto elimina encuestas y sus respuestas. No se puede deshacer.")
        rows = db.list_response_summaries(version_id, limit=300)
        if not rows:
            st.info("No hay registros para borrar.")
        else:
            opts = [
                f"#{r['id']} | {str(r['created_at'])[:19]}" for r in rows
            ]
            sel = st.multiselect("Selecciona encuestas a borrar", options=opts)
            confirm = st.checkbox("Confirmo que quiero borrar los registros seleccionados", value=False)
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Borrar seleccionadas", type="primary", disabled=(not sel or not confirm)):
                    ids = [int(x.split("|", 1)[0].replace("#", "").strip()) for x in sel]
                    db.delete_responses(ids)
                    st.success(f"Borradas {len(ids)} encuestas.")
                    st.rerun()
            with c2:
                confirm_all = st.checkbox("Confirmo borrar TODAS las encuestas", value=False)
                if st.button("Borrar TODO", disabled=(not confirm_all), help="Elimina todas las encuestas de esta versión"):
                    db.delete_all_responses(version_id)
                    st.success("Borradas todas las encuestas.")
                    st.rerun()

    st.caption("Exporta en formato ancho: 1 fila = 1 encuesta; columnas = preguntas.")

    if st.button("Generar Excel", type="primary", disabled=(n==0)):
        try:
            df = db.export_answers_wide(version_id)
        except Exception as e:
            st.error(f"No se pudo exportar: {e}")
            st.stop()
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
