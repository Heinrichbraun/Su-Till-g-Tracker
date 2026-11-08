"""
Streamlit-app der viser data fra su_status_log.csv.
Fokus: Videregående uddannelser – hvornår ændrer tallene sig, og hvor mange dage rykker de?

Kør lokalt:   streamlit run app.py
Gratis hosting: Streamlit Community Cloud (se README).
"""

import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

LOG_FILE = Path(__file__).resolve().parent / "su_status_log.csv"
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# --- Personlige datoer (ret her, hvis noget ændrer sig) ---------------------
MIN_ANSOEGNING = pd.Timestamp(2025, 10, 10)   # datoen din ansøgning blev sendt
SU_KLIP_SLUT = pd.Timestamp(2027, 6, 1)       # hvornår du løber tør for SU-klip (juni 2027)

MAANEDER = {
    "januar": 1, "februar": 2, "marts": 3, "april": 4, "maj": 5, "juni": 6,
    "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "december": 12,
}
MAANEDSNAVNE = {nr: navn for navn, nr in MAANEDER.items()}

# Kun det felt der rammer mig: ansøgninger der kræver yderligere dokumentation.
# ("behandlet_til_videregaende" bliver stadig logget i CSV-filen, men vises ikke her.)
# kolonne i loggen -> titel
FELTER = {
    "yderligere_oplysninger_videregaende": "Ældste afventende sag",
}
RELEVANT_FELT = "yderligere_oplysninger_videregaende"


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


def fmt_dato(d):
    """Timestamp -> '10. oktober 2025'."""
    return f"{d.day}. {MAANEDSNAVNE[d.month]} {d.year}"


def i_dag():
    """Dagens dato i dansk tid (Streamlit Cloud kører i UTC)."""
    return pd.Timestamp(datetime.now(ZoneInfo("Europe/Copenhagen")).date())


def fmt_varighed(dage):
    """Antal dage -> '345 dage (ca. 49 uger)'."""
    dage = int(dage)
    return f"{dage} dage (ca. {round(dage / 7)} uger)"


def fmt_dage(v):
    """Formatér antal dage som '+7' / '-3' / '0' / '–'."""
    if pd.isna(v):
        return "–"
    v = int(v)
    return f"+{v}" if v > 0 else str(v)


def fmt_tempo(v):
    """Ændring i tempo: hvor mange dage mere/mindre de rykkede end ugen før."""
    if pd.isna(v):
        return "–"
    v = int(v)
    if v > 0:
        return f"▲ hurtigere (+{v})"
    if v < 0:
        return f"▼ langsommere ({v})"
    return "＝ samme tempo"


@st.cache_data(ttl=60)
def load_log(filstempel):
    """filstempel (filens ændringstid) gør, at cachen ugyldiggøres når loggen ændres."""
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
        dage = uger[kol + "_dato"].diff().dt.days
        out[f"{titel} – dage rykket"] = dage
        out[f"{titel} – tempo vs. forrige uge"] = dage.diff()
        out[f"{titel} – gns. seneste 4 uger"] = dage.rolling(4, min_periods=1).mean().round(1)
    return out


st.set_page_config(page_title="SU handicaptillæg – status", page_icon="📊", layout="wide")
st.title("📊 SU handicaptillæg – Videregående uddannelser")
st.caption("Data hentes automatisk fra su.dk tirsdag aften og onsdag morgen.")

df = load_log(LOG_FILE.stat().st_mtime if LOG_FILE.exists() else 0)

if df is None or df.empty:
    st.info("Der er endnu ikke logget nogen data. Kør workflowet på GitHub én gang, og genindlæs siden.")
    st.stop()

st.caption(f"Loggen indeholder {len(df)} tjek. Seneste linje: {df['tjek_tidspunkt'].iloc[-1]:%d-%m-%Y %H:%M}.")
ugetabel = uge_for_uge(df)
seneste = df.iloc[-1]

# --- Seneste tjek ----------------------------------------------------------
st.subheader("Seneste tjek")

# "Ændret siden sidst" ud fra det relevante felt (ikke fra CSV-kolonnen, som også
# tæller ændringer i felter der ikke vises her)
if len(df) < 2:
    relevant_aendret = "Første kørsel"
else:
    relevant_aendret = "Ja" if df[RELEVANT_FELT + "_dage"].iloc[-1] != 0 else "Nej"

st.write(
    f"**{seneste['ugedag']} {seneste['tjek_tidspunkt']:%d-%m-%Y kl. %H:%M}** "
    f"· su.dk angiver selv: *opdateret {seneste['side_opdateret'] or 'ukendt'}* "
    f"· ændret siden sidst: **{relevant_aendret}**"
)

for felt, titel in FELTER.items():
    delta = None
    if len(ugetabel) > 1:
        v = ugetabel[f"{titel} – dage rykket"].iloc[-1]
        if pd.notna(v):
            delta = f"{fmt_dage(v)} dage siden forrige uge"
    st.metric(titel, seneste[felt] or "–", delta=delta)

# --- Min ansøgning og SU-klip ----------------------------------------------
st.subheader("Min ansøgning og SU-klip")
idag = i_dag()
ældste = seneste["yderligere_oplysninger_videregaende_dato"]  # ældste sag der afventer ekstra dokumentation

