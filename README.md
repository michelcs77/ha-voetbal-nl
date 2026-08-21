# HA Voetbal.nl

Een onofficiële Home Assistant custom integration voor gegevens van **Voetbal.nl**.

Met HA Voetbal.nl kun je een club en één of meerdere teams selecteren en voetbalinformatie in Home Assistant gebruiken voor dashboards en automatiseringen. De integratie is via de Home Assistant-interface te configureren.

> [!IMPORTANT]
> Dit is een onafhankelijk communityproject en is **niet officieel verbonden aan, goedgekeurd door of ondersteund door Voetbal.nl of de KNVB**. De integratie gebruikt de website van Voetbal.nl. Wijzigingen aan die website kunnen de werking van de integratie beïnvloeden.

## Functies

- Inloggen met een Voetbal.nl-account via de Home Assistant config flow.
- Club zoeken en één of meerdere teams selecteren.
- Team-, spelers- en stafgegevens als sensoren.
- Wedstrijdprogramma en volgende wedstrijd.
- Trainingsschema en trainingsinformatie.
- Aanwezigheidsregistratie voor wedstrijden en trainingen.
- Rijschema voor uitwedstrijden.
- Optionele vlagger-/assistent-scheidsrechterplanning.
- Routeberekening via OpenRouteService.
- Seizoensoverzicht en PDF-export.
- Optionele WhatsApp-polls en berichten via WAHA.
- Optionele weersinformatie via Open-Meteo.
- Optionele coachteksten via Google Gemini.

## Installatie via HACS

1. Open **HACS** in Home Assistant.
2. Ga naar **Integrations**.
3. Open het menu rechtsboven en kies **Custom repositories**.
4. Voeg de URL van deze GitHub-repository toe.
5. Kies type **Integration**.
6. Installeer **HA Voetbal.nl**.
7. Herstart Home Assistant.
8. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen**.
9. Zoek op **HA Voetbal.nl** en doorloop de configuratie.

## Handmatige installatie

Kopieer de map:

```text
custom_components/ha_voetbal_nl
```

naar de map `custom_components` van je Home Assistant-configuratie. Herstart daarna Home Assistant en voeg de integratie via **Instellingen → Apparaten & diensten** toe.

## Configuratie

Voor de basisfunctionaliteit heb je een geldig Voetbal.nl-account nodig. Optionele uitbreidingen vragen aanvullende gegevens:

- **OpenRouteService**: API-key voor route- en reistijdberekeningen.
- **WAHA**: basis-URL, API-key en sessie voor WhatsApp-functionaliteit.
- **Google Gemini**: API-key en model voor optionele coachteksten.

API-keys en wachtwoorden horen uitsluitend via de configuratie-interface ingevoerd te worden. Plaats nooit persoonlijke sleutels, wachtwoorden of tokens in issues, screenshots of logbestanden.

## Beschikbare informatie

Afhankelijk van de gekozen opties maakt de integratie sensoren aan voor onder andere:

- geselecteerde club en teams;
- spelers en staf;
- programma en volgende wedstrijd;
- aanwezigheid en aanwezigheidscontrole;
- trainingsschema en trainingsaanwezigheid;
- wedstrijdinstellingen;
- routes;
- rijschema;
- vlaggerplanning;
- seizoensoverzicht.

## PDF-export

De integratie kan voor een team een seizoens-PDF genereren met onder andere wedstrijden, rijschema en trainingsinformatie. De actie `ha_voetbal_nl.genereer_seizoens_pdf` is hiervoor beschikbaar.

## Privacy en beveiliging

De integratie kan gevoelige gegevens verwerken, zoals het e-mailadres en wachtwoord van een Voetbal.nl-account en optionele API-keys. Deze repository bevat geen ingebouwde accounts, wachtwoorden of API-keys.

Gebruik bij voorkeur aparte/revocable API-keys voor externe diensten. Deel diagnostische gegevens alleen nadat je hebt gecontroleerd dat daar geen persoonsgegevens, tokens, groeps-ID's of andere gevoelige gegevens in staan.

## Bekende beperkingen

- Dit is geen officiële Voetbal.nl API-integratie; wijzigingen aan de website kunnen parsing of authenticatie breken.
- Beschikbare teamgegevens zijn afhankelijk van wat het gebruikte Voetbal.nl-account mag zien.
- WAHA, Gemini en OpenRouteService zijn optioneel en worden door externe projecten/diensten geleverd.

## Problemen melden

Maak bij een probleem een GitHub issue met:

- versie van HA Voetbal.nl;
- Home Assistant-versie;
- korte omschrijving van het probleem;
- relevante foutmelding uit de logs.

Verwijder eerst wachtwoorden, API-keys, cookies, tokens, telefoonnummers, WhatsApp-groeps-ID's en andere persoonsgegevens.

## Versie

Huidige release: **0.11.4**. Zie [CHANGELOG.md](CHANGELOG.md) voor de wijzigingen.

## Licentie

Dit project wordt gepubliceerd onder de [MIT License](LICENSE).
