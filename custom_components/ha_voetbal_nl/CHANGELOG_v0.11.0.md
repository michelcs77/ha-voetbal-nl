# HA Voetbal.nl v0.11.0

- Programma-ophaling structureel verbeterd voor teams waarbij Voetbal.nl het seizoen over meerdere `ScheduleResults`-blokken verdeelt.
- AJAX-programmablokken worden nu iteratief gevolgd: ook een vervolg-URL die pas in een eerder opgehaald blok verschijnt wordt meegenomen.
- Ondersteuning toegevoegd voor HTML-escaped `data-options`, JSON-responses met een `html`-blok en absolute voetbal.nl-programma-URL's.
- Dubbele programma-URL's worden overgeslagen en de crawler is defensief begrensd.
- Gewone wedstrijdlinks worden niet als pagination-endpoint gevolgd.
- Hiermee wordt voorkomen dat een programma na alleen de eerste beker-/competitiefase wordt afgekapt, zoals zichtbaar was bij v.v. Cuijk 3 en eerder bij MO17-2.
- Overige functionaliteit (WhatsApp, polls, rijschema, vlaggers, trainingen en PDF-export) is niet functioneel gewijzigd.
