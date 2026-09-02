# ⚽ HA Voetbal.nl

Een onofficiële Home Assistant custom integration voor gegevens van **Voetbal.nl**.

Met **HA Voetbal.nl** kun je een club en één of meerdere teams selecteren en voetbalinformatie in Home Assistant gebruiken voor dashboards, planning en automatiseringen.

Naast wedstrijd- en trainingsinformatie biedt de integratie inmiddels ondersteuning voor onder andere aanwezigheid, rijschema's, vlaggerplanning, WhatsApp-communicatie, automatische polls en reminders, weersinformatie en PDF-export.

De integratie is volledig via de Home Assistant-interface te configureren.

> [!IMPORTANT]
> Dit is een onafhankelijk communityproject en is **niet officieel verbonden aan, goedgekeurd door of ondersteund door Voetbal.nl of de KNVB**.
>
> De integratie gebruikt de website van Voetbal.nl. Wijzigingen aan die website kunnen de werking van de integratie beïnvloeden.

---

## ✨ Functies

### ⚽ Voetbal.nl

- Inloggen met een Voetbal.nl-account via de Home Assistant config flow.
- Club zoeken en één of meerdere teams selecteren.
- Team-, spelers- en stafgegevens als sensoren.
- Wedstrijdprogramma en volgende wedstrijd.
- Ondersteuning voor competitie- en bekerwedstrijden.
- Trainingsschema en trainingsinformatie.
- Seizoensoverzicht.

### 👥 Team en aanwezigheid

- Selectie uit Voetbal.nl gebruiken.
- Handmatig spelers toevoegen.
- Stafgegevens verwerken.
- Aanwezigheidsregistratie voor wedstrijden.
- Aanwezigheidsregistratie voor trainingen.
- Statussen zoals:
  - ✅ Aanwezig
  - ❌ Afwezig
  - 🤕 Geblesseerd
- Aanwezigheidscontrole en overzichten binnen Home Assistant.

### 🚗 Rijschema

- Automatisch rijschema voor uitwedstrijden.
- Instelbaar aantal auto's per wedstrijd.
- Chauffeurs selecteren.
- Spelers permanent uitsluiten als chauffeur.
- Chauffeurs voor een specifieke wedstrijddatum als niet beschikbaar instellen.
- Rijschema opnieuw laten berekenen op basis van actuele instellingen.

### 🚩 Vlagger / assistent-scheidsrechter

- Optionele automatische vlaggerplanning.
- Zelf bepalen welke spelers als vlagger mogen worden ingepland.
- Verdeling over het seizoen.
- Rekening houden met het rijschema bij uitwedstrijden.
- Permanente en tijdelijke rijbeperkingen meenemen.
- Vlaggerinformatie beschikbaar in wedstrijdinformatie en seizoensoverzicht.

### 🗺️ Routeberekening

- Optionele routeberekening via **OpenRouteService**.
- Afstand naar uitwedstrijden.
- Verwachte reistijd.
- Ondersteuning voor gebruik in het rijschema en seizoensoverzicht.

---

## 📲 WhatsApp via WAHA

HA Voetbal.nl kan optioneel worden gekoppeld aan **WAHA** voor automatische WhatsApp-communicatie met het team.

Per team kunnen afzonderlijke **test- en productiegroepen** worden ingesteld.

Hierdoor kunnen berichten en polls eerst veilig worden getest voordat ze daadwerkelijk naar het team worden gestuurd.

### 📊 Wedstrijdpolls

Voor wedstrijden kan automatisch een aanwezigheids-poll worden verstuurd.

Spelers kunnen bijvoorbeeld stemmen:

- ✅ Aanwezig
- ❌ Afwezig
- 🤕 Geblesseerd

De stemmen worden automatisch door Home Assistant verwerkt en gekoppeld aan de betreffende speler en wedstrijd.

### 🏃 Trainingspolls

Ook voor trainingen kunnen automatisch aanwezigheidspolls worden verstuurd.

Wedstrijden en trainingen hebben ieder hun eigen planning en kunnen onafhankelijk van elkaar worden ingesteld.

### ⏰ Flexibele WhatsApp-planning

Via de Home Assistant-interface kan per team worden ingesteld wanneer WhatsApp-berichten worden verzonden.

Voor zowel **wedstrijden** als **trainingen** kunnen afzonderlijke momenten worden aangemaakt voor:

- 📊 Poll
- 🔔 Reminder
- ℹ️ Informatiebericht

Per berichtmoment kan worden ingesteld:

- hoeveel dagen vooraf het bericht wordt verstuurd;
- op welk tijdstip het bericht wordt verstuurd.

Er kunnen meerdere reminders worden toegevoegd.

De planner maakt duidelijk onderscheid tussen:

- ⚽ WEDSTRIJD
- 🏃 TRAINING

### 📌 Wedstrijdpoll automatisch vastzetten

Een automatisch verstuurde productie-wedstrijdpoll wordt automatisch **vastgezet in de WhatsApp-groep**.

