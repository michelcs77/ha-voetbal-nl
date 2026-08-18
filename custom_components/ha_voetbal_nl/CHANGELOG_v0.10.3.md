# HA Voetbal.nl v0.10.3

## Nieuwe functie: tijdelijke rijbeperkingen per wedstrijd

Een speler kan nu per specifieke wedstrijddatum tijdelijk worden uitgesloten als chauffeur, zonder de speler voor het hele seizoen uit te sluiten.

### Configuratie
In **Rijschema — team** is het veld **🚫 Tijdelijke rijbeperkingen** toegevoegd. Gebruik bijvoorbeeld:

`Babs van Haren | 12-09-2026`

Meerdere beperkingen kunnen met een puntkomma worden opgegeven. Zowel `DD-MM-JJJJ` als `YYYY-MM-DD` wordt geaccepteerd.

### Planner
- De tijdelijke beperking geldt uitsluitend op de opgegeven datum.
- Op andere wedstrijden blijft de speler gewoon beschikbaar als chauffeur.
- De beperking wordt meegenomen bij een volledige rebuild én bij aanvullende rijschema's.
- De vlaggerplanning blijft ongewijzigd: vlaggers zijn een aparte whitelist en bij uitwedstrijden moet de vlagger ook chauffeur zijn.
- Bestaande plannen met een nieuw ingestelde beperking worden in de status als ongeldig/incompleet behandeld totdat opnieuw wordt berekend.

### Voorbeeld
Babs van Haren kan normaal rijden, maar met `Babs van Haren | 12-09-2026` wordt zij op 12 september niet ingepland. Op 29 augustus, 19 september en 10 oktober kan zij wel worden ingepland.
