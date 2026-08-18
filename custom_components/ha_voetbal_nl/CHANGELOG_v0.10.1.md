# HA Voetbal.nl v0.10.1

## Vlaggers als whitelist

- De vlaggerconfiguratie gebruikt nu een duidelijke whitelist: **alleen geselecteerde personen mogen vlaggen**.
- Niet geselecteerd betekent expliciet: **niet inplannen als vlagger**.
- De oude `excluded_flaggers`-bediening is verwijderd uit het configuratiescherm.
- Extra vlaggers kunnen nog steeds als bestaande personen of handmatig worden toegevoegd.
- Thuiswedstrijden: een geselecteerde vlagger kan worden gepland zonder chauffeur te zijn.
- Uitwedstrijden: een geselecteerde vlagger moet ook in het rijschema van die wedstrijd staan.
- De vlaggerplanning blijft volledig onafhankelijk van de aanwezigheidspoll.
- De optie voor herberekenen blijft een expliciete actie per team.
- Bestaande rijschema's worden niet automatisch opnieuw berekend alleen door het opslaan van de vlaggerinstellingen.

## Testdoel

- v.v. Cuijk MO17-2: vlaggerplanning testen en daarna expliciet rijschema + vlaggers opnieuw berekenen.
- v.v. Cuijk 3: vlaggerplanning blijft uit en bestaande rijschema's blijven ongemoeid.
