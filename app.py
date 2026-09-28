"""
Streamlit-app der viser data fra su_status_log.csv.

Kør lokalt:   streamlit run app.py
Gratis hosting: Streamlit Community Cloud (se README).
"""

import re
from pathlib import Path

import pandas as pd
import streamlit as st

LOG_FILE = Path(__file__).resolve().parent / "su_status_log.csv"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

MAANEDER = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}

DATO_FELTER = {
    "behandlet_til_videregaende": "Behandlet til – Videregående uddannelser",
    "behandlet_til_erhverv": "Behandlet til – Erhvervsuddannelser",
    "yderligere_oplysninger_videregaende": "Ældste afventende sag – Videregående",
    "yderligere_oplysninger_erhverv": "Ældste afventende sag – Erhvervsuddannelser",
}


def parse_dansk_dato(tekst):
    """'1. januar 2026' -> Timestamp. Returnerer NaT hvis det ikke kan læses."""
    if not isinstance(tekst, str):
        return pd.NaT
    m = re.search(r"(\d{1,2})\.?\s*([A-Za-zæøåÆØÅ]+)\s+(\d{4})", tekst)
    if not m:
        return pd.NaT
    dag, maaned, aar = m.groups()
    nr = MAANEDER.get(maaned.lower())
    if not nr:
        return pd.NaT
    try:
        return pd.Timestamp(int(aar), nr, int(dag))
    except ValueError:
        return pd.NaT


@st.cache_data(ttl=300)
def load_log():
    if not LOG_FILE.exists():
        return None
    df = pd.read_csv(LOG_FILE, dtype=str).fillna("")
    df["tjek_tidspunkt"] = pd.to_datetime(df["tjek_tidspunkt"], errors="coerce")
    for kol in DATO_FELTER:
        if kol in df.columns:
            df[kol + "_dato"] = df[kol].apply(parse_dansk_dato)
    return df


st.set_page_config(page_title="SU handicaptillæg – status", page_icon="📊", layout="wide")
st.title("📊 SU handicaptillæg – status på sagsbehandling")
st.caption("Data hentes automatisk fra su.dk tirsdag aften og onsdag morgen.")

df = load_log()

if df is None or df.empty:
    st.info("Der er endnu ikke logget nogen data. Kør workflowet på GitHub én gang, og genindlæs siden.")
    st.stop()

seneste = df.iloc[-1]
forrige = df.iloc[-2] if len(df) > 1 else None

# --- Seneste værdier -------------------------------------------------------
st.subheader("Seneste tjek")
st.write(f"**{seneste['ugedag']} {seneste['tjek_tidspunkt']:%d-%m-%Y kl. %H:%M}** "
         f"· su.dk angiver selv: *opdateret {seneste['side_opdateret'] or 'ukendt'}* "
         f"· ændret siden sidst: **{seneste['aendret_siden_sidste_tjek']}**")

kolonner = st.columns(len(DATO_FELTER))
for kol, (felt, titel) in zip(kolonner, DATO_FELTER.items()):
    ny = seneste.get(felt, "")
    gammel = forrige[felt] if forrige is not None else None
    delta = None
    if gammel is not None and gammel != ny:
        delta = f"før: {gammel}"
    kol.metric(titel, ny or "–", delta=delta, delta_color="off")

# --- Udvikling over tid ----------------------------------------------------
st.subheader("Udvikling over tid")
chart_cols = [k + "_dato" for k in DATO_FELTER if k + "_dato" in df.columns]
chart_df = df.set_index("tjek_tidspunkt")[chart_cols].dropna(how="all")
chart_df = chart_df.rename(columns={k + "_dato": v for k, v in DATO_FELTER.items()})
if chart_df.notna().any().any():
    # Y-aksen er selve datoen (vist som tal); tabellen nedenfor viser de læsbare datoer
    st.line_chart(chart_df.apply(lambda s: s.map(lambda d: d.toordinal() if pd.notna(d) else None)))
    st.caption("Y-aksen er en løbende dagstæller: jo højere op, jo nyere dato er sagsbehandlingen nået til.")
else:
    st.write("Ikke nok læsbare datoer til at tegne en graf endnu.")

# --- Ændringer -------------------------------------------------------------
st.subheader("Tidspunkter hvor noget ændrede sig")
aendringer = df[df["aendret_siden_sidste_tjek"].isin(["Ja", "Ukendt (første kørsel)"])]
st.dataframe(
    aendringer.drop(columns=[c for c in df.columns if c.endswith("_dato")]).sort_values("tjek_tidspunkt", ascending=False),
    use_container_width=True, hide_index=True,
)

# --- Hele loggen -----------------------------------------------------------
with st.expander("Hele loggen"):
    st.dataframe(
        df.drop(columns=[c for c in df.columns if c.endswith("_dato")]).sort_values("tjek_tidspunkt", ascending=False),
        use_container_width=True, hide_index=True,
    )
    st.download_button("Download CSV", LOG_FILE.read_bytes(), file_name="su_status_log.csv", mime="text/csv")

# --- Advarsel hvis felter mangler ------------------------------------------
tomme = [f for f in DATO_FELTER if seneste.get(f, "") == ""]
if tomme:
    st.warning(
        "Seneste kørsel kunne ikke læse: " + ", ".join(tomme) +
        ". su.dk kan have ændret layout – tjek det seneste snapshot i mappen `snapshots/` på GitHub."
    )

if SNAPSHOT_DIR.exists():
    st.caption(f"{len(list(SNAPSHOT_DIR.glob('*.html')))} snapshots gemt i repoet.")
