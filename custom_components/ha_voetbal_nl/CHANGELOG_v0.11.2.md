# HA Voetbal.nl v0.11.2

- Programma-parser herkent nu ook AJAX-programmalinks in gewone `href`/`action` attributen en ruwe/escaped markup.
- De reguliere competitie-endpoint `/team/ajax/<team_id>/programma/competitie` wordt als veilige fallback mee opgehaald wanneer Voetbal.nl alleen de actieve bekerfase in de pagina publiceert.
- Extra diagnose-attributen: ontdekte, opgehaalde en mislukte ScheduleResults-URL's.
- Bestaande functionaliteit voor WhatsApp, rijschema, vlaggers, trainingen en PDF-export ongewijzigd.
