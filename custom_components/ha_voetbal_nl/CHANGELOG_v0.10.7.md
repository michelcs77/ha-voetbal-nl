# v0.10.7

## Vlaggerverdeling
- De vlaggersensor bevat nu een `verdeling`-attribuut.
- Per geconfigureerde vlagger wordt het aantal toegewezen wedstrijden bijgehouden.
- Alleen daadwerkelijk geregelde vlagger-toewijzingen tellen mee.
- Vlaggers met nul toegewezen wedstrijden blijven zichtbaar met `wedstrijden: 0`.
- De verdeling is geschikt voor een `custom:flex-table-card` met `data: verdeling`.
