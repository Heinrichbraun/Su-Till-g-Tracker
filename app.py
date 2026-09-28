"""
Streamlit-app der viser data fra su_status_log.csv.
Fokus: Videregående uddannelser – hvornår ændrer tallene sig, og hvor mange dage rykker de?

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

# kolonne i loggen -> (kort titel, titel til kolonne med dage)
FELTER = {
    "behandlet_til_videregaende": "Behandlet til",
    "yderligere_oplysninger_videregaende": "Ældste afventende sag",
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


def fmt_dage(v):
    """Formatér antal dage som '+7' / '-3' / '0' / '–'."""
    if pd.isna(v):
        return "–"
    v = int(v)
    return f"+{v}" if v > 0 else str(v)


@st.cache_data(ttl=300)
def load_log():
    if not LOG_FILE.exists():
        return None
    df = pd.read_csv(LOG_FILE, dtype=str).fillna("")
    df["tjek_tidspunkt"] = pd.to_datetime(df["tjek_tidspunkt"], errors="coerce")
    df = df.dropna(subset=["tjek_tidspunkt"]).sort_values("tjek_tidspunkt").reset_index(drop=True)
    for kol in FELTER:
        df[kol + "_dato"] = df[kol].apply(parse_dansk_dato)
        # Ændring i dage siden forrige logline
        df[kol + "_dage"] = df[kol + "_dato"].diff().dt.days
    return df


def uge_for_uge(df):
    """Én linje pr. kalenderuge (seneste tjek i ugen) + antal dage tallene har rykket sig."""
    iso = df["tjek_tidspunkt"].dt.isocalendar()
    d = df.assign(uge=iso["year"].astype(str) + "-U" + iso["week"].astype(str).str.zfill(2))
    uger = d.groupby("uge", sort=True).tail(1).reset_index(drop=True)  # sidste tjek i hver uge
    out = pd.DataFrame({"Uge": uger["uge"], "Sidst tjekket": uger["tjek_tidspunkt"].dt.strftime("%d-%m-%Y %H:%M")})
    for kol, titel in FELTER.items():
        out[titel] = uger[kol]
        out[f"{titel} – dage rykket"] = uger[kol + "_dato"].diff().dt.days
    return out


st.set_page_config(page_title="SU handicaptillæg – status", page_icon="📊", layout="wide")
st.title("📊 SU handicaptillæg – Videregående uddannelser")
st.caption("Data hentes automatisk fra su.dk tirsdag aften og onsdag morgen.")

df = load_log()

if df is None or df.empty:
    st.info("Der er endnu ikke logget nogen data. Kør workflowet på GitHub én gang, og genindlæs siden.")
    st.stop()

ugetabel = uge_for_uge(df)
seneste = df.iloc[-1]

# --- Seneste tjek ----------------------------------------------------------
st.subheader("Seneste tjek")
st.write(
    f"**{seneste['ugedag']} {seneste['tjek_tidspunkt']:%d-%m-%Y kl. %H:%M}** "
    f"· su.dk angiver selv: *opdateret {seneste['side_opdateret'] or 'ukendt'}* "
    f"· ændret siden sidst: **{seneste['aendret_siden_sidste_tjek']}**"
)

kol1, kol2 = st.columns(2)
for kol, (felt, titel) in zip((kol1, kol2), FELTER.items()):
    delta = None
    if len(ugetabel) > 1:
        v = ugetabel[f"{titel} – dage rykket"].iloc[-1]
        if pd.notna(v):
            delta = f"{fmt_dage(v)} dage siden forrige uge"
    kol.metric(titel, seneste[felt] or "–", delta=delta)

# --- Uge for uge -----------------------------------------------------------
st.subheader("Uge for uge – hvor mange dage har de rykket sig?")
vis = ugetabel.copy()
for kol in [c for c in vis.columns if c.endswith("dage rykket")]:
    vis[kol] = vis[kol].map(fmt_dage)
st.dataframe(vis.sort_values("Uge", ascending=False), use_container_width=True, hide_index=True)
st.caption("Positivt tal = sagsbehandlingen er rykket frem. Første uge har ingen sammenligning.")

# --- Tidspunkter hvor noget ændrede sig ------------------------------------
st.subheader("Tidspunkter hvor noget ændrede sig")
maske = df["aendret_siden_sidste_tjek"].isin(["Ja", "Ukendt (første kørsel)"])
aendringer = pd.DataFrame({
    "Tidspunkt": df["tjek_tidspunkt"].dt.strftime("%d-%m-%Y %H:%M"),
    "Ugedag": df["ugedag"],
})
for kol, titel in FELTER.items():
    aendringer[titel] = df[kol]
    aendringer[f"{titel} – dage rykket"] = df[kol + "_dage"].map(fmt_dage)
aendringer = aendringer[maske].iloc[::-1]
if aendringer.empty:
    st.write("Ingen ændringer registreret endnu.")
else:
    st.dataframe(aendringer, use_container_width=True, hide_index=True)

# --- Hele loggen -----------------------------------------------------------
with st.expander("Hele loggen (alle tjek)"):
    raa = df.drop(columns=[c for c in df.columns if c.endswith("_dato") or c.endswith("_dage")])
    st.dataframe(raa.iloc[::-1], use_container_width=True, hide_index=True)
    st.download_button("Download CSV", LOG_FILE.read_bytes(), file_name="su_status_log.csv", mime="text/csv")

# --- Advarsel hvis felter mangler ------------------------------------------
tomme = [f for f in FELTER if seneste.get(f, "") == ""]
if tomme:
    st.warning(
        "Seneste kørsel kunne ikke læse: " + ", ".join(tomme) +
        ". su.dk kan have ændret layout – tjek det seneste snapshot i mappen `snapshots/` på GitHub."
    )

if SNAPSHOT_DIR.exists():
    st.caption(f"{len(list(SNAPSHOT_DIR.glob('*.html')))} snapshots gemt i repoet.")