Hierdoor blijft de actuele wedstrijdpoll eenvoudig bereikbaar voor de spelers.

Na de wedstrijd wordt de poll automatisch weer losgemaakt.

### 🔔 Reminder als antwoord op de poll

Een wedstrijdreminder wordt als **reply op de oorspronkelijke wedstrijdpoll** verstuurd.

De bestaande remindertekst blijft behouden, maar WhatsApp toont daarbij direct de oorspronkelijke poll.

Hierdoor hoeft een speler niet terug te scrollen door de groepschat om de juiste poll terug te vinden.

Er wordt geen tweede of dubbele poll aangemaakt.

### 🚗 Chauffeurwaarschuwing

Wanneer een speler bij een wedstrijdpoll:

- ❌ afwezig stemt; of
- 🤕 geblesseerd stemt;

en voor die wedstrijd als chauffeur staat ingepland, geeft HA Voetbal.nl automatisch een waarschuwing.

De WhatsApp-groep ontvangt bijvoorbeeld:

> 🚗 **Chauffeurwaarschuwing - VV Cuijk 3**
>
> Speler heeft gestemd: ❌ afwezig.
>
> Deze speler staat als chauffeur gepland. Graag zelf actie ondernemen of vervanging regelen. Het rijschema is niet aangepast.

Het bestaande rijschema wordt bewust **niet automatisch gewijzigd**.

### 👤 Persoonlijke chauffeurwaarschuwing

Vanaf versie **0.11.10** ontvangt de betreffende chauffeur daarnaast automatisch een **persoonlijk WhatsApp-bericht** met dezelfde waarschuwing.

Hiervoor hoeft geen aparte lijst met mobiele telefoonnummers te worden bijgehouden. De integratie gebruikt de WhatsApp-identiteit die bij de pollstem beschikbaar is.

Veiligheidsmaatregelen:

- alleen actief voor productie-wedstrijdpolls;
- testpolls sturen geen persoonlijke berichten;
- dezelfde waarschuwing wordt niet onnodig meerdere keren verstuurd;
- een fout bij het privébericht blokkeert de groepsmelding niet;
- het rijschema wordt niet automatisch aangepast.

### 🤖 Digitale stafassistent

WhatsApp-berichten kunnen worden voorzien van een herkenbare digitale afzender, bijvoorbeeld:

> 🤖 **De AI-Stafchef**  
> Digitale stafassistent van VV Cuijk 3

De naam van deze assistent kan per team worden ingesteld.

---

## 🌦️ Weersinformatie

Optioneel kan weersinformatie via **Open-Meteo** worden toegevoegd aan wedstrijd- en trainingsinformatie.

Hierdoor kan relevante weersinformatie automatisch worden meegenomen in berichten richting het team.

Voor Open-Meteo is geen aparte API-key nodig.

---

## 🤖 Google Gemini

Optioneel kan **Google Gemini** worden gebruikt voor aanvullende coach- of stafteksten.

Hiervoor kunnen via de configuratie-interface een Gemini API-key en model worden ingesteld.

Deze functionaliteit is optioneel en niet noodzakelijk voor de basiswerking van HA Voetbal.nl.

---

## 📄 PDF-export

De integratie kan voor een team een seizoens-PDF genereren.

Afhankelijk van de beschikbare gegevens kan deze onder andere bevatten:

- volledig wedstrijdprogramma;
- thuis- en uitwedstrijden;
- tegenstanders;
- wedstrijddata en aanvangstijden;
- rijschema;
- chauffeurs;
- tijdelijke chauffeur-onbeschikbaarheid;
- vlaggerplanning;
- trainingen;
- team- en clublogo's.

De actie:

`ha_voetbal_nl.genereer_seizoens_pdf`

is hiervoor beschikbaar.

De PDF kan vervolgens binnen Home Assistant verder worden gebruikt of verzonden.

---

## 🏠 Home Assistant

Afhankelijk van de gekozen configuratie maakt HA Voetbal.nl sensoren en functionaliteit beschikbaar voor onder andere:

- geselecteerde club;
- geselecteerde teams;
- spelers;
- staf;
- wedstrijdprogramma;
- volgende wedstrijd;
- trainingsschema;
- aanwezigheid;
- trainingsaanwezigheid;
- wedstrijdinstellingen;
- routes;
- rijschema;
- vlaggerplanning;
- WhatsApp-status;
- seizoensoverzicht.

Daarnaast zijn verschillende acties/services beschikbaar voor onder andere:

- wedstrijdpoll versturen;
- trainingspoll versturen;
- aanwezigheid controleren;
- wedstrijdinformatie versturen;
- trainingsinformatie versturen;
- scheduler testen/simuleren;
- seizoens-PDF genereren.

---

# 📦 Installatie via HACS

1. Open **HACS** in Home Assistant.
2. Ga naar **Integrations**.
3. Open het menu rechtsboven en kies **Custom repositories**.
4. Voeg de URL van deze GitHub-repository toe.
5. Kies type **Integration**.
6. Installeer **HA Voetbal.nl**.
7. Herstart Home Assistant.
8. Ga naar **Instellingen → Apparaten & diensten → Integratie toevoegen**.
9. Zoek op **HA Voetbal.nl**.
10. Doorloop de configuratie.