# Gennemsnitligt tempo (dage rykket pr. uge) over de seneste op til 4 uger
tempo_serie = ugetabel["Ældste afventende sag – dage rykket"].dropna().tail(4)
tempo = tempo_serie.mean() if len(tempo_serie) else None

forventet = None
dage_til_ansoegning = None
if pd.notna(ældste):
    dage_til_ansoegning = (MIN_ANSOEGNING - ældste).days
    if dage_til_ansoegning > 0 and tempo is not None and tempo > 0:
        forventet = idag + timedelta(days=round(dage_til_ansoegning / tempo * 7))

m1, m2, m3 = st.columns(3)

with m1:
    if dage_til_ansoegning is None:
        st.metric("Afstand til din ansøgning", "–")
        st.caption("Kunne ikke læse datoen for ældste afventende sag.")
    elif dage_til_ansoegning > 0:
        st.metric("Afstand til din ansøgning", f"{dage_til_ansoegning} dage")
        st.caption(
            f"Ældste sag med ekstra dokumentation: **{fmt_dato(ældste)}**. "
            f"Din ansøgning: **{fmt_dato(MIN_ANSOEGNING)}**."
        )
    else:
        st.metric("Afstand til din ansøgning", "Nået")
        st.caption(
            f"Ældste sag med ekstra dokumentation er nu **{fmt_dato(ældste)}**, "
            f"altså på eller efter din ansøgningsdato ({fmt_dato(MIN_ANSOEGNING)}). "
            "Tjek din egen sag hos SU for at se, om den er afgjort."
        )

with m2:
    if forventet is not None:
        st.metric("Groft estimat: ansøgningsdato nået", fmt_dato(forventet))
        tempo_tekst = f"{tempo:.1f}".replace(".", ",")
        st.caption(
            f"Baseret på et gennemsnit på {tempo_tekst} dage pr. uge over de seneste "
            f"{len(tempo_serie)} uger."
        )
    elif dage_til_ansoegning is not None and dage_til_ansoegning <= 0:
        st.metric("Groft estimat: ansøgningsdato nået", "Allerede nået")
    else:
        st.metric("Groft estimat: ansøgningsdato nået", "–")
        if dage_til_ansoegning is not None:
            st.caption(
                "Kan ikke beregnes endnu. Det kræver mindst to uger i loggen, hvor datoen "
                "har rykket sig fremad."
            )

with m3:
    dage_til_klip = (SU_KLIP_SLUT - idag).days
    if dage_til_klip > 0:
        st.metric("Nedtælling til SU-klip løber ud", f"{dage_til_klip} dage")
        st.caption(f"Ca. {round(dage_til_klip / 7)} uger til {fmt_dato(SU_KLIP_SLUT)}.")
    else:
        st.metric("Nedtælling til SU-klip løber ud", "Nået")
        st.caption(f"Datoen {fmt_dato(SU_KLIP_SLUT)} er passeret.")

if forventet is not None:
    forskel = (SU_KLIP_SLUT - forventet).days
    if forskel >= 0:
        st.success(
            f"På nuværende tempo nås din ansøgningsdato ca. {fmt_varighed(forskel)} "
            f"**før** {fmt_dato(SU_KLIP_SLUT)}. Det er et groft estimat, tempoet svinger fra uge til uge."
        )
    else:
        st.warning(
            f"På nuværende tempo nås din ansøgningsdato ca. {fmt_varighed(-forskel)} "
            f"**efter** {fmt_dato(SU_KLIP_SLUT)}. Det er et groft estimat, tempoet svinger fra uge til uge."
        )

# --- Uge for uge -----------------------------------------------------------
st.subheader("Uge for uge – hvor mange dage har de rykket sig?")
fane_tabel, fane_graf = st.tabs(["Tabel", "Graf"])

with fane_tabel:
    vis = ugetabel.copy()
    for kol in [c for c in vis.columns if c.endswith("dage rykket")]:
        vis[kol] = vis[kol].map(fmt_dage)
    for kol in [c for c in vis.columns if "tempo vs." in c]:
        vis[kol] = vis[kol].map(fmt_tempo)
    for kol in [c for c in vis.columns if "gns." in c]:
        vis[kol] = vis[kol].map(lambda v: "–" if pd.isna(v) else f"{v:.1f}".replace(".", ","))
    st.dataframe(vis.sort_values("Uge", ascending=False), use_container_width=True, hide_index=True)
    st.caption(
        "Dage rykket: positivt tal = sagsbehandlingen er rykket frem. "
        "Tempo: ▲ = rykkede flere dage end ugen før, ▼ = færre dage. "
        "Første uge har ingen sammenligning, og tempo vises først fra tredje uge. "
        "Hvis en uge mangler i loggen, dækker tallet to uger."
    )

with fane_graf:
    graf = ugetabel.set_index("Uge")[[f"{t} – dage rykket" for t in FELTER.values()]]
    graf.columns = list(FELTER.values())
    graf = graf.dropna(how="all")
    if graf.empty:
        st.write("Der skal være mindst to uger i loggen, før grafen kan vises.")
    else:
        st.bar_chart(graf)
        st.caption("Højere søjle = de rykkede flere dage den uge.")

# --- Tidspunkter hvor noget ændrede sig ------------------------------------
st.subheader("Tidspunkter hvor noget ændrede sig")
# Kun rækker hvor det relevante felt rykkede sig (plus allerførste række)
maske = (df[RELEVANT_FELT + "_dage"].fillna(0) != 0) | (df.index == 0)
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
