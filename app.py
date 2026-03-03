"""Dashboard Streamlit para monitoreo financiero personal."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from categorizer import assign_category_and_learn, auto_categorize
from db import Database
from statement_parser import StatementParser


@contextmanager
def get_db():
    """Context manager que abre y cierra la conexión SQLite correctamente."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _load_transactions(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT t.*, c.name AS category_name
        FROM transactions t
        LEFT JOIN categories c ON c.id = t.category_id
        """,
        conn,
    )


def _render_sidebar(conn: sqlite3.Connection) -> None:
    """Muestra estado operacional del sistema en la barra lateral."""
    st.sidebar.header("Estado del sistema")

    last_gmail = conn.execute(
        "SELECT MAX(created_at) AS last FROM transactions WHERE source='gmail'"
    ).fetchone()["last"]
    st.sidebar.metric("Última ingesta Gmail", last_gmail or "Sin datos")

    pending_emails = conn.execute(
        "SELECT COUNT(*) AS n FROM unprocessed_emails"
    ).fetchone()["n"]
    color = "normal" if pending_emails == 0 else "inverse"
    st.sidebar.metric("Correos sin procesar", pending_emails, delta_color=color)

    st.sidebar.subheader("Cobertura — últimos 30 días")
    active_banks = {
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT bank FROM transactions WHERE date >= DATE('now', '-30 days')"
        )
    }
    for bank in ("BCI", "BANCO_ESTADO", "SECURITY"):
        icon = "✅" if bank in active_banks else "⚠️"
        st.sidebar.write(f"{icon} {bank}")


def _render_kpis(df: pd.DataFrame) -> None:
    today = pd.Timestamp.now(tz=config.TIMEZONE).date()
    current_month = pd.Timestamp.now(tz=config.TIMEZONE).to_period("M")
    previous_month = current_month - 1

    gasto_hoy = df[df["date"].dt.date == today]["amount"].sum()
    gasto_mes_actual = df[df["date"].dt.to_period("M") == current_month]["amount"].sum()
    gasto_mes_anterior = df[df["date"].dt.to_period("M") == previous_month]["amount"].sum()
    variacion = (
        (gasto_mes_actual - gasto_mes_anterior) / gasto_mes_anterior * 100
        if gasto_mes_anterior
        else 0.0
    )

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Gasto total hoy", f"${gasto_hoy:,.0f}".replace(",", "."))
    kpi2.metric("Gasto mes actual", f"${gasto_mes_actual:,.0f}".replace(",", "."))
    kpi3.metric(
        "Variación vs mes anterior",
        f"{variacion:.1f}%",
        delta=f"{variacion:.1f}%",
        delta_color="inverse",
    )


def _render_charts(df: pd.DataFrame) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Gasto por categoría")
        cat_df = (
            df[df["category_name"].notna()]
            .groupby("category_name")["amount"]
            .sum()
            .reset_index()
        )
        if cat_df.empty:
            st.info("Sin transacciones categorizadas aún")
        else:
            fig = px.pie(
                cat_df,
                names="category_name",
                values="amount",
                hole=0.35,
                color_discrete_sequence=px.colors.qualitative.Pastel,
            )
            fig.update_traces(textinfo="label+percent")
            fig.update_layout(showlegend=False, margin=dict(t=10, b=0, l=0, r=0))
            st.plotly_chart(fig, use_container_width=True)

    with col2:
        st.subheader("Evolución diaria del gasto")
        daily = df.groupby(df["date"].dt.date)["amount"].sum().reset_index()
        daily.columns = ["Fecha", "Monto"]
        st.line_chart(daily, x="Fecha", y="Monto")


def _render_categorization(conn: sqlite3.Connection, df: pd.DataFrame) -> None:
    st.subheader("Transacciones sin categoría")

    uncategorized = df[df["category_id"].isna()].copy()
    categories = pd.read_sql_query(
        "SELECT id, name FROM categories ORDER BY name", conn
    )

    if uncategorized.empty:
        st.success("Todas las transacciones están categorizadas")
        return

    if categories.empty:
        st.warning("No hay categorías definidas. Agregue categorías a la tabla `categories`.")
        return

    # Botón de auto-categorización
    if st.button("Auto-categorizar con reglas aprendidas"):
        with conn:
            n = auto_categorize(conn)
        st.success(f"Se categorizaron automáticamente {n} transacciones")
        st.rerun()

    cat_map = dict(zip(categories["id"], categories["name"]))
    cat_options = categories["id"].tolist()

    for _, row in uncategorized.iterrows():
        col1, col2, col3, col4 = st.columns([3, 2, 2, 1])
        col1.write(f"**{row['merchant']}**")
        col2.write(str(row["date"].date()))
        col3.write(f"${int(row['amount']):,}".replace(",", "."))
        selected = col4.selectbox(
            "cat",
            options=cat_options,
            format_func=lambda x, m=cat_map: m.get(x, "?"),
            key=f"cat-{int(row['id'])}",
            label_visibility="collapsed",
        )
        if st.button("Guardar", key=f"save-{int(row['id'])}"):
            with conn:
                assign_category_and_learn(
                    conn, int(row["id"]), int(selected), str(row["merchant"])
                )
            st.rerun()


def _render_pending(conn: sqlite3.Connection) -> None:
    st.subheader("Pendientes de verificación")
    pending = pd.read_sql_query(
        """
        SELECT id, bank, date, amount, type, merchant, source
        FROM transactions
        WHERE verified=0
        ORDER BY date DESC
        LIMIT 100
        """,
        conn,
    )
    if pending.empty:
        st.success("Sin transacciones pendientes de verificación")
    else:
        st.dataframe(pending, use_container_width=True)


def _render_rules(conn: sqlite3.Connection) -> None:
    """Muestra reglas de categorización aprendidas con opción de eliminar."""
    with st.expander("Reglas de categorización aprendidas"):
        rules = pd.read_sql_query(
            """
            SELECT cr.id, cr.pattern, c.name AS categoria, cr.created_at
            FROM category_rules cr
            JOIN categories c ON c.id = cr.category_id
            ORDER BY cr.created_at DESC
            """,
            conn,
        )
        if rules.empty:
            st.info("No hay reglas aprendidas aún")
            return

        st.dataframe(
            rules[["pattern", "categoria", "created_at"]],
            use_container_width=True,
        )
        rule_to_delete = st.selectbox(
            "Eliminar regla",
            options=rules["id"].tolist(),
            format_func=lambda x: rules[rules["id"] == x]["pattern"].iloc[0],
        )
        if st.button("Eliminar regla seleccionada"):
            with conn:
                conn.execute("DELETE FROM category_rules WHERE id=?", (rule_to_delete,))
            st.success("Regla eliminada")
            st.rerun()


def _render_cartola_upload() -> None:
    """Permite cargar una cartola PDF o CSV y persistirla en la base de datos."""
    with st.expander("Cargar cartola", expanded=False):
        uploaded = st.file_uploader(
            "Selecciona una cartola (PDF o CSV)",
            type=["pdf", "csv"],
            key="cartola_uploader",
        )
        password = st.text_input(
            "Contraseña del PDF",
            type="password",
            placeholder="Ej: 12345678-9  — dejar vacío si no tiene contraseña",
            key="cartola_password",
        )

        if uploaded and st.button("Procesar cartola"):
            suffix = ".pdf" if uploaded.name.lower().endswith(".pdf") else ".csv"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(uploaded.read())
                tmp_path = tmp.name
            try:
                transactions = StatementParser().parse_file(
                    tmp_path, password=password or None
                )
                saved = Database(config.DB_PATH).insert_transactions(transactions)
                st.success(
                    f"{saved} transacciones guardadas "
                    f"({len(transactions)} extraídas de «{uploaded.name}»)."
                )
                if saved < len(transactions):
                    st.info(f"{len(transactions) - saved} ya existían y fueron ignoradas.")
                st.rerun()
            except Exception as exc:
                st.error(f"Error al procesar la cartola: {exc}")
            finally:
                os.unlink(tmp_path)


def main() -> None:
    st.set_page_config(
        page_title="Finanzas Personales CL",
        layout="wide",
        page_icon="💰",
    )
    st.title("Consolidado financiero personal")

    with get_db() as conn:
        _render_sidebar(conn)
        _render_cartola_upload()
        st.divider()
        df = _load_transactions(conn)

        if df.empty:
            st.info(
                "No hay transacciones cargadas. "
                "Ejecute la ingesta de Gmail o cargue una cartola."
            )
            return

        df["date"] = pd.to_datetime(df["date"])

        _render_kpis(df)
        st.divider()
        _render_charts(df)
        st.divider()
        _render_categorization(conn, df)
        st.divider()
        _render_pending(conn)
        st.divider()
        _render_rules(conn)


if __name__ == "__main__":
    main()
