# MX Installments – Page 0 (Weekly)
# v5 – redesigned chart and YoY table

import os
from datetime import timedelta

import numpy as np
import pandas as pd
import streamlit as st
import altair as alt
import io
import plotly.express as px
import plotly.graph_objects as go
import xlsxwriter
from xlsxwriter.utility import xl_col_to_name

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

st.set_page_config(page_title="MX Installments – Page 0 (Weekly)", layout="wide")


# ---------------------------
# Data loading helpers
# ---------------------------
@st.cache_data
def load_data(weekly_csv: str, cal_csv: str) -> pd.DataFrame:
    """Read weekly fact + comparison-week calendar and return merged dataframe.
    if code
    Expected columns:
    - weekly: week_start_date, program, asp_band_label, gms_local
    - calendar: week_start_date, comp_week_of_ly
    """
    if not os.path.exists(weekly_csv):
        raise FileNotFoundError(f"Weekly file not found: {weekly_csv}")
    if not os.path.exists(cal_csv):
        raise FileNotFoundError(f"Calendar file not found: {cal_csv}")

    weekly = pd.read_csv(weekly_csv)
    cal = pd.read_csv(cal_csv)

    # Filter out invalid programs first
    weekly = weekly[weekly['program'].notna() & (weekly['program'] != '')]

    # Parse dates with error handling
    try:
        weekly['week_start_date'] = pd.to_datetime(weekly['week_start_date'], format='%m/%d/%Y', errors='coerce')
        cal['week_start_date'] = pd.to_datetime(cal['week_start_date'], format='%m/%d/%Y', errors='coerce')
        cal['comp_week_of_ly'] = pd.to_datetime(cal['comp_week_of_ly'], format='%m/%d/%Y', errors='coerce')
    except:
        # Fallback to automatic parsing
        weekly['week_start_date'] = pd.to_datetime(weekly['week_start_date'], errors='coerce')
        cal['week_start_date'] = pd.to_datetime(cal['week_start_date'], errors='coerce')
        cal['comp_week_of_ly'] = pd.to_datetime(cal['comp_week_of_ly'], errors='coerce')

    # Remove rows with invalid dates
    weekly = weekly.dropna(subset=['week_start_date'])
    cal = cal.dropna(subset=['week_start_date', 'comp_week_of_ly'])

    # Normalize dates 
    weekly["week_start_date"] = weekly["week_start_date"].dt.normalize()
    cal["week_start_date"] = cal["week_start_date"].dt.normalize()
    cal["comp_week_of_ly"] = cal["comp_week_of_ly"].dt.normalize()

    # Basic column validation
    expected_weekly = {'week_start_date', 'program', 'asp_band_label', 'gms_local'}
    missing = expected_weekly - set(weekly.columns)
    if missing:
        raise ValueError(f"Missing columns in weekly file: {missing}")
    if 'comp_week_of_ly' not in cal.columns:
        raise ValueError("Calendar file must include 'comp_week_of_ly' column")

    # Merge calendar
    weekly = weekly.merge(cal[['week_start_date', 'comp_week_of_ly']],
                          on='week_start_date', how='left')

    # Normalize numeric
    weekly['gms_local'] = pd.to_numeric(weekly['gms_local'], errors='coerce').fillna(0.0)
    return weekly


