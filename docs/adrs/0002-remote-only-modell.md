# Alle LLM-Aufrufe remote, kein lokales Modell

Sämtliche LLM-Nutzung läuft über ein remote bereitgestelltes Spitzenmodell; ein lokales Modell wird nirgends eingesetzt. Das ist nicht offensichtlich, weil der Nutzer anfangs Kosten und Token-Limits fürchtete und ein lokales Modell naheliegend wirkte. Der Grund für remote: Das LLM steckt ausschließlich in *kalten* Pfaden — der einmaligen Offline-Aufbereitung pro Modul und dem nur gelegentlich genutzten Tutormodus. Damit ist das Volumen klein (Cent-Beträge), und Qualität — dem Nutzer das Wichtigste — wird nicht ausgerechnet im Moment der Verständnislücke durch ein schwächeres lokales Modell kompromittiert.

## Considered Options

Verworfen: Lokales Modell. Sinnvoll nur bei garantierter Offline-Pflicht, Datenschutz-Zwang, fehlendem API-Account oder sehr intensiver Live-Nutzung — keiner dieser Fälle trifft zu.
