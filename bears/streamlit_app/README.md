# Wildlife Movement Analysis System

Eine Streamlit-Anwendung, die drei bisher getrennte Teilsysteme der
Bärenforschung auf **einer gemeinsamen Karte** zusammenführt und um zwei
Experimente zur Bewegungssimulation erweitert.

> **Hinweis zur Sprache:** Quelltext und Benutzeroberfläche sind
> vollständig auf Englisch. Diese README und `ANPASSUNGEN.md` sind bewusst
> auf Deutsch gehalten; sie richten sich an die Betreuung, nicht an die
> Anwendung.

---

## 1. Was das System tut

| Teilsystem | Inhalt |
|---|---|
| **Japan Bear Deterrent** | Abschreckungsgeräte, Kamerastandorte, Kamerabilder, frei gezeichnete Marker und Gebiete (Vorarbeit Marcel Lorenz) |
| **Carpathian Bears** | GPS-Halsbanddaten von 13 Braunbären in den rumänischen Karpaten, 59 997 Ortungen von August 2011 bis Juli 2015 |
| **Bewegungssimulation** | Schritt-Simulation auf Basis empirischer Schrittlängen (Vorarbeit Fabian Bräu) |

Dazu zwei Analyse-Seiten:

**Experiments** — Animation eines Bären an einem Tag. Die echte GPS-Spur und
mehrere simulierte Bären laufen auf derselben Zeitachse nebeneinander. Jeder
simulierte Pfad ist eine Zufallsziehung aus dem Modell, keine Vorhersage;
über einen Seed ist jeder Lauf exakt reproduzierbar.

**Japan Experiment** — Übertragung der in Rumänien gemessenen
Bewegungsmuster auf die japanische Kameralandschaft. Simulierte Bären
starten an einem echten Foto-Ereignis; echte Auslösezeiten erscheinen als
rote Marken auf derselben Zeitleiste. Darunter eine aggregierte Statistik
über viele Läufe (Überlappungskoeffizient mit Bootstrap-Konfidenzintervall).

---

## 2. Installation

Voraussetzung: **Python 3.14.3** (getestet unter Windows 11; ältere 3.1x
sollten laufen, sind aber nicht geprüft).

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # Linux, macOS

