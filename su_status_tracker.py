#!/usr/bin/env python3
"""
su_status_tracker.py

Henter status-siden for handicaptillæg på su.dk og logger de vigtigste
datoer/tal i en CSV-fil, så du kan følge udviklingen over tid.

Kør scriptet manuelt:
    python3 su_status_tracker.py

Eller sæt det til at køre automatisk med cron / Windows Aftaleplanlægning
(se README_su_status_tracker.md for vejledning).

Afhængigheder:
    pip install requests beautifulsoup4
"""

import csv
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

# GitHub-serverne kører i UTC, så vi angiver dansk tid eksplicit
TZ = ZoneInfo("Europe/Copenhagen")

URL = "https://www.su.dk/handicaptillaeg/status-paa-behandling-af-sager-handicaptillaeg"

# Filen logges i samme mappe som scriptet ligger i
LOG_FILE = Path(__file__).resolve().parent / "su_status_log.csv"

# Mappe hvor et rå HTML-snapshot af siden gemmes hver gang (til fejlfinding,
# hvis su.dk ændrer sidens layout og udtrækket holder op med at virke)
SNAPSHOT_DIR = Path(__file__).resolve().parent / "snapshots"

# De felter, der reelt afspejler indholdet på siden. Bruges til at afgøre,
# om noget har ændret sig siden sidste tjek.
SCRAPE_FIELDS = [
    "side_opdateret",              # datoen su.dk selv angiver ("opdateret X")
    "behandlet_til_videregaende",  # "Vi har behandlet ansøgninger modtaget på eller før" - Videregående uddannelser
    "behandlet_til_erhverv",       # samme, men Erhvervsuddannelser
    "yderligere_oplysninger_videregaende",  # ældste sag der afventer, hvor der er indhentet mere info - Videregående
    "yderligere_oplysninger_erhverv",       # samme - Erhvervsuddannelser
    "klagesager_til_og_med",       # måned for klagesager der behandles
]

# Kolonneoverskrifter i loggen
FIELDNAMES = [
    "tjek_tidspunkt",              # hvornår scriptet blev kørt
    "ugedag",                      # Tirsdag / Onsdag / osv.
    *SCRAPE_FIELDS,
    "aendret_siden_sidste_tjek",   # Ja / Nej / Ukendt (første kørsel) — sammenlignet med forrige logline
]

UGEDAGE_DA = {
    "Monday": "Mandag",
    "Tuesday": "Tirsdag",
    "Wednesday": "Onsdag",
    "Thursday": "Torsdag",
    "Friday": "Fredag",
    "Saturday": "Lørdag",
    "Sunday": "Søndag",
}


def hent_html(url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (kompatibel; su-status-tracker/1.0; privat logning)"
    }
    resp = requests.get(url, headers=headers, timeout=20)
    resp.raise_for_status()
    return resp.text


def find_table_value(soup: BeautifulSoup, row_label: str) -> str:
    """
    Finder værdien i en tabelrække, hvor første celle matcher row_label
    (fx "Videregående uddannelser"), og returnerer indholdet af anden celle.
    """
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            first = cells[0].get_text(strip=True)
            if first == row_label:
                return cells[1].get_text(strip=True)
    return ""


