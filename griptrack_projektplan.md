# GripTrack – No-Hang/Block-Pull Tracker mit Performance-Korrelation


---

## 1. Projektidee

Eine Web-App zum strukturierten Loggen von Block-Pull-/No-Hang-Trainingseinheiten
(Fingerkraft-Training ohne Hangboard, Gewicht wird vom Boden gehoben statt
Körpergewicht zu hängen) sowie von Kletter-Sends (Grad, Datum). Das System:

- speichert Trainings- und Klettern-Daten strukturiert in SQL,
- bietet eine selbst gebaute REST-API zum Eintragen/Abrufen der Daten,
- berechnet Trends (Kraftzuwachs über Zeit), Plateau-Signale und optional die
  Korrelation zwischen Block-Pull-Kraft (% Körpergewicht) und Klettergrad,
- zeigt das alles in einem Dashboard.

### Warum dieses Projekt?

- Deckt alle gewünschten Lernziele ab: SQL, REST-API, Frontend, Data Science
- Du bist selbst Teil der Zielgruppe → einfache, echte Nutzervalidierung
  (Boulderhalle/Crew) – genau das "klein anfangen, mit Nutzern sprechen"-Prinzip
- Bestehende Tools (Force Board, Frez, Tindeq, Crimpd) fokussieren auf
  **Hangboard** oder **sensorgebundenes** Training. Lattice Training hat die
  Kraft-zu-Grad-Korrelation ausführlich für Fingerboard-Hangs erforscht
  (R = 0.704, R² = 0.496 zwischen 7-Sek-Max-Hang %BW und Bouldergrad), aber
  nicht für sensorfreies Block-Pull-Training. Genau das ist die Nische:
  ein einfaches, kostenloses, sensorfreies Tool für eine Trainingsform, für die
  es noch keine systematische öffentliche Datenbasis gibt.
- **Wichtig für die Positionierung:** Nicht behaupten, Lattice's Forschung zu
  widerlegen oder zu ersetzen – Lattice's Methodik transparent als Referenzrahmen
  nutzen und auf einen anderen, bisher nicht abgedeckten Trainingsfall anwenden.
  Der Wert des Projekts liegt im **Tool selbst**, nicht im Forschungsanspruch.

---

## 2. Tech-Stack

| Komponente | Wahl | Begründung |
|---|---|---|
| Backend/API | **Python + FastAPI** | Automatische OpenAPI-Docs, Pydantic-Validierung – ideal zum REST-Lernen |
| Datenbank | **SQLite** (Start) → optional Postgres (Railway/Render/Supabase) später | Niedrige Einstiegshürde, später Cloud-fähig |
| Frontend | **Eigenes HTML/CSS/Vanilla-JS, mobile-first** | Volle Kontrolle über responsives Design – entscheidend für die Eingabe direkt in der Boulderhalle (kein Laptop verfügbar); kein React/Build-Tooling nötig für diesen Umfang |
| Data Science | **pandas, scikit-learn, plotly** | Zeitreihen-Trend, einfache Regression, Visualisierung |
| Hosting | **Beliebiger Static-Host** (z.B. Render/Netlify/GitHub Pages) für Frontend + **Railway/Render** (API) | Kostenlose Tiers, echter Link statt "läuft nur lokal" |

**Wichtige Architektur-Entscheidung:** Das Frontend spricht **nicht direkt mit der
Datenbank**, sondern ausschließlich über HTTP (fetch-Aufrufe) mit der eigenen
FastAPI. So entsteht eine echte dreistufige Architektur (Frontend ⇄ REST-API ⇄
SQL-DB), die den Lerneffekt für REST-APIs erzwingt statt ihn zu umgehen.

**Warum mobile-first wichtig ist:** Der Kern-Use-Case (Gewicht/Reps zwischen
Sets in der Halle eintragen) passiert praktisch nie am Laptop. Ein eigenes,
schlankes HTML/JS-Frontend mit großen Touch-Targets und einfachen Formularen
löst das direkt, ohne auf ein für Desktop-Dashboards gebautes Tool wie
Streamlit angewiesen zu sein, das mobile nur mittelmäßig funktioniert.

**Bewusst NICHT verfolgt (für den MVP):**
- Vollständige PWA mit Service Worker/Offline-Support (Zeitfresser ohne Bezug
  zu den Kernlernzielen) – ein minimales `manifest.json` für "Zum Homescreen
  hinzufügen" ist als kleiner Stretch Goal in Monat 4 vermerkt
