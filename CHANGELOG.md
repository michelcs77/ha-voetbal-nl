# HA Voetbal.nl v0.10.0

## Wedstrijdtaken: optionele assistent-scheidsrechter/vlagger

- Nieuwe per-team instelling `Vlagger regelen` (aan/uit).
- Vlaggerplanning staat volledig los van aanwezigheidspolls.
- Per team kunnen vlaggers worden uitgesloten.
- Extra vlaggers/staf kunnen worden toegevoegd.
- Bij thuiswedstrijden is iedere geschikte vlagger toegestaan.
- Bij uitwedstrijden wordt alleen gekozen uit personen die daadwerkelijk in het rijschema staan.
- Extra chauffeurs/staf kunnen per team worden toegevoegd.
- Een expliciete optie kan het rijschema en de vlaggerplanning voor één team opnieuw berekenen.
- Bestaande rijschema's worden niet automatisch opnieuw berekend.
- De nieuwe functie is standaard uitgeschakeld, zodat bestaande teams zoals v.v. Cuijk 3 ongemoeid blijven.
- De planning is persistent opgeslagen per team en wedstrijd.
- Nieuwe sensor `sensor.ha_voetbal_nl_<team>_vlagger` toont status, naam, wedstrijden en waarschuwingen.

### Beoogd testteam

v.v. Cuijk MO17-2 kan via de configuratie worden geactiveerd en daarna expliciet opnieuw worden berekend. v.v. Cuijk 3 blijft standaard zonder vlaggerplanning en behoudt het bestaande rijschema.
