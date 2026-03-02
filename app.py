"""Dashboard Streamlit para monitoreo financiero personal."""

from __future__ import annotations

import sqlite3

import pandas as pd
import streamlit as st

from categorizer import assign_category_and_learn


def _load_transactions(conn: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query(
        """
        SELECT t.*, c.name AS category_name
        FROM transactions t
        LEFT JOIN categories c ON c.id=t.category_id
        """,
        conn,
    )


def main() -> None:
    """Renderiza dashboard base con KPIs y gráfico funcional."""

    st.set_page_config(page_title="Finanzas Personales CL", layout="wide")
    st.title("Consolidado financiero personal")

    conn = sqlite3.connect("finance.db")
    conn.row_factory = sqlite3.Row
    df = _load_transactions(conn)

    if df.empty:
        st.info("No hay transacciones cargadas")
        return

    df["date"] = pd.to_datetime(df["date"])
    today = pd.Timestamp.now(tz="America/Santiago").date()
    current_month = pd.Timestamp.now(tz="America/Santiago").to_period("M")
    previous_month = current_month - 1

    gasto_hoy = df[df["date"].dt.date == today]["amount"].sum()
    gasto_mes_actual = df[df["date"].dt.to_period("M") == current_month]["amount"].sum()
    gasto_mes_anterior = df[df["date"].dt.to_period("M") == previous_month]["amount"].sum()
    variacion = ((gasto_mes_actual - gasto_mes_anterior) / gasto_mes_anterior * 100) if gasto_mes_anterior else 0

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Gasto total hoy", f"${gasto_hoy:,.0f}".replace(",", "."))
    kpi2.metric("Gasto mes actual", f"${gasto_mes_actual:,.0f}".replace(",", "."))
    kpi3.metric("Variación vs mes anterior", f"{variacion:.1f}%")

    st.subheader("Evolución diaria")
    daily = df.groupby(df["date"].dt.date)["amount"].sum().reset_index()
    st.line_chart(daily, x="date", y="amount")

    st.subheader("Transacciones sin categoría")
    uncategorized = df[df["category_id"].isna()]
    categories = pd.read_sql_query("SELECT id, name FROM categories", conn)
    if uncategorized.empty:
        st.success("No hay transacciones pendientes de categorizar")
    else:
        for _, row in uncategorized.iterrows():
            st.write(f"{row['date'].date()} - {row['merchant']} - ${row['amount']:,.0f}".replace(",", "."))
            selected = st.selectbox(
                f"Categoría para transacción #{int(row['id'])}",
                options=categories["id"].tolist(),
                format_func=lambda x: categories[categories["id"] == x]["name"].iloc[0],
                key=f"tx-{int(row['id'])}",
            )
            if st.button(f"Guardar categoría #{int(row['id'])}"):
                assign_category_and_learn(conn, int(row["id"]), int(selected), str(row["merchant"]))
                conn.commit()
                st.rerun()

    st.subheader("Pendientes de verificación")
    pending = pd.read_sql_query("SELECT * FROM transactions WHERE verified=0", conn)
    st.dataframe(pending, use_container_width=True)


if __name__ == "__main__":
    main()
