# HA Voetbal.nl v0.11.4

- Nieuw PDF-hoofdstuk **Chauffeurs niet beschikbaar**.
- Tijdelijke chauffeur-onbeschikbaarheid wordt per datum gegroepeerd met week, thuis/uit en wedstrijd.
- Ook beperkingen op thuiswedstrijden worden in de PDF getoond.
- Invoer van tijdelijke rijbeperkingen is toleranter: naast puntkomma/nieuwe regel worden achter elkaar geplakte `Naam | datum`-paren herkend.
- Dubbele tijdelijke rijbeperkingen worden bij opslaan verwijderd.
- Bestaande controle blijft actief: een chauffeur die op een uitwedstrijddatum niet beschikbaar is, wordt niet ingepland.
