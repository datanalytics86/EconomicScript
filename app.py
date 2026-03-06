"""Dashboard Streamlit para monitoreo financiero personal."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, timedelta
from io import BytesIO

import pandas as pd
import plotly.express as px
import streamlit as st

import config
from categorizer import assign_category_and_learn, auto_categorize
from db import Database, get_or_create_category, get_transactions_for_export
from gmail_ingest import GmailIngestor
from statement_parser import StatementParser
from utils import get_cycle_start_date


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


# ── Sidebar ────────────────────────────────────────────────────────────────────

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


# ── KPIs ───────────────────────────────────────────────────────────────────────

def _render_kpis(df: pd.DataFrame) -> None:
    today = pd.Timestamp.now(tz=config.TIMEZONE).date()
    cycle_start = get_cycle_start_date(today)
    prev_cycle_start = get_cycle_start_date(
        cycle_start - timedelta(days=1)  # un día antes del ciclo → mes anterior
    )

    # Solo gastos (amount > 0); abonos/devoluciones tienen amount < 0
    gastos = df[df["amount"] > 0]

    gasto_hoy = gastos[gastos["date"].dt.date == today]["amount"].sum()

    gasto_ciclo = gastos[gastos["date"].dt.date >= cycle_start]["amount"].sum()

    days_elapsed = (today - cycle_start).days
    prev_cycle_end = prev_cycle_start + timedelta(days=days_elapsed)
    gasto_ciclo_anterior = gastos[
        (gastos["date"].dt.date >= prev_cycle_start)
        & (gastos["date"].dt.date <= prev_cycle_end)
    ]["amount"].sum()

    variacion = (
        (gasto_ciclo - gasto_ciclo_anterior) / gasto_ciclo_anterior * 100
        if gasto_ciclo_anterior
        else 0.0
    )

    kpi1, kpi2, kpi3 = st.columns(3)
    kpi1.metric("Gasto total hoy", f"${gasto_hoy:,.0f}".replace(",", "."))
    kpi2.metric(
        f"Acumulado del ciclo",
        f"${gasto_ciclo:,.0f}".replace(",", "."),
        help=f"Gastos desde el {cycle_start.strftime('%d/%m/%Y')} (inicio del ciclo)",
    )
    kpi3.metric(
        "Variación vs ciclo anterior",
        f"{variacion:.1f}%",
        delta=f"{variacion:.1f}%",
        delta_color="inverse",
        help=f"Comparado con los mismos {days_elapsed + 1} días del ciclo anterior",
    )


# ── Gráficos ───────────────────────────────────────────────────────────────────

def _render_charts(df: pd.DataFrame) -> None:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Gasto por categoría")
        cat_df = (
            df[(df["category_name"].notna()) & (df["amount"] > 0)]
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
        daily = (
            df[df["amount"] > 0]
            .groupby(df["date"].dt.date)["amount"]
            .sum()
            .reset_index()
        )
        daily.columns = ["Fecha", "Monto"]
        st.line_chart(daily, x="Fecha", y="Monto")


# ── Ingesta Gmail ──────────────────────────────────────────────────────────────

def _render_gmail_ingest(conn: sqlite3.Connection) -> None:
    """Sección para disparar la ingesta de Gmail con filtro de fecha."""
    with st.expander("Ingesta de Gmail", expanded=False):
        if not config.IMAP_USER or not config.OAUTH_CLIENT_ID or not config.OAUTH_REFRESH_TOKEN:
            st.warning(
                "Configura IMAP_USER, OAUTH_CLIENT_ID y OAUTH_REFRESH_TOKEN en el archivo .env para usar esta función."
            )
            return

        last_gmail = conn.execute(
            "SELECT MAX(date) AS d FROM transactions WHERE source='gmail'"
        ).fetchone()["d"]
        if last_gmail:
            st.caption(f"Último correo Gmail en DB: **{last_gmail}**")

        st.write(
            "Busca correos de notificaciones bancarias (BCI, BancoEstado, Security) "
            "y los importa a la base de datos. La deduplicación es automática."
        )

        def _run_ingest(since_date_arg: date | None) -> None:
            progress_bar = st.progress(0)
            status_slot = st.empty()
            status_slot.info("Conectando a Gmail…")
            try:
                db = Database(config.DB_PATH)
                ingestor = GmailIngestor(db)

                def _update_progress(current: int, total: int, msg: str) -> None:
                    pct = current / total if total else 1.0
                    progress_bar.progress(pct)
                    status_slot.caption(f"{msg}  ({current}/{total})")

                summary = ingestor.ingest(since_date=since_date_arg, progress_callback=_update_progress)
                progress_bar.progress(1.0)
                status_slot.empty()
                st.success(
                    f"Ingesta completada — "
                    f"encontrados: **{summary['found']}** | "
                    f"procesados: **{summary['processed']}** | "
                    f"guardados: **{summary['saved']}** | "
                    f"fallidos: **{summary['failed']}**"
                )
                if summary.get("no_parser", 0):
                    st.info(
                        f"{summary['no_parser']} correos sin parser compatible "
                        "(guardados en 'Correos sin procesar')."
                    )
                st.rerun()
            except Exception as exc:
                progress_bar.empty()
                status_slot.empty()
                st.error(f"Error durante la ingesta: {exc}")

        # ── Modo incremental (uso diario) ──────────────────────────────────────
        st.write("**Modo rápido** — solo correos no leídos (uso diario):")
        if st.button("Actualizar (solo correos nuevos)", key="btn_gmail_unseen"):
            _run_ingest(since_date_arg=None)

        st.divider()

        # ── Modo histórico ─────────────────────────────────────────────────────
        st.write("**Modo histórico** — re-descarga todos los correos desde una fecha:")
        default_since = date.today() - timedelta(days=7)
        since = st.date_input(
            "Procesar correos desde",
            value=default_since,
            max_value=date.today(),
            help="Se incluirán correos leídos y no leídos desde esta fecha.",
            key="gmail_since_date",
        )
        if st.button("Re-ingestar desde fecha", key="btn_gmail_ingest"):
            _run_ingest(since_date_arg=since)


# ── Carga de cartolas ──────────────────────────────────────────────────────────

def _render_cartola_upload() -> None:
    """Permite cargar una cartola PDF o CSV y persistirla en la base de datos."""
    with st.expander("Cargar cartola / Estado de cuenta", expanded=False):
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


# ── Gestión de categorías ──────────────────────────────────────────────────────

def _render_category_manager(conn: sqlite3.Connection) -> None:
    """Sección siempre visible para crear y gestionar categorías."""
    st.subheader("Gestión de categorías")

    categories = pd.read_sql_query(
        "SELECT id, name, keywords, created_at FROM categories ORDER BY name", conn
    )

    col_create, col_list = st.columns([1, 2])

    with col_create:
        st.write("**Nueva categoría**")
        new_name = st.text_input(
            "Nombre",
            placeholder="Ej: Alimentación, Transporte…",
            key="new_category_name",
        )
        new_keywords = st.text_input(
            "Keywords iniciales (opcional, separadas por coma)",
            placeholder="Ej: SUPERMERCADO, UNIMARC, JUMBO",
            key="new_category_keywords",
        )
        if st.button("Crear categoría", key="btn_create_category"):
            if not new_name.strip():
                st.warning("Ingresa un nombre para la categoría.")
            else:
                import json

                keywords_list = (
                    [k.strip().upper() for k in new_keywords.split(",") if k.strip()]
                    if new_keywords
                    else []
                )
                try:
                    with conn:
                        conn.execute(
                            "INSERT INTO categories(name, keywords) VALUES(?, ?)",
                            (new_name.strip(), json.dumps(keywords_list)),
                        )
                        # Si hay keywords, crear las reglas automáticamente
                        cat_id = conn.execute(
                            "SELECT id FROM categories WHERE name=?", (new_name.strip(),)
                        ).fetchone()["id"]
                        for kw in keywords_list:
                            conn.execute(
                                "INSERT OR IGNORE INTO category_rules(pattern, category_id) VALUES(?, ?)",
                                (kw, cat_id),
                            )
                    st.success(f"Categoría «{new_name.strip()}» creada.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Error al crear categoría: {exc}")

    with col_list:
        if categories.empty:
            st.info(
                "No hay categorías definidas aún. "
                "Crea las primeras categorías para poder clasificar tus transacciones."
            )
        else:
            st.write(f"**{len(categories)} categorías definidas**")
            st.dataframe(
                categories[["name", "keywords"]].rename(
                    columns={"name": "Nombre", "keywords": "Keywords"}
                ),
                use_container_width=True,
                hide_index=True,
            )

            cat_to_delete = st.selectbox(
                "Eliminar categoría",
                options=categories["id"].tolist(),
                format_func=lambda x: categories[categories["id"] == x]["name"].iloc[0],
                key="sel_delete_category",
            )
            if st.button("Eliminar categoría seleccionada", key="btn_delete_category"):
                with conn:
                    conn.execute("DELETE FROM categories WHERE id=?", (cat_to_delete,))
                st.success("Categoría eliminada.")
                st.rerun()


# ── Categorización manual ──────────────────────────────────────────────────────

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
        st.info(
            "Crea categorías en la sección **Gestión de categorías** "
            "para poder clasificar las transacciones."
        )
        return

    # Botón de auto-categorización
    if st.button("Auto-categorizar con reglas aprendidas", key="btn_autocategorize"):
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


# ── Pendientes de verificación ─────────────────────────────────────────────────

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


# ── Reglas aprendidas ──────────────────────────────────────────────────────────

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


# ── Categorización masiva vía Excel ────────────────────────────────────────────

def _render_bulk_categorization(conn: sqlite3.Connection) -> None:
    """Exporta transacciones a Excel para categorizar en bulk e importar de vuelta."""
    with st.expander("Categorización masiva (Excel)", expanded=False):
        st.write(
            "Descarga las transacciones en Excel, rellena la columna "
            "**categoria_nueva** y vuelve a subir el archivo. "
            "El sistema asignará la categoría y aprenderá la regla para ese comercio."
        )

        # ── Filtros ────────────────────────────────────────────────────────────
        col_f1, col_f2, col_f3, col_f4 = st.columns(4)
        since = col_f1.date_input(
            "Desde", value=date.today() - timedelta(days=90), key="bulk_since"
        )
        until = col_f2.date_input("Hasta", value=date.today(), key="bulk_until")
        bank_opts = ["(todos)", "BCI", "BANCO_ESTADO", "SECURITY"]
        bank_sel = col_f3.selectbox("Banco", bank_opts, key="bulk_bank")
        uncategorized_only = col_f4.checkbox(
            "Solo sin categorizar", value=True, key="bulk_uncategorized"
        )

        bank_filter = None if bank_sel == "(todos)" else bank_sel

        # ── Exportar ───────────────────────────────────────────────────────────
        rows = get_transactions_for_export(conn, since, until, bank_filter, uncategorized_only)
        if rows:
            df_exp = pd.DataFrame(rows)
            df_exp["categoria_nueva"] = ""
            buf = BytesIO()
            df_exp.to_excel(buf, index=False, engine="openpyxl")
            st.download_button(
                label=f"Descargar Excel ({len(rows)} transacciones)",
                data=buf.getvalue(),
                file_name=f"transacciones_{since}_{until}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_excel",
            )
        else:
            st.info("Sin transacciones con los filtros seleccionados.")

        st.divider()

        # ── Importar ───────────────────────────────────────────────────────────
        st.write("**Importar Excel categorizado:**")
        uploaded = st.file_uploader(
            "Sube el Excel con la columna categoria_nueva rellena",
            type=["xlsx"],
            key="bulk_uploader",
        )
        if uploaded and st.button("Aplicar categorías", key="btn_import_excel"):
            df_in = pd.read_excel(uploaded, engine="openpyxl")
            to_process = df_in[
                df_in["categoria_nueva"].notna()
                & (df_in["categoria_nueva"].astype(str).str.strip() != "")
            ]
            ok, errors = 0, []
            for _, row in to_process.iterrows():
                try:
                    cat_id = get_or_create_category(
                        conn, str(row["categoria_nueva"]).strip()
                    )
                    assign_category_and_learn(
                        conn, int(row["id"]), cat_id, str(row["comercio"])
                    )
                    ok += 1
                except Exception as exc:
                    errors.append(f"ID {row.get('id', '?')}: {exc}")
            conn.commit()
            n_auto = auto_categorize(conn)
            conn.commit()
            st.success(
                f"{ok} transacciones categorizadas manualmente"
                + (f" + {n_auto} adicionales por reglas aprendidas" if n_auto else "")
            )
            if errors:
                st.warning("Errores:\n" + "\n".join(errors))
            st.rerun()


# ── Diagnóstico de correo diario ───────────────────────────────────────────────

def _render_email_diagnostics() -> None:
    """Muestra estado de configuración SMTP y permite enviar un test."""
    with st.expander("Diagnóstico correo diario (SMTP)", expanded=False):
        smtp_user = config.SMTP_USER or config.IMAP_USER
        smtp_to = config.SMTP_TO
        smtp_password = config.SMTP_PASSWORD

        col1, col2 = st.columns(2)
        col1.metric("Remitente", smtp_user or "No configurado")
        col2.metric("Destinatario (SMTP_TO)", smtp_to or "No configurado")

        if not smtp_password:
            st.error(
                "**SMTP_PASSWORD no está configurado en `.env`** — "
                "esta es la causa de que no lleguen los correos automáticos.\n\n"
                "**Pasos para solucionarlo:**\n"
                "1. Ve a https://myaccount.google.com/apppasswords\n"
                "2. Crea una App Password (categoría: Correo)\n"
                "3. Agrega en tu `.env`:\n"
                "   ```\n"
                "   SMTP_PASSWORD=xxxx xxxx xxxx xxxx\n"
                "   ```\n"
                "4. Reinicia el dashboard y vuelve a probar aquí."
            )
            return

        st.success("SMTP_PASSWORD configurado correctamente")

        st.divider()
        report_date_test = st.date_input(
            "Fecha del reporte de prueba",
            value=date.today() - timedelta(days=1),
            key="test_email_date",
        )
        if st.button("Enviar reporte de prueba", key="btn_test_email"):
            from daily_report import send_daily_report
            try:
                send_daily_report(report_date=report_date_test)
                st.success(f"Reporte enviado a {smtp_to}")
            except Exception as exc:
                st.error(f"Error al enviar: {exc}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    st.set_page_config(
        page_title="Finanzas Personales CL",
        layout="wide",
        page_icon="💰",
    )
    st.title("Consolidado financiero personal")

    Database(config.DB_PATH).init_schema(config.SCHEMA_PATH)

    with get_db() as conn:
        _render_sidebar(conn)

        # Secciones siempre visibles (independiente de si hay transacciones)
        _render_gmail_ingest(conn)
        _render_cartola_upload()
        _render_email_diagnostics()
        st.divider()
        _render_category_manager(conn)
        _render_bulk_categorization(conn)
        st.divider()

        df = _load_transactions(conn)

        if df.empty:
            st.info(
                "No hay transacciones cargadas aún. "
                "Usa **Ingesta de Gmail** o **Cargar cartola** para comenzar."
            )
            return

        df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce").dt.tz_convert(config.TIMEZONE)

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
