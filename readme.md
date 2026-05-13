# NVDAClaude

NVDA-Addon, das den **Claude Desktop-Client** (Anthropic, `claude.exe`) barrierefreier macht.

Aktuelles Ziel: Schnellnavigation zwischen den einzelnen Nachrichten eines Chats per Tastaturkürzel — ähnlich wie „nächste/vorherige Überschrift" im Browse-Modus, aber zuverlässig auch dann, wenn der Fokus im Eingabefeld liegt.

Status: **Vorschlag / v0.1 in Vorbereitung.** Implementierung folgt nach Freigabe.

## Status quo (was Claude Desktop schon liefert)

Der Anthropic-Client ist ein Electron/Chromium-Programm und exponiert die Chat-DOM via UIA. Die Inspektion mit [`dumpUIA`](https://github.com/slohmaier/dumpUIA) zeigt: vor **jeder** Nachricht steht ein 1×1-Pixel großer, visuell unsichtbarer `sr-only`-Text als Anker — genau das, was Webentwickler für Screen-Reader einbauen.

| Sprecher | Anker-Element |
|---|---|
| Nutzer (DE) | `Text` · `ClassName="sr-only"` · `Name="Du hast gesagt: …"` |
| Nutzer (EN) | `Text` · `ClassName="sr-only"` · `Name="You said: …"` |
| Claude (DE) | `Text` · `ClassName="sr-only"` · `Name="Claude hat geantwortet: …"` |
| Claude (EN) | `Text` · `ClassName="sr-only"` · `Name="Claude said: …"` |

Daneben:

- Ende einer Assistant-Antwort: leerer `StatusBar` mit `ClassName="sr-only"` (vermutlich `role="status"` für „Antwort fertig").
- Aktions-Leiste nach jeder Nachricht: `Group` mit `Name="Message actions"`.
- Hauptcontainer: `Group` mit `Name="Hauptbereich"` (lokalisiert).

Das Problem: NVDA kann zwar im Browse-Modus per `H` zwischen Überschriften springen, aber Claude markiert die Nachrichten nicht als Überschriften, sondern nur als visuell versteckten Text. Außerdem liegt der Fokus meist im Eingabefeld (Fokus-Modus), wo Browse-Mode-Schnelltasten gar nicht greifen.

## Vorgeschlagene Lösung

Ein NVDA-Addon mit App-Modul für `claude.exe`, das globale Gesten registriert:

| Gestik (Standard, anpassbar) | Aktion |
|---|---|
| `NVDA+Alt+J` | Nächste Nachricht (egal von wem) |
| `NVDA+Alt+K` | Vorherige Nachricht |
| `NVDA+Alt+U` / `NVDA+Alt+Shift+U` | Nächste / vorherige **Nutzer**-Nachricht |
| `NVDA+Alt+A` / `NVDA+Alt+Shift+A` | Nächste / vorherige **Claude**-Antwort |
| `NVDA+Alt+B` | Sprung ans Ende (letzte Nachricht / Eingabefeld) |
| `NVDA+Alt+T` | Sprung an den Anfang des Chats |
| `NVDA+Alt+I` | Sprung ins Eingabefeld |
| `NVDA+Alt+C` | Aktuelle Nachricht **in voller Länge** vorlesen |
| `NVDA+Alt+Shift+C` | Aktuelle Nachricht in die Zwischenablage kopieren |

Die Auswahl `J/K` ist bewusst an Vim/Twitter angelehnt — falls Stefan andere Buchstaben bevorzugt (z. B. die im NVDA-Browse-Modus reservierten Tasten meiden), legen wir das vor der Implementierung fest.

### Wie die Navigation intern funktioniert

1. Im AppModule für `claude.exe` werden die Gesten registriert (`__gestures`).
2. Auf Tastendruck:
   - Foreground-Fenster holen (`api.getForegroundObject()`).
   - Rekursiv alle Kinder einsammeln, die `role == STATICTEXT` und einen Namen mit einem der bekannten Präfixe (`Du hast gesagt:`, `You said:`, `Claude hat geantwortet:`, `Claude said:`, `Claude responded:`) haben. Die Präfix-Liste ist konfigurierbar, damit weitere Sprachen schnell ergänzt werden können.
   - Nach `location.top` sortieren → das ist die Lesereihenfolge.
   - Aktuelle Position bestimmen (Review-Cursor oder Fokus → Y-Koordinate) und das nächste/vorherige Element auswählen.
3. Auf das Ziel zeigen:
   - `obj.scrollIntoView()` damit es sichtbar wird,
   - Review-Cursor dorthin setzen (`api.setReviewPosition`) **und** den Objektnamen + die folgenden Geschwister-Textknoten bis zum nächsten Anker sprechen.
   - Bei „volle Nachricht vorlesen" wird der komplette Textinhalt zwischen aktuellem und nächstem Anker zusammengesetzt und ausgegeben (`speech.speakText`).

### Warum AppModule statt GlobalPlugin

- Gesten sind nur aktiv, solange Claude im Vordergrund ist → kein Konflikt mit anderen Anwendungen.
- NVDA-Konvention: Anwendungsspezifisches Verhalten gehört ins App-Modul (vgl. Stefans `icloudpasswords.py`).
- Dateiname **muss** kleingeschrieben sein (`claude.py`), weil NVDA den Exe-Namen vor dem Import lowercase'd.

## Offene Fragen (vor der Implementierung zu klären)

1. **Tasten-Layout**: Sind `NVDA+Alt+J/K` etc. okay, oder kollidieren die mit anderen Addons / Stefans Setup? Alternative: `NVDA+Bild ab / Bild auf` für „nächste/vorherige Nachricht", weil das räumlich-intuitiv ist.
2. **Englische Anker**: Stefans Konto ist auf Deutsch — die englischen Strings (`You said:`, `Claude said:`) sollten wir bei Gelegenheit gegen einen englischen Claude-Tab verifizieren, bevor wir sie in Stein meißeln.
3. **Code-Blöcke & Tool-Use-Ausgaben**: Soll der Lese-Befehl Markdown-Codeblöcke übersprungen oder vorgelesen werden? Erst mal: vorlesen, aber mit „Codeblock Anfang / Ende" als Klammer.
4. **„Claude tippt…" / Streaming**: V0.2 könnte den `StatusBar`-`sr-only` als Hook nutzen, um „Antwort fertig" zu signalisieren. Erst mal nicht im MVP.
5. **Sidebar-Navigation**: Das Addon konzentriert sich auf den Chatbereich. Möchten wir später auch Schnelltasten zum Wechseln zwischen Konversationen in der Seitenleiste?

## Build / Entwicklung

(Wird ausgefüllt sobald `sconstruct` + `buildVars.py` aus dem Standard-Template übernommen sind — Vorlage liegt bei `~/git/NVDAiCloudPasswordManager`.)

```powershell
scons          # baut die .nvda-addon-Datei
scons install  # baut + installiert in NVDA
```

## Lizenz

GPL v2 (NVDA-Addon-Standard).