def find_opdateret_dato(soup: BeautifulSoup) -> str:
    """
    Finder teksten i overskriften "Status på sagsbehandlingen - opdateret DD. måned ÅÅÅÅ"
    """
    heading = soup.find(string=re.compile(r"Status på sagsbehandlingen", re.IGNORECASE))
    if heading:
        m = re.search(r"opdateret\s+(.+)", heading, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def find_klagesager(soup: BeautifulSoup) -> str:
    """
    Finder værdien i tabellen for klagesager (kun én kolonne/én række med data).
    """
    heading = soup.find(
        lambda tag: tag.name in ("h2", "h3") and "Sagsbehandlingstid på klager" in tag.get_text()
    )
    if not heading:
        return ""
    table = heading.find_next("table")
    if not table:
        return ""
    row = table.find_all("tr")
    for r in row:
        cells = r.find_all(["td", "th"])
        if cells:
            text = cells[-1].get_text(strip=True)
            # Spring selve overskriftsrækken over
            if text and "Vi er i gang med" not in text:
                return text
    return ""


def gem_snapshot(html: str) -> Path:
    """
    Gemmer den rå HTML som et snapshot med tidsstempel i filnavnet, så vi har
    et arkiv at kigge i, hvis su.dk ændrer sidens opbygning og udtrækket
    begynder at fejle.
    """
    SNAPSHOT_DIR.mkdir(exist_ok=True)
    filnavn = datetime.now(TZ).strftime("%Y-%m-%d_%H%M") + ".html"
    sti = SNAPSHOT_DIR / filnavn
    sti.write_text(html, encoding="utf-8")
    return sti


def hent_data() -> dict:
    html = hent_html(URL)
    gem_snapshot(html)
    soup = BeautifulSoup(html, "html.parser")

    nu = datetime.now(TZ)
    data = {
        "tjek_tidspunkt": nu.strftime("%Y-%m-%d %H:%M"),
        "ugedag": UGEDAGE_DA.get(nu.strftime("%A"), nu.strftime("%A")),
        "side_opdateret": find_opdateret_dato(soup),
        "behandlet_til_videregaende": find_table_value(soup, "Videregående uddannelser"),
        "behandlet_til_erhverv": find_table_value(soup, "Erhvervsuddannelser"),
        "klagesager_til_og_med": find_klagesager(soup),
    }

    # De to tabeller for "Videregående uddannelser" / "Erhvervsuddannelser" har samme
    # rækkenavn i to forskellige tabeller (behandlet-dato og yderligere-oplysninger-dato).
    # find_table_value finder kun den første forekomst, så vi finder den anden manuelt.
    all_matches_vgu = [
        cells[1].get_text(strip=True)
        for row in soup.find_all("tr")
        for cells in [row.find_all(["td", "th"])]
        if len(cells) >= 2 and cells[0].get_text(strip=True) == "Videregående uddannelser"
    ]
    all_matches_eud = [
        cells[1].get_text(strip=True)
        for row in soup.find_all("tr")
        for cells in [row.find_all(["td", "th"])]
        if len(cells) >= 2 and cells[0].get_text(strip=True) == "Erhvervsuddannelser"
    ]

    data["yderligere_oplysninger_videregaende"] = all_matches_vgu[1] if len(all_matches_vgu) > 1 else ""
    data["yderligere_oplysninger_erhverv"] = all_matches_eud[1] if len(all_matches_eud) > 1 else ""

    return data


def hent_seneste_logrow() -> dict | None:
    """
    Læser den seneste linje i loggen (hvis loggen findes), så vi kan
    sammenligne med det, vi lige har hentet.
    """
    if not LOG_FILE.exists():
        return None
    with LOG_FILE.open("r", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows[-1] if rows else None


def tjek_aendring(data: dict, forrige: dict | None) -> str:
    """
    Sammenligner de faktiske indholdsfelter (SCRAPE_FIELDS) med den seneste
    linje i loggen. Returnerer "Ja", "Nej" eller "Ukendt (første kørsel)".

    Dette er kernen i "tjek om det er ændret siden sidst": hvis su.dk
    plejer at opdatere om tirsdagen, men vi tirsdag aften ser "Nej"
    (uændret siden sidste tjek), kan det skyldes, at de er blevet
    forsinkede med opdateringen. Onsdag morgens tjek vil så typisk vise
    "Ja", når opdateringen er faldet på plads.
    """
    if forrige is None:
        return "Ukendt (første kørsel)"
    aendret = any(data.get(felt, "") != forrige.get(felt, "") for felt in SCRAPE_FIELDS)
    return "Ja" if aendret else "Nej"


def gem_i_log(data: dict) -> None:
    fil_findes = LOG_FILE.exists()
    with LOG_FILE.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        if not fil_findes:
            writer.writeheader()
        writer.writerow(data)


def main():
    # Læs seneste linje FØR vi tilføjer en ny, så vi kan sammenligne
    forrige = hent_seneste_logrow()

    try:
        data = hent_data()
    except requests.RequestException as e:
        print(f"Fejl ved hentning af siden: {e}", file=sys.stderr)
        sys.exit(1)

    manglende = [k for k in SCRAPE_FIELDS if not data.get(k)]
    if manglende:
        print(
            "Advarsel: kunne ikke finde værdi for: " + ", ".join(manglende) +
            " — su.dk kan have ændret sidens opbygning.",
            file=sys.stderr,
        )

    data["aendret_siden_sidste_tjek"] = tjek_aendring(data, forrige)

    gem_i_log(data)
    print(f"Logget kl. {data['tjek_tidspunkt']} ({data['ugedag']}):")
    for k in [*SCRAPE_FIELDS, "aendret_siden_sidste_tjek"]:
        print(f"  {k}: {data[k]}")

    if data["ugedag"] == "Tirsdag" and data["aendret_siden_sidste_tjek"] == "Nej":
        print(
            "\nBemærk: Siden er IKKE ændret siden sidste tjek. Da su.dk "
            "normalt opdaterer om tirsdagen, kan de være forsinkede — "
            "onsdagens tjek vil afklare det."
        )
    elif data["ugedag"] == "Onsdag" and data["aendret_siden_sidste_tjek"] == "Ja":
        print(
            "\nBemærk: Siden er ændret siden i går (tirsdag) — su.dk var "
            "altså forsinkede med ugens opdatering, men den er nu faldet på plads."
        )
    elif data["ugedag"] == "Onsdag" and data["aendret_siden_sidste_tjek"] == "Nej":
        print(
            "\nBemærk: Siden er STADIG ikke ændret onsdag morgen. "
            "Ugens opdatering er enten ikke kommet endnu, eller også er "
            "der reelt ingen ændring i tallene denne uge."
        )

    print(f"\nGemt i: {LOG_FILE}")
    print(f"Snapshot gemt i: {SNAPSHOT_DIR}")


if __name__ == "__main__":
    main()
