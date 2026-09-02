# HA Voetbal.nl v0.11.6

## Nieuw
- Dynamische WhatsApp-berichtenplanning per team.
- Afzonderlijk overzicht voor wedstrijden en trainingen.
- Planningsregels in formaat `type | dagen vooraf | HH:MM`.
- Ondersteuning voor meerdere reminders per wedstrijd of training.
- Poll, reminder en informatiebericht zijn onafhankelijk planbaar.
- Iedere reminder krijgt een unieke uitvoersleutel zodat Home Assistant-herstarts geen dubbele reminders veroorzaken.

## Compatibiliteit
- Bestaande v0.11.5 poll-, reminder- en wedstrijddaginstellingen worden automatisch als startwaarden getoond.
- Oude schedulerinstellingen blijven als fallback beschikbaar zolang geen nieuwe planning is opgeslagen.
- De bestaande trainingsinfo-instelling in uren vooraf blijft actief zolang geen expliciete `info`-regel voor trainingen is toegevoegd.