def compute_wow_yoy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute WoW and YoY metrics at the most granular level available.

    Grain: week_start_date + program + asp_band_label + optional Channel + GL_product_ID
    """
    group_cols = ['week_start_date', 'program', 'asp_band_label']
    if 'Channel' in df.columns:
        group_cols.append('Channel')
    if 'GL_product_ID' in df.columns:
        group_cols.append('GL_product_ID')

    # Show data range for debugging
    st.write(f"Rango de fechas en datos: {df['week_start_date'].min()} a {df['week_start_date'].max()}")
    st.write(f"Total registros: {len(df):,}")

    # Aggregate GMS
    base = (
        df.groupby(group_cols, as_index=False)
          .agg(gms=('gms_local', 'sum'))
    )

    # WoW: join current week with prior week
    wow = base.copy()
    wow['prior_week'] = wow['week_start_date'] - pd.Timedelta(days=7)
    wow_merge_cols = ['prior_week'] + [c for c in group_cols if c != 'week_start_date']

    wow = wow.merge(
        base.rename(columns={'week_start_date': 'prior_week', 'gms': 'gms_pw'}),
        on=wow_merge_cols,
        how='left'
    )

    # YoY: use comparison-week calendar
    cal = df[['week_start_date', 'comp_week_of_ly']].drop_duplicates().dropna()
    
    # Simple merge: current data with calendar
    yoy = base.merge(cal, on='week_start_date', how='left')
    
    # Get historical data by renaming week_start_date to comp_week_of_ly
    base_ly = base.rename(columns={'week_start_date': 'comp_week_of_ly', 'gms': 'gms_ly'})
    
    # Merge to get LY data
    yoy_merge_cols = ['comp_week_of_ly'] + [c for c in group_cols if c != 'week_start_date']
    yoy = yoy.merge(base_ly, on=yoy_merge_cols, how='left')

    merged = wow.merge(
        yoy[group_cols + ['comp_week_of_ly', 'gms_ly']],
        on=group_cols,
        how='left'
    )

    merged['WoW %'] = np.where(
        merged['gms_pw'] > 0,
        (merged['gms'] / merged['gms_pw']) - 1,
        np.nan,
    )
    merged['YoY %'] = np.where(
        merged['gms_ly'] > 0,
        (merged['gms'] / merged['gms_ly']) - 1,
        np.nan,
    )

    return merged

##AFI by Band
def render_afi_asp_bands_view(weekly: pd.DataFrame):
    st.subheader("AFI – GMS by ASP Band (Last N Weeks)")
    # Aseguramos tipos de datos
    df = weekly.copy()
    df["week_start_date"] = pd.to_datetime(df["week_start_date"])
    # Filtrar solo AFI
    afi = df[df["program"] == "AFI"].copy()
    if afi.empty:
        st.warning("No hay datos para AFI en el archivo cargado.")
        return
    # Selector de número de semanas (Chema pidió 16 por default)
    num_weeks = st.slider("Número de semanas a mostrar", 4, 20, 16, key="num2")
    # Últimas N semanas disponibles para AFI
    weeks_sorted = sorted(afi["week_start_date"].unique())
    last_weeks = weeks_sorted[-num_weeks:]
    afi_n = afi[afi["week_start_date"].isin(last_weeks)]
   

    # Pivot: filas = semana, columnas = ASP band, valor = GMS
    pivot = afi_n.pivot_table(
        index="week_start_date",
        columns="asp_band_label",
        values="gms_local",
        aggfunc="sum"
    ).sort_index().fillna(0)
    if pivot.empty:
        st.warning("No hay datos para las semanas seleccionadas.")
        return
    
    # Filtro opcional de ASP bands
    all_bands = list(pivot.columns)
    selected_bands = st.multiselect(
        "ASP bands a mostrar",
        all_bands,
        default=all_bands
    )
    if selected_bands:
        pivot = pivot[selected_bands]

    
    
    # ======================
    # GRÁFICA STACKED BAR
    # ======================
    pivot_plot = pivot.reset_index()
    fig = px.bar(
        pivot_plot,
        x="week_start_date",
        y=pivot.columns,
        title="AFI – GMS (MXN) por ASP Band (stacked) – últimas semanas",
    )

    # ============================
    #   LÍNEA DE TOTAL AFI (MM)
    # ============================

    # Total por semana (solo AFI)
    total_df = (
        afi_n.groupby("week_start_date", as_index=False)["gms_local"]
             .sum()
             .rename(columns={"gms_local": "Total"})
    )

    # Convertir a millones
    total_df["Total_MM"] = total_df["Total"] / 1_000_000.0

    # Línea negra gruesa
    fig.add_trace(
        go.Scatter(
            x=total_df["week_start_date"],
            y=total_df["Total"],
            mode="lines+markers",
            line=dict(color="black", width=4),
            marker=dict(size=10, color="black"),
            name="Total GMS AFI",
            hovertemplate='<b>Total:</b> %{y:,.0f}<br>%{x}<extra></extra>'
        )
    )

    # ============================
    #   ETIQUETAS ARRIBA DE CADA BARRA
    # ============================ 

    fig.add_trace(
        go.Scatter(
            x=total_df["week_start_date"],
            y=total_df["Total"] * 1.02,  # 2% arriba del tope
            mode="text",
            text=[f"{v:.1f}" for v in total_df["Total_MM"]],
            textposition="top center",
            textfont=dict(size=12, color="black", family="Arial"),
            showlegend=False,
            hoverinfo="skip",
        )
    )

    fig.update_layout(
        barmode="stack",
        xaxis_title="Week start date",
        yaxis_title="GMS (MXN)",
        legend_title="ASP Band",
        hovermode="x unified",
        height=600,
    )
    fig.update_yaxes(tickformat=",")
    fig.update_xaxes(tickformat="%b %d\n%Y")

    # ==========================================
    # LABELS YoY% por ASP band dentro del stack
    # ==========================================
    # afi_n tiene los datos AFI de las últimas N semanas (ya filtrado arriba)
    afi_n = afi_n.copy()
    afi_n["iso_year"] = afi_n["week_start_date"].dt.isocalendar().year
    afi_n["iso_week"] = afi_n["week_start_date"].dt.isocalendar().week
    # Usamos TODO AFI (df) para calcular YoY contra el año anterior
    afi_all = df[df["program"] == "AFI"].copy()
    afi_all["iso_year"] = afi_all["week_start_date"].dt.isocalendar().year
    afi_all["iso_week"] = afi_all["week_start_date"].dt.isocalendar().week
    latest_year = int(afi_all["iso_year"].max())
    # GMS actual y LY por semana ISO + ASP band
    cur = (
        afi_all[afi_all["iso_year"] == latest_year]
        .groupby(["iso_week", "asp_band_label"], as_index=False)["gms_local"]
        .sum()
        .rename(columns={"gms_local": "gms_cur"})
    )
    ly = (
        afi_all[afi_all["iso_year"] == latest_year - 1]
        .groupby(["iso_week", "asp_band_label"], as_index=False)["gms_local"]
        .sum()
        .rename(columns={"gms_local": "gms_ly"})
    )
    yoy_band = cur.merge(
        ly,
        on=["iso_week", "asp_band_label"],
        how="left"
    )
    yoy_band["yoy_pct"] = np.where(
        yoy_band["gms_ly"] > 0,
        (yoy_band["gms_cur"] / yoy_band["gms_ly"]) - 1.0,
        np.nan
    )
    # Traemos el YoY a las semanas que estás graficando (afi_n)
    afi_n = afi_n.merge(
        yoy_band[["iso_week", "asp_band_label", "yoy_pct"]],
        on=["iso_week", "asp_band_label"],
        how="left"
    )
    # Agregamos por semana + ASP band para tener un punto por segmento
    labels_df = (
        afi_n.groupby(["week_start_date", "asp_band_label"], as_index=False)
        .agg(
            GMS=("gms_local", "sum"),
            YoY_pct=("yoy_pct", "mean"),
        )
    )
    # Convertimos a millones para coordinar con tu eje (opcional, si tu eje está en MXN deja sin dividir)
    labels_df["GMS_MM"] = labels_df["GMS"] / 1_000_000.0

    # UMBRAL para mostrar etiquetas (en millones)
    UMBRAL_MM = 5
    labels_df = labels_df[labels_df["GMS_MM"] >= UMBRAL_MM]
    # Cálculo de la posición vertical (centro del bloque del stack)
    labels_df = labels_df.sort_values(["week_start_date", "asp_band_label"])
    labels_df["cumsum_mm"] = labels_df.groupby("week_start_date")["GMS_MM"].cumsum()
    labels_df["y_bottom"] = labels_df["cumsum_mm"] - labels_df["GMS_MM"]
    labels_df["y_center"] = labels_df["y_bottom"] + labels_df["GMS_MM"] / 2.0
    # Creamos un trace SOLO de texto (no modifica tus barras)
    # Etiquetas de GMS en millones dentro de cada bloque
    labels_trace = go.Scatter(
        x=labels_df["week_start_date"],
        y=labels_df["y_center"] * 1_000_000.0,  # seguimos usando la misma posición en MXN
        mode="text",
        text=[
            f"{v:,.1f}" if pd.notnull(v) else ""
            for v in labels_df["GMS_MM"]   #: usamos GMS_MM, no YoY
        ],
        textposition="middle center",
        textfont=dict(size=10, color="black"),
        showlegend=False,
        hoverinfo="skip",
    )

    fig.add_trace(labels_trace)

    # ==========================
    # Botón para descargar la gráfica en PDF
    # ==========================
    try:
        pdf_bytes = fig.to_image(format="pdf")  # requiere kaleido instalado

        st.download_button(
            label=":page_facing_up: Download AFI Weekly GMS chart (PDF)",
            data=pdf_bytes,
            file_name="AFI_weekly_GMS_ASP_Bands.pdf",
            mime="application/pdf",
        )
    except Exception as e:
        st.warning(
            "No fue posible generar el PDF directamente. "
            "Verifica que tengas instalado el paquete 'kaleido' en tu entorno "
            "(por ejemplo: `pip install -U kaleido`)."
        )

    st.plotly_chart(fig, use_container_width=True)

    # ==========================================================
    # EXCEL: GMS ($MM) por ASP Band (Weeks as columns "GMS ($MM) – W42")
    # ==========================================================
    afi_all = df[df["program"] == "AFI"].copy()
    afi_all["iso_year"] = afi_all["week_start_date"].dt.isocalendar().year
    afi_all["iso_week"] = afi_all["week_start_date"].dt.isocalendar().week
    latest_year = int(afi_all["iso_year"].max())
    # GMS actual por año, semana, ASP band
    cur = (
        afi_all[afi_all["iso_year"] == latest_year]
        .groupby(["iso_year", "iso_week", "asp_band_label"], as_index=False)["gms_local"]
        .sum()
        .rename(columns={"gms_local": "gms_cur"})
    )
    # Pivot: filas = ASP band, columnas = semana ISO, valores = GMS en MM
    pivot_gms = cur.pivot_table(
        index="asp_band_label",
        columns="iso_week",
        values="gms_cur",
        aggfunc="sum"
    ).sort_index()
    # Lo pasamos a millones de pesos
    pivot_gms_mm = pivot_gms / 1_000_000.0
    # Renombrar columnas: GMS ($MM) – W42, W43, etc.
    new_cols = {w: f"GMS ($MM) – W{int(w)}" for w in pivot_gms_mm.columns}
    pivot_gms_mm = pivot_gms_mm.rename(columns=new_cols)
    # ==========================================
    # ARME EXECUTIVO: Rank, Avg GMS, Δ vs Avg
    # ==========================================
    # Promedio GMS por ASP band
    avg_by_band = pivot_gms_mm.mean(axis=1, skipna=True)
    # Rank (1 = banda con mayor promedio de GMS)
    rank_by_band = avg_by_band.rank(ascending=False, method="min").astype(int)
    # Promedio global (todas las bandas)
    overall_avg = avg_by_band.mean(skipna=True)
    # Δ vs promedio global
    delta_vs_avg = avg_by_band - overall_avg
    # Construimos DataFrame de salida:
    # ASP Band | Rank | GMS ($MM) – W.. | Avg GMS ($MM) | Δ vs Avg ($MM)
    df_out = pivot_gms_mm.copy()
    df_out["Rank"] = rank_by_band
    df_out["Avg GMS ($MM)"] = avg_by_band
    df_out["Δ vs Avg ($MM)"] = delta_vs_avg
    df_out.index.name = "ASP Band"
    # Fila "Average GMS"
    avg_row = {}
    for col in pivot_gms_mm.columns:
        avg_row[col] = pivot_gms_mm[col].mean(skipna=True)
    avg_row["Rank"] = None
    avg_row["Avg GMS ($MM)"] = overall_avg
    avg_row["Δ vs Avg ($MM)"] = 0.0
    # Fila "Δ vs Average" (por semana vs promedio global)
    delta_row = {}
    for col in pivot_gms_mm.columns:
        delta_row[col] = avg_row[col] - overall_avg
    delta_row["Rank"] = None
    delta_row["Avg GMS ($MM)"] = 0.0
    delta_row["Δ vs Avg ($MM)"] = 0.0
    df_out.loc["Average GMS"] = avg_row
    df_out.loc["Δ vs Average"] = delta_row
    # Orden de columnas
    df_excel = df_out.reset_index()
    cols_order = (
        ["ASP Band", "Rank"]
        + [c for c in df_excel.columns if c.startswith("GMS ($MM) – W")]
        + ["Avg GMS ($MM)", "Δ vs Avg ($MM)"]
    )
    df_excel = df_excel[cols_order]
    # ===========================
    # EXPORTAR CON FORMATO MEJORADO
    # ===========================
    # Mapa iso_week -> fecha (week_start_date) del año más reciente
    week_date_map = (
    afi_all[afi_all["iso_year"] == latest_year]
    .groupby("iso_week")["week_start_date"]
    .min()
    )
    # Lo convertimos a string para usarlo como header
    week_date_map_str = week_date_map.dt.strftime("%Y-%m-%d")

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_excel.to_excel(
        writer,
        sheet_name="AFI_ASP_Bands_GMS",
        index=False,
        startrow=1  # <-- dejamos la fila 0 libre para las fechas
        )
        workbook  = writer.book
        worksheet = writer.sheets["AFI_ASP_Bands_GMS"]
        n_rows = df_excel.shape[0]
        n_bands = pivot_gms_mm.shape[0]
        n_cols = df_excel.shape[1]
        # Formatos
        num_fmt = workbook.add_format({
        "num_format": "#,##0.0",
        "align": "center"
        })
        int_fmt = workbook.add_format({
        "num_format": "0",
        "align": "center"
        })
        header_fmt = workbook.add_format({
        "bold": True,
        "align": "center",
        "valign": "vcenter",
        "text_wrap": True,
        "bg_color": "DCE6F1_1",
        "border": 1
        })
        band_fmt = workbook.add_format({
        "align": "left"
        })
        # Columnas
        worksheet.set_column(0, 0, 18, band_fmt)   # ASP Band
        worksheet.set_column(1, 1, 6, int_fmt)     # Rank
        worksheet.set_column(2, n_cols - 1, 12, num_fmt)  # GMS ($MM) y promedios

        # ---------- Fila 0: fechas por semana ----------7
        for col_num, col_name in enumerate(df_excel.columns):
            date_text = ""
            if col_name.startswith("GMS ($MM) – W"):
                try:
                    week_num = int(col_name.split("W")[1])
                    date_text = week_date_map_str.get(week_num, "")
                except Exception:
                    date_text = ""
            # si no es columna de GMS, dejamos la celda vacía
            worksheet.write(0, col_num, date_text, header_fmt)

        # ---------- Fila 1: headers originales ----------
        for col_num, col_name in enumerate(df_excel.columns):
            worksheet.write(1, col_num, col_name, header_fmt)
        # Data bars en valores (solo bandas, sin filas de resumen)
        first_data_row = 2          #data starts in row 2
        last_data_row = n_bands + 1 # solo bandas fila 1
        first_week_col = 2
        last_week_col = n_cols - 1
        worksheet.conditional_format(
            first_data_row,
            first_week_col,
            last_data_row,
            last_week_col,
            {
                "type": "data_bar",
                "bar_color": "#63BE7B",
            }
        )
        # Gráfico: Avg GMS ($MM) por ASP Band
        from xlsxwriter.utility import xl_col_to_name
        chart = workbook.add_chart({"type": "column"})
        cat_range = f"=AFI_ASP_Bands_GMS!$A$2:$A${n_bands+1}"
        avg_col_idx = df_excel.columns.get_loc("Avg GMS ($MM)")
        avg_col_letter = xl_col_to_name(avg_col_idx)
        val_range = f"=AFI_ASP_Bands_GMS!${avg_col_letter}$2:${avg_col_letter}${n_bands+1}"
        chart.add_series({
            "name":       "Avg GMS ($MM) by ASP Band",
            "categories": cat_range,
            "values":     val_range,
            "data_labels": {"value": True},
        })
        chart.set_title({"name": "AFI – Avg GMS ($MM) by ASP Band"})
        chart.set_y_axis({"num_format": "#,##0.0", "major_gridlines": {"visible": False}})
        chart.set_legend({"none": True})
        chart.set_size({"width": 720, "height": 420})
        worksheet.insert_chart(1, n_cols + 1, chart)
    output.seek(0)
    st.download_button(
        label="Download AFI ASP Bands GMS (Excel – Executive)",
        data=output,
        file_name="AFI_GMS_ASP_Bands_last_weeks_executive.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )    

##########
# ---------------------------
# Page layout
# ---------------------------
st.title("MX Installments – Page 0 (Weekly)")
st.caption("Slicers: Week range, ASP band, Program, Channel, GL Product • Stacked GMS & YoY table (last 5 weeks)")

with st.sidebar:
    st.header("Data sources")
    default_weekly = "weekly_fact_template_v5.csv"
    default_cal = "comp_week_calendar_template_v5.csv"
    weekly_csv = st.text_input("Weekly fact CSV", value=default_weekly)
    cal_csv = st.text_input("Calendar CSV", value=default_cal)
    st.info(
        "Weekly: week_start_date, program, asp_band_label, gms_local, optional Channel & GL_product_ID.\n"
        "Calendar: week_start_date, comp_week_of_ly."
    )

weekly = None

try:
    weekly_path = BASE_DIR / weekly_csv
    cal_path = BASE_DIR / cal_csv

    st.write("Loading weekly from", weekly_path)
    st.write("Loading calendar from", cal_path)

    weekly = load_data(str(weekly_path), str(cal_path))
    metrics = compute_wow_yoy(weekly)
except Exception as e:
    st.error(f"Error loading data: {e}")
    st.stop()


    
##AFI by ASP band
st.markdown("---")
st.header("AFI – Deep dive ASP Bands (Chema request)")

render_afi_asp_bands_view(weekly)


# Basic week range
all_weeks = sorted(metrics['week_start_date'].unique())
latest_week = max(all_weeks)
earliest_week = min(all_weeks)

default_start = max(earliest_week, latest_week - timedelta(weeks=12))

st.subheader("Filters")
col_range, col_prog, col_asp = st.columns([2, 1, 1])

with col_range:
    week_range = st.slider(
        "Week range (start of week)",
        min_value=earliest_week.date(),
        max_value=latest_week.date(),
        value=(default_start.date(), latest_week.date()),
        key="week_range_slider"
    )

with col_prog:
    programs = sorted(metrics['program'].dropna().unique())
    default_programs = programs
    programs_sel = st.multiselect("Program", programs, default=default_programs)

with col_asp:
    asp_bands = sorted(metrics['asp_band_label'].dropna().unique())
    asp_sel = st.multiselect("ASP band", asp_bands, default=asp_bands)

# Filter after base slicers
filt = metrics.copy()
filt = filt[(filt['week_start_date'].dt.date >= week_range[0]) &
            (filt['week_start_date'].dt.date <= week_range[1])]
if programs_sel:
    filt = filt[filt['program'].isin(programs_sel)]
if asp_sel:
    filt = filt[filt['asp_band_label'].isin(asp_sel)]

# Dynamic filters for Channel & GL_product_ID based on previous selection
col_ch, col_gl = st.columns(2)
with col_ch:
    if 'Channel' in filt.columns:
        channels = sorted(filt['Channel'].dropna().unique())
        channel_sel = st.multiselect("Channel", channels, default=channels)
        if channel_sel:
            filt = filt[filt['Channel'].isin(channel_sel)]
    else:
        channel_sel = []

with col_gl:
    if 'GL_product_ID' in filt.columns:
        gl_ids = sorted(filt['GL_product_ID'].dropna().unique())
        gl_sel = st.multiselect("GL Product ID", gl_ids, default=gl_ids)
        if gl_sel:
            filt = filt[filt['GL_product_ID'].isin(gl_sel)]
    else:
        gl_sel = []

if filt.empty:
    st.warning("No data found with selected filters.")
    st.stop()

# -----------------------------------
# Weekly IFI GMS ($MM Pesos)
# -----------------------------------
st.subheader("Weekly Installments GMS ($MM Pesos)")
# 1) Agregamos por semana + programa
chart_df = (
    filt.groupby(['week_start_date', 'program'], as_index=False)
        .agg(GMS=('gms', 'sum'))
)
# Pasamos a millones
chart_df['GMS_MM'] = chart_df['GMS'] / 1_000_000.0
# Total por semana
total_df = chart_df.groupby('week_start_date', as_index=False)['GMS_MM'].sum()
total_df.rename(columns={'GMS_MM': 'Total_MM'}, inplace=True)
chart_df = chart_df.merge(total_df, on='week_start_date', how='left')

# :point_right: YoY por semana (total IFI)
yoy_total = (
    filt.groupby('week_start_date', as_index=False)
        .agg(
            GMS=('gms', 'sum'),
            GMS_LY=('gms_ly', 'sum')
        )
)

yoy_total['YoY_pct'] = np.where(
    yoy_total['GMS_LY'] > 0,
    (yoy_total['GMS'] / yoy_total['GMS_LY']) - 1,
    np.nan,
)

# lo unimos al total_df para usar en las etiquetas
total_df = total_df.merge(
    yoy_total[['week_start_date', 'YoY_pct']],
    on='week_start_date',
    how='left'
)


# Orden de programas
program_order = ['AFI', 'CPI', 'SPI', 'VFI']
chart_df['program'] = pd.Categorical(chart_df['program'], categories=program_order, ordered=True)
# :point_right: Ordenamos por semana y por programa (AFI, CPI, SPI, VFI)
order_map = {p: i for i, p in enumerate(program_order)}
chart_df['program_order_idx'] = chart_df['program'].map(order_map)
chart_df = chart_df.sort_values(['week_start_date', 'program_order_idx'])
total_df = total_df.sort_values('week_start_date')
# Etiquetas legibles de semana
chart_df['week_label'] = chart_df['week_start_date'].dt.strftime('%b %d, %Y')
total_df['week_label'] = total_df['week_start_date'].dt.strftime('%b %d, %Y')
# :point_right: Calculamos posición de inicio y centro de cada segmento
chart_df['y_bottom'] = chart_df.groupby('week_start_date')['GMS_MM'].cumsum() - chart_df['GMS_MM']
chart_df['y_center'] = chart_df['y_bottom'] + chart_df['GMS_MM'] / 2.0
# 2) Base X temporal
base = alt.Chart(chart_df).encode(
    x=alt.X(
        'week_start_date:T',
        title='',
        axis=alt.Axis(
            format='%b %d',     # Nov 09
            labelAngle=0,       # Horizontal
            tickCount={'interval': 'week', 'step': 1},  # Solo las fechas de datos
            labelFontSize=10
        )
    )
)
# 3) Barras apiladas (más gruesas)
bars = base.mark_bar(size=32).encode(
    y=alt.Y('GMS_MM:Q', stack='zero', title='GMS ($MM Pesos)'),
    color=alt.Color(
        'program:N',
        title='Program',
        scale=alt.Scale(
            domain=program_order,
            range=['#BFBFBF', '#E53935', '#43A047', '#FBC02D'],  # AFI, CPI, SPI, VFI
        ),
    ),
    order=alt.Order('program:N'),
    tooltip=[
        alt.Tooltip('week_label:N', title='Week'),
        alt.Tooltip('program:N', title='Program'),
        alt.Tooltip('GMS_MM:Q', format=',.1f', title='GMS ($MM)')
    ],
)
# 4) Línea de total
line = alt.Chart(total_df).mark_line(point=True).encode(
    x=alt.X('week_start_date:T', axis=alt.Axis(format='%b %d, %Y', labelAngle=0)),
    y='Total_MM:Q',
    color=alt.value('black'),
    tooltip=[
        alt.Tooltip('week_label:N', title='Week'),
        alt.Tooltip('Total_MM:Q', format=',.1f', title='Total GMS ($MM)')
    ],
)
# 5) Etiquetas de TOTAL arriba de cada barra
labels = alt.Chart(total_df).mark_text(
    dy=-15,
    fontSize=14,
    fontWeight='bold',
    color='black'
).encode(
    x=alt.X('week_start_date:T', axis=alt.Axis(format='%b %d, %Y', labelAngle=0)),
    y='Total_MM:Q',
    text=alt.Text('Total_MM:Q', format=',.1f')
)

# 6) :fire: Etiquetas DENTRO de cada segmento (AFI/CPI/SPI/VFI)
segment_labels = alt.Chart(chart_df).mark_text(
    fontSize=10,
    fontWeight='bold',
    color='black'
).encode(
    x=alt.X('week_start_date:T', axis=alt.Axis(format='%b %d, %Y', labelAngle=0)),
    y='y_center:Q',                           # :point_left: centro exacto del bloque
    text=alt.Text('GMS_MM:Q', format=',.1f')  # ej. 346.1, 243.4, etc.
)
# 7) Dibujar todo junto
#  Gráfica final en formato widescreen con título grande
full_chart = (bars + line + labels + segment_labels).properties(
    width=1100,  # Volver al ancho original
    height=700,
    title=alt.TitleParams(
        text="Weekly IFI GMS ($MM Pesos)",
        fontSize=44,
        fontWeight="bold",
        anchor="start",
        offset=12
    )
)

st.altair_chart(full_chart, use_container_width=True)

# --- Exportar la gráfica como HTML (para luego pasarla a PDF o imagen) ---
html_path = "weekly_gms_chart.html"
full_chart.save(html_path)   # NO requiere altair_saver

with open(html_path, "r", encoding="utf-8") as f:
    html_content = f.read()
    st.download_button(
        label=":page_facing_up: Descargar gráfica (HTML)",
        data=html_content,
        file_name="weekly_gms_chart.html",
        mime="text/html",
    )



# -----------------------------------
# YoY table – last 5 weeks, aggregated
# -----------------------------------
#####
st.subheader("YoY GMS - Last 5 Weeks (All selected programs)")

# 1) totales semanales
week_summary = (
    filt.groupby('week_start_date', as_index=False)
        .agg(
            GMS=('gms', 'sum')
        )
)
#2) traer comp week of ly
cal_map = (
    metrics[['week_start_date', 'comp_week_of_ly']]
    .drop_duplicates()
    .dropna()
)

week_summary = week_summary.merge(
    cal_map, 
    on="week_start_date", 
    how="left"
    )

#3) construir dataset
filt_same = metrics.copy()
filt_same = filt_same[
    (filt_same['week_start_date'].dt.date >= week_range[0]) &
    (filt_same['week_start_date'].dt.date <= week_range[1])
]

if programs_sel:
    filt_same = filt_same[filt_same['program'].isin(programs_sel)]
if asp_sel:
    filt_same = filt_same[filt_same['asp_band_label'].isin(asp_sel)]

if 'Channel' in filt_same.columns and channel_sel:
    filt_same = filt_same[filt_same['Channel'].isin(channel_sel)]
if "GL_product_ID" in filt_same.columns and gl_sel:
    filt_same = filt_same[filt_same["GL_product_ID"].isin(gl_sel)]

# 4) totales ly por semana
filt_same_ly = (
    filt_same.merge(
        cal_map, 
        on="week_start_date",
        how="left"
    )
)

filt_ly = metrics.copy()

filt_ly = filt_ly[
    filt_ly['week_start_date'].isin(
        week_summary["comp_week_of_ly"].dropna())
]


ly_totals = (
    filt_ly
    .groupby('week_start_date', as_index=False)
    .agg(GMS_LY=('gms', 'sum'))
    .rename(columns={'week_start_date': 'comp_week_of_ly'}))

#5)pegar ly a la tabla
week_summary = week_summary.merge(ly_totals, on="comp_week_of_ly", how="left")


# 6) calcular yoy
week_summary['YoY %'] = np.where(
    week_summary['GMS_LY'] > 0,
    (week_summary['GMS'] / week_summary['GMS_LY']) - 1,
    np.nan,
)

# 7)last 5 eeks
week_summary = week_summary.sort_values('week_start_date', ascending=False).head(5)
week_summary = week_summary.sort_values('week_start_date')
#8)formato de display
week_summary['Week'] = week_summary['week_start_date'].dt.strftime('%b %d, %Y')
week_summary['GMS ($MM)'] = week_summary['GMS'] / 1_000_000.0
week_summary['GMS LY ($MM)'] = week_summary['GMS_LY'] / 1_000_000.0
week_summary['YoY %'] = week_summary['YoY %'] * 100

yoy_display = week_summary[['Week', 'GMS ($MM)', 'GMS LY ($MM)', 'YoY %']].copy()
yoy_display['GMS ($MM)'] = yoy_display['GMS ($MM)'].map(lambda x: f"{x:,.1f}" if pd.notnull(x) else "N/A")
yoy_display['GMS LY ($MM)'] = yoy_display['GMS LY ($MM)'].map(lambda x: f"{x:,.1f}" if pd.notnull(x) else "N/A")
yoy_display['YoY %'] = yoy_display['YoY %'].map(lambda x: f"{x:,.1f}%" if pd.notnull(x) else "N/A")

st.dataframe(
    yoy_display.set_index('Week'),
    use_container_width=True,
)
######
# -----------------------------------
# Export CSV – keep original structure as much as possible
# -----------------------------------
# Build table similar to your original 'tbl'
tbl = filt.copy()
tbl = tbl.merge(
    weekly[['week_start_date', 'comp_week_of_ly']].drop_duplicates(),
    on='week_start_date',
    how='left',
    suffixes=('', '_cal')
)

tbl['fecha_actual'] = tbl['week_start_date']
tbl['GMS'] = tbl['gms']
tbl['fecha_pw'] = tbl['prior_week']
tbl['GMS_PW'] = tbl['gms_pw']
tbl['fecha_ly'] = tbl['comp_week_of_ly']
tbl['GMS_LY'] = tbl['gms_ly']
tbl['WoW'] = tbl['WoW %']
tbl['YoY'] = tbl['YoY %']

st.subheader("Downloads")
csv_export = tbl.copy()
st.write(f"Summary CSV records: {len(csv_export):,}")

desired_order = [
    'fecha_actual', 'GMS',
    'fecha_pw', 'GMS_PW',
    'fecha_ly', 'GMS_LY',
    'program', 'asp_band_label',
    'WoW', 'YoY',
]
if 'Channel' in csv_export.columns:
    desired_order.append('Channel')
if 'GL_product_ID' in csv_export.columns:
    desired_order.append('GL_product_ID')

existing_cols = [c for c in desired_order if c in csv_export.columns]
csv_export = csv_export[existing_cols]

csv_bytes = csv_export.to_csv(index=False).encode('utf-8')
st.download_button(
    "Download summary CSV",
    csv_bytes,
    file_name=f"mx_installments_summary_{latest_week.date()}.csv",
    mime="text/csv",
)