pip install -r requirements.txt
```

`requirements-dev.txt` wird **nicht** benötigt. Darin stehen nur Pakete für
Module der ursprünglichen Simulation, die die Anwendung nicht lädt
(`hdbscan`, `scikit-learn`, `scipy`, `dash`, `folium`). Begründung in
`ANPASSUNGEN.md`, Punkt 7.

## 3. Starten

```bash
streamlit run map.py
```

Die Anwendung öffnet sich im Browser. Links in der Seitenleiste stehen die
Filter, die Layer werden direkt **auf der Karte** oben links an- und
abgehakt. Die beiden Experiment-Seiten erreicht man über die
Seitennavigation.

---

## 4. Abhängigkeiten zur Laufzeit

| Was | Wofür | Ohne? |
|---|---|---|
| **OTH-VPN** | MariaDB `ursus`: Kamerabilder, Foto-Zeitstempel, Marker und Gebiete | Anwendung startet trotzdem; Carpathian-Daten kommen aus CSV, Simulation läuft vollständig, nur die DB-Inhalte fehlen |
| **Internet** | Kartenkacheln (Esri, OpenFreeMap, Carto), Höhenmodell (Mapterhorn) | Karte bleibt leer bzw. ohne 3D; die Simulation selbst braucht kein Internet |
| **Overpass API** | Nur beim Vorabladen der Geländedaten | Siehe Abschnitt 5 |

Die Anwendung ist durchgehend so gebaut, dass eine fehlende Verbindung zu
einer **Warnung** führt und nicht zu einem Absturz.

---

## 5. Geländedaten vorab laden

Die Geländegewichtung der Simulation bewertet OpenStreetMap-Daten. Würde
sie bei jedem Simulationsschritt live abgefragt, wären das tausende
Overpass-Anfragen pro Lauf. Stattdessen wird das Kameragebiet **einmalig**
heruntergeladen und lokal gerastert:

```bash
python tools/prefetch_terrain.py
```

Ergebnis: `bear_simulation/data/terrain_cache.db` (rund 5 MB, etwa 20 000
Rasterzellen à 150 m). Danach stellt die Simulation in diesem Gebiet
**keine** Internet-Anfragen mehr.

Falls Python die Overpass-Server nicht erreicht, ein Browser aber schon:

```bash
python tools/prefetch_terrain.py --print-query
# Abfrage auf https://overpass-turbo.eu ausführen,
# "Export" -> "Rohdaten" als JSON speichern, dann:
python tools/prefetch_terrain.py --from-file terrain.json
```

Der Schreibvorgang ist atomar: erst in eine Kopie, dann `PRAGMA
quick_check`, dann ersetzen. Ein Abbruch lässt die alte, funktionierende
Datei unangetastet.

**Bekannte Einschränkung:** Das vorberechnete Gebiet umfasst die
Kamerastandorte plus 5 km Puffer. Bei Simulationsläufen über 48 Stunden
verlassen Bären dieses Gebiet, und die Geländegewichtung schaltet sich dann
still ab. Für belastbare Läufe über 24 Stunden hinaus muss der Puffer
vergrößert werden (`--buffer-km`).

---

## 6. Vor dem Deployment an der OTH

Die folgenden Punkte sind **vor** dem Ausrollen zu klären. Sie sind nach
Dringlichkeit sortiert.

### 6.1 Zugangsdaten aus dem Quelltext nehmen — kritisch

Die MariaDB-Zugangsdaten standen bisher im Klartext in
`wildlife_db_mariadb.py` und liegen damit in der Git-Historie. Das Modul
liest sie jetzt aus Umgebungsvariablen und fällt nur dann auf die alten
Werte zurück, wenn keine gesetzt sind:

```bash
set WILDLIFE_DB_HOST=...
set WILDLIFE_DB_PORT=3306
set WILDLIFE_DB_USER=...
set WILDLIFE_DB_PASSWORD=...
set WILDLIFE_DB_NAME=ursus
```

Zu erledigen:

1. Auf dem Zielsystem die Variablen setzen (oder `.streamlit/secrets.toml`
   nutzen, bereits in `.gitignore`).
2. Die Rückfallwerte in `wildlife_db_mariadb.py` entfernen, sobald das
   steht — sonst bleibt das Passwort im Quelltext.
3. **Das Passwort ändern.** Es war im Repository sichtbar und muss als
   kompromittiert gelten, auch nach dem Entfernen aus dem Code: die
   Git-Historie enthält es weiterhin.

### 6.2 Netzwerkfreigaben prüfen

Der Server braucht ausgehenden Zugriff auf:

| Ziel | Zweck | Ohne |
|---|---|---|
| `172.20.39.9:3306` | MariaDB | keine Bilder, Marker, Foto-Zeitstempel |
| `server.arcgisonline.com`, `tiles.openfreemap.org`, `basemaps.cartocdn.com` | Kartenkacheln | Karte bleibt grau |
| `tiles.mapterhorn.com` | Höhenmodell für 3D | 3D-Schalter meldet "nicht erreichbar", 2D funktioniert |
| `overpass-api.de` u. a. | nur für `tools/prefetch_terrain.py` | nicht nötig, wenn der Cache mitgeliefert wird |

Die Kartenkacheln lädt **der Browser des Nutzers**, nicht der Server. Wenn
der Server abgeschottet ist, die Clients aber Internet haben, funktionieren
die Karten trotzdem.

### 6.3 Datendateien mitliefern

Diese Dateien sind für den Betrieb nötig, stehen aber teilweise in
`.gitignore` und kommen deshalb **nicht** automatisch mit:

| Datei / Ordner | Größe | Status |
|---|---|---|
| `bear_simulation/data/database.db` | 4,4 MB | im Repository |
| `bear_simulation/data/terrain_cache.db` | 5,5 MB | **ignoriert** — mitkopieren oder neu erzeugen |
| `data/animal_data/carpathian_bears/*.csv` | ca. 9 MB | im Repository, dient als Fallback ohne DB |
| `data/` gesamt | ca. 70 MB | enthält Bilder und Gebietsdaten |
| `bear_simulation/data/terrain_prefetch_raw/` | 29 MB | **ignoriert**, nur zum Neuerzeugen des Caches nötig |

Ohne `terrain_cache.db` läuft die Anwendung, aber die Geländegewichtung
schaltet sich beim ersten Lauf ab (mit Hinweis in der Oberfläche).

### 6.4 Streamlit-Konfiguration

Für den Serverbetrieb in `.streamlit/config.toml`:

```toml
[server]
headless = true
port = 8501
address = "0.0.0.0"
enableCORS = false
maxUploadSize = 50

[browser]
gatherUsageStats = false
```

**Wichtig bei Betrieb hinter einem Reverse Proxy:** Die Karte schreibt
ihren Zustand (Kartenausschnitt, Zoom, sichtbare Layer) in die URL des
umgebenden Fensters und löst beim Speichern neuer Marker eine echte
Navigation aus. Das funktioniert nur, wenn iframe und Seite **dieselbe
Origin** haben. Bei einem Proxy mit abweichender Domain schlägt das fehl —
die Karte bleibt nutzbar, aber Zustandserhalt und das Zeichnen neuer
Marker funktionieren nicht mehr. Vor dem Ausrollen testen.

### 6.5 Funktionsprüfung nach dem Ausrollen

```bash
python tests/smoke_test.py
```

16 Prüfungen, läuft ohne Datenbank und ohne Netzwerk. Erwartete Ausgabe:
`16 of 16 checks passed`. Der Test vergleicht unter anderem Hash-Werte der
simulierten Pfade und schlägt an, wenn sich das Verhalten der Simulation
verändert hat.

Danach manuell prüfen: Hauptkarte lädt, beide Experiment-Seiten laden, ein
Simulationslauf startet, die 3D-Schalter reagieren.

### 6.6 Nicht benötigt

- `hdbscan` und `scikit-learn` werden **nicht** gebraucht. Die
  Integrationsschicht umgeht die Cluster-Analyse der ursprünglichen
  Simulation bewusst (`ANPASSUNGEN.md`, Punkt 7).
- Der Ordner `_archiv/` enthält einmalige Migrations- und Prüfskripte sowie
  abgelöste Artefakte. Er wird nicht ausgeliefert.

---

## 7. Projektstruktur

```
streamlit_app/
  map.py                        Einstiegspunkt, gemeinsame Hauptkarte
  pages/
    2_Experiments.py            Animation echt vs. simuliert (Karpaten)
    3_Japan_Experiment.py       Übertragung auf die Japan-Kameras

  maplibre_component.py         Hauptkarte (MapLibre, Layer, Zeichnen)
  animation_component.py        Animationskarte Karpaten
  japan_map_component.py        Animationskarte Japan

  carpathian_bears.py           GPS-Daten, DB-first mit CSV-Fallback
  japan_deterrents.py           Geräte, Bilder, Marker, Gebiete
  wildlife_db_mariadb.py        Datenzugriffsschicht MariaDB
  new_images_checker.py         Erkennung neuer Bilder
  status_widget.py              Statusanzeige in der Seitenleiste
  geojson_table_helper.py       GeoJSON zu Tabelle

  sync_simulation.py            Synchrone echte und simulierte Bewegung
  japan_comparison.py           Simulation ab Kamerastandort, Richtungswahl
  activity_overlap.py           Tagesrhythmus-Vergleich, Bootstrap
  terrain_cache.py              Lokaler OpenStreetMap-Geländecache

  import_bfn_wolf_lynx.py       Wolf- und Luchsdaten vom BfN, eigenstaendig
  import_gbif_bears.py          Bärensichtungen aus GBIF, eigenstaendig
                                Beide sind nicht mehr an die Karte
                                angebunden: sie lagen ausserhalb des
                                Themas der Arbeit. Als Skript ausfuehrbar.

  bear_simulation/              Vorarbeit Fabian Bräu, unverändert,
                                plus eigene Integrationsschicht __init__.py
  tools/prefetch_terrain.py     Geländedaten einmalig vorab laden
  tests/smoke_test.py           Regressionstest, 16 Prüfungen
  tests/direction_distribution_test.py
                                Messungen zur Richtungswahl
  docs/                         Referenzliteratur (nicht im Repository)
  _archiv/                      abgelegte Skripte, nicht ausliefern

  ANPASSUNGEN.md                Abweichungen von der Vorarbeit, mit Messungen
```

### Konventionen für Konsolenausgaben

- `[ok]`, `[note]`, `[warning]`, `[error]` für Ausgaben von Skripten
- `[modulname]` für Diagnosemeldungen einzelner Module, etwa
  `[terrain_cache]` oder `[japan_comparison]`

---

## 8. Hinweise zur Interpretation

Zwei Punkte, die bei der Beurteilung der Ergebnisse zählen:

**Simulierte Pfade sind keine Vorhersagen.** Jeder Pfad ist eine
Zufallsziehung aus dem Bewegungsmodell. Deshalb werden standardmäßig
mehrere gleichzeitig gezeichnet: aussagekräftig ist ihre Streuung, nicht
die einzelne Linie.

**Artunterschied.** Die japanischen Kameras stehen im Verbreitungsgebiet
des Asiatischen Schwarzbären (*Ursus thibetanus*), das Bewegungsmodell
stammt vom Europäischen Braunbären (*Ursus arctos*). Das ist eine bewusste
methodische Vereinfachung und keine Gleichsetzung.

Weitere Einschränkungen, jeweils mit Messwerten, stehen in
`ANPASSUNGEN.md`.

---

## 9. Vorarbeiten

Das System baut auf drei studentischen Arbeiten auf:

- **Marcel Lorenz** — Japan Bear Deterrent System
- **Fabian Bräu** — Bewegungssimulation Karpaten (`bear_simulation/`)
- **Anthony Lelchat** — Bildextraktion aus E-Mail-Postfächern

Die Richtungswahl der Simulation übernimmt das Verfahren aus
J. Geyer, M. Melzer, J. Dünnweber, A. Sarkar, *Human Step Movement
Imitation for Training Privacy-Aware Intelligent Environments*, IEEE,
Abschnitt III-B, Formel (1). Details und Abgrenzung in `ANPASSUNGEN.md`,
Punkt 8.
