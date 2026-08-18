# HA Voetbal.nl v0.10.2

## Fix: volledige herberekening wedstrijdtaken

De knop `rebuild_match_tasks` is nu een echte volledige rebuild voor het gekozen team.

### Volgorde
1. Bestaand rijschema van het gekozen team wordt volledig gewist.
2. Het rijschema wordt opnieuw opgebouwd op basis van de actuele chauffeurinstellingen.
3. Alle uitwedstrijden krijgen opnieuw het ingestelde aantal auto's wanneer er voldoende beschikbare chauffeurs zijn.
4. Daarna wordt de vlaggerplanning opnieuw opgebouwd.
5. Bij uitwedstrijden wordt alleen een geselecteerde vlagger gebruikt die ook chauffeur is.
6. Bij thuiswedstrijden hoeft de vlagger geen chauffeur te zijn.
7. De HA-entiteiten worden direct bijgewerkt, zodat oude sensorwaarden niet blijven staan tot de volgende coordinator-refresh.

De rebuild is uitsluitend van toepassing op het gekozen team.
v.v. Cuijk 3 blijft ongemoeid zolang de vlaggerfunctie/rebuild daar niet wordt uitgevoerd.