- React/Vue oder anderes Frontend-Framework (unnötiger Lernaufwand für den
  Umfang dieses Projekts; Vanilla JS reicht völlig)
- Bluetooth-/Sensor-Hardware-Integration (zusätzliches technisches Risiko, nicht
  Teil der Lernziele)

---

## 3. Trainingslogik (Domänenmodell)

### Session-Struktur

Fester Warmup/Ramp-Ablauf, nur Work-Sets werden gespeichert:

1. Warmup: 8 Reps @ ~50% Max (nicht gespeichert)
2. Ramp: 5 Reps @ ~65% Max (nicht gespeichert)
3. Ramp: 5 Reps @ ~80% Max (nicht gespeichert)
4. Ramp: 3–5 Reps @ ~90% Max (nicht gespeichert)
5. **Work-Sets: 3+ Sets, 5 Reps @ 100% Max** ← das wird getrackt

Für Warmup/Ramp-Sets schlägt die App ein plattengerundetes Gewicht vor;
Nutzer tippt "Fertig" und macht weiter – kein Eintragen von Reps/Gewicht nötig.

### Sonstige Spezifikationen

- **Hände:** unabhängig getrackt (ggf. unterschiedliche Max-Gewichte je Hand)
- **Reihenfolge der Hände:** konfigurierbare Einstellung (abwechselnd oder sequenziell)
- **Einheiten:** kg/lbs wählbar, kg als Standard
- **Plattenrundung:** vorgeschlagene Gewichte auf normale Plattenlayouts runden
  (eigenes Platten-Inventar als spätere Ausbaustufe)
- **Testing-Session:** zum Festlegen/Zurücksetzen des Max-Gewichts (Details später)

### Progressionspfade — als spätere Ausbaustufe, NICHT Teil des MVP

Diese drei Pfade sind konzeptionell festgehalten, werden aber erst nach dem MVP
gebaut, um den Zeitplan realistisch zu halten:

1. **Set-Progression:** Reps fix bei 5, pro Woche ein Work-Set mehr (3→5→7…)
2. **Gewichts-Progression:** Sets fix, Gewicht steigt pro Woche (rechnet auch
   Ramp/Warmup-Gewichte neu)
3. **Advanced-Progression:** 3. Work-Set geht bis zum Failure → erreichte Reps
   werden neues Ziel für alle 3 Sets in der nächsten Session, bis 3×12 erreicht,
   dann Gewicht hoch und Reps zurück auf 3–5

Im MVP wird stattdessen einfach **eine feste Anzahl Work-Sets mit manueller
Gewichtseingabe** geloggt – die Progressionslogik kommt, wenn Zeit übrig ist
(siehe Monat 4 / "Stretch Goals").

---

## 4. Datenmodell (SQL)

```sql
-- Nutzer
users (
  id            INTEGER PRIMARY KEY,
  name          TEXT,
  bodyweight_kg REAL,
  created_at    TIMESTAMP
)

-- Trainingseinheiten (nur Work-Sets)
sessions (
  id          INTEGER PRIMARY KEY,
  user_id     INTEGER REFERENCES users(id),
  date        DATE,
  hand        TEXT,        -- 'left' / 'right'
  grip_type   TEXT,        -- z.B. 'half_crimp', 'open_hand'
  edge_mm     INTEGER,
  weight_kg   REAL,
  reps        INTEGER,
  set_number  INTEGER,
  rpe         INTEGER       -- gefühlte Anstrengung, optional
)

-- Kletter-Sends
climbs (
  id        INTEGER PRIMARY KEY,
  user_id   INTEGER REFERENCES users(id),
  date      DATE,
  grade     TEXT,
  style     TEXT           -- z.B. 'flash', 'redpoint'
)
```