---

## 🔧 Handmatige installatie

Kopieer de map:

```text
custom_components/ha_voetbal_nl
```

naar de map:

```text
custom_components
```

van je Home Assistant-configuratie.

Herstart daarna Home Assistant en voeg de integratie via:

**Instellingen → Apparaten & diensten**

toe.

---

# ⚙️ Configuratie

Voor de basisfunctionaliteit heb je een geldig **Voetbal.nl-account** nodig.

Optionele uitbreidingen vragen aanvullende configuratie:

- **OpenRouteService**  
  API-key voor route- en reistijdberekeningen.

- **WAHA**  
  Basis-URL, API-key en sessie voor WhatsApp-functionaliteit.

- **Google Gemini**  
  API-key en model voor optionele coachteksten.

- **Open-Meteo**  
  Wordt gebruikt voor optionele weersinformatie en vereist geen API-key.

API-keys en wachtwoorden horen uitsluitend via de configuratie-interface ingevoerd te worden.

Plaats nooit persoonlijke sleutels, wachtwoorden of tokens in issues, screenshots of logbestanden.

---

# 🔐 Privacy en beveiliging

De integratie kan gevoelige gegevens verwerken, waaronder:

- e-mailadres van het Voetbal.nl-account;
- wachtwoord van het Voetbal.nl-account;
- API-keys;
- WhatsApp-groeps-ID's;
- WhatsApp-identiteiten;
- namen van spelers en staf.

Deze repository bevat geen ingebouwde accounts, wachtwoorden of API-keys.

Gebruik bij voorkeur aparte/revocable API-keys voor externe diensten.

Deel diagnostische gegevens alleen nadat je hebt gecontroleerd dat daarin geen persoonsgegevens, tokens, groeps-ID's of andere gevoelige gegevens staan.

---

# ⚠️ Bekende beperkingen

- Dit is geen officiële Voetbal.nl API-integratie.
- Wijzigingen aan de website van Voetbal.nl kunnen parsing of authenticatie breken.
- Beschikbare teamgegevens zijn afhankelijk van wat het gebruikte Voetbal.nl-account mag zien.
- WAHA, Gemini en OpenRouteService zijn optionele externe projecten/diensten.
- WhatsApp-functionaliteit is afhankelijk van de gebruikte WAHA-versie en engine.
- Een poll die al vóór installatie van de automatische pin-functionaliteit is verstuurd, kan niet achteraf automatisch worden beheerd wanneer het oorspronkelijke message-ID niet bekend is.

---

# 🐛 Problemen melden

Maak bij een probleem een GitHub issue met:

- versie van HA Voetbal.nl;
- Home Assistant-versie;
- korte omschrijving van het probleem;
- relevante foutmelding uit de Home Assistant-logs;
- indien relevant de gebruikte WAHA-versie/engine.

Verwijder vóór het plaatsen altijd:

- wachtwoorden;
- API-keys;
- cookies;
- tokens;
- telefoonnummers;
- WhatsApp-groeps-ID's;
- andere persoonsgegevens.

---

# 🧪 Testen

Voor verschillende WhatsApp-functies zijn test- en simulatiemogelijkheden beschikbaar.

Gebruik waar mogelijk eerst de ingestelde **WhatsApp-testgroep** voordat productiecommunicatie wordt ingeschakeld.

Dit voorkomt dat testpolls of testberichten onbedoeld in de echte spelersgroep terechtkomen.

---

# 📌 Versie

Huidige release: **0.11.10**

Belangrijkste recente uitbreidingen:

### 0.11.10

- Persoonlijke WhatsApp-waarschuwing voor een chauffeur die zich afmeldt.
- Alleen actief bij productie-wedstrijdpolls.
- Geen aparte telefoonnummeradministratie noodzakelijk.
- Fouten bij privéberichten verstoren de overige WhatsApp-verwerking niet.

### 0.11.9

- Wedstrijdpoll automatisch vastzetten in WhatsApp.
- Wedstrijdreminders als reply op de oorspronkelijke poll.
- Poll na de wedstrijd automatisch losmaken.
- WAHA message-ID van de wedstrijdpoll wordt hiervoor bijgehouden.

### 0.11.8

- Sterk vereenvoudigde WhatsApp-berichtenplanner.
- Wedstrijd- en trainingsmomenten in één overzicht.
- Duidelijk onderscheid tussen **WEDSTRIJD** en **TRAINING**.
- Polls, reminders en informatieberichten afzonderlijk instelbaar.

Zie [CHANGELOG.md](https://github.com/michelcs77/ha-voetbal-nl/blob/main/CHANGELOG.md) voor de overige wijzigingen.

---

# 📜 Licentie

Dit project wordt gepubliceerd onder de [MIT License](https://github.com/michelcs77/ha-voetbal-nl/blob/main/LICENSE).
