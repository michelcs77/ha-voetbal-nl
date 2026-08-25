# HA Voetbal.nl v0.11.5

## Fix
- Teamherkenning robuuster gemaakt voor verschillende schrijfwijzen van clubnamen.
- Punten in clubnamen worden genegeerd tijdens normalisatie.
- Bijvoorbeeld `v.v. Cuijk` matcht nu correct met `VV Cuijk 3` en `VV Cuijk MO17-2`.
- Voorkomt dat geselecteerde teams na een wijziging op Voetbal.nl als 0 teams worden geladen.
- Hierdoor blijven team-sensoren na een Home Assistant herstart beschikbaar.