Bewusst simpel gehalten (3 Tabellen), damit der Fokus auf JOIN-/Aggregations-
Logik liegt (z.B. "letzte Session pro Nutzer pro Grifftyp", "Kraft-Trend über
Zeit pro Hand") statt auf Schema-Komplexität.

---

## 5. 4-Monats-Zeitplan

### Monat 1 – SQL- & REST-Grundlagen + Datenpipeline

**Woche 1–2: SQL von Grund auf**
- Konzepte: Tabellen, Primary/Foreign Keys, JOIN, GROUP BY, Aggregationen
- Praktisch: Datenmodell oben in SQLite anlegen, mit Testdaten befüllen
- Erst selbst SQL schreiben, danach Claude Code zur Erklärung/Kontrolle nutzen

**Woche 3–4: REST-API mit FastAPI**
- Konzepte: HTTP-Methoden, Status-Codes, Request/Response-Bodies
- Praktisch: Endpunkte `POST /sessions`, `GET /sessions`, `POST /climbs`,
  `GET /users/{id}/sessions` usw.
- Claude Code kann hier Boilerplate übernehmen, während du Pydantic-Models
  und die Architektur verstehst

**Meilenstein:** Funktionierende API mit SQL-Anbindung (noch kein Frontend)

---

### Monat 2 – Frontend (MVP) + Nutzervalidierung

**Woche 5:** HTML/CSS/JS-Grundlagen (falls neu): DOM, Formulare, `fetch()` für
HTTP-Requests, Grundlagen mobile-first CSS (Flexbox/Grid, große Touch-Targets,
Viewport-Meta-Tag). Claude Code kann hier gut als Lernbegleiter dienen, um
Konzepte am eigenen Code zu erklären.

**Woche 6:** Mobile-first Frontend gegen die eigene API bauen:
- Formular: Session eintragen (Hand, Grifftyp, Edge, Gewicht, Reps, Sets)
- Formular: Send eintragen (Grad, Datum, Stil)
- Einfache Verlaufsansicht (Session-History-Log: Datum, Hand, Gewicht, Reps, Sets)
- Fokus auf schnelle, große Eingabefelder – das Tool muss sich in der Halle
  zwischen Sets in Sekunden bedienen lassen, nicht nach Feinschliff suchen

**Woche 7:** Mit 5–10 Personen aus der Boulderhalle/Crew sprechen – auf dem
Handy testen lassen, Feedback einholen: Was fehlt? Was ist verwirrend?
Funktioniert die Eingabe wirklich schnell genug zwischen Sets?

**Woche 8:** Iteration basierend auf echtem Feedback

**Meilenstein:** Nutzbares MVP, von echten Personen getestet, Feedback dokumentiert

---

### Monat 3 – Data Science: Trends & Korrelation

**Woche 9–10:** Zeitreihen-Trend pro Nutzer/Hand/Grifftyp:
- Kraftentwicklung über Zeit (z.B. rollender Durchschnitt)
- Einfache Plateau-Erkennung

**Woche 11:** Korrelationsanalyse Kraft (% Körpergewicht) ↔ Klettergrad
- Eigene Daten gegen Lattice's publizierte Methodik einordnen (nicht 1:1
  reproduzieren, sondern als Referenzrahmen zitieren)

**Woche 12:** Einfache Übertrainings-Heuristik (z.B. Belastungsspitze ohne
Erholungsphase → Warnung im Dashboard)

**Meilenstein:** Dashboard zeigt echte Insights, nicht nur Rohdaten

---

### Monat 4 – Polish, Deployment, Storytelling

**Woche 13:** Code-Cleanup, Tests für API-Endpunkte, README, Architekturdiagramm

**Woche 14:** Deployment (Streamlit Community Cloud + Railway/Render),
damit ein echter, teilbarer Link entsteht

**Woche 15:** Dokumentation des Produktdenkens: Welche Entscheidungen,
warum, was hat Nutzerfeedback verändert, welche technischen Stolpersteine
gab es – das ist das Material für Bewerbungsgespräche

**Woche 16:** Puffer, Politur, ggf. GitHub-Profil/LinkedIn-Post

**Stretch Goals (falls Zeit übrig ist):**
- Progressionspfade (Set-/Gewichts-/Advanced-Progression) implementieren
- Plattengerundete Gewichtsvorschläge mit individuellem Platten-Inventar
- Testing-Session-Flow zum Max-Gewicht-Reset
- Minimale PWA-Funktionalität (`manifest.json` + Icon) für "Zum Homescreen
  hinzufügen" – kein vollständiger Service Worker/Offline-Support nötig, aber
  spürbarer Komfortgewinn für die Hallen-Nutzung bei geringem Zusatzaufwand

---

## 6. Erwartungssteuerung

Mit ~20h/Woche über 4 Monate (≈ 320–350h) und Unterstützung durch Claude Code
ist dieser Plan ambitioniert, aber machbar. Der kritische Punkt: SQL und REST
in Monat 1 wirklich selbst verstehen, nicht nur generieren lassen – das ist
die Basis für alles Weitere. Bei zügigem Fortschritt kann Monat 3 vertieft
werden (z.B. richtiges ML-Modell statt einfacher Regression) oder einer der
Stretch Goals vorgezogen werden.
