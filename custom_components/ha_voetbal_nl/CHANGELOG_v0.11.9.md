# v0.11.9

- Productie-wedstrijdpoll wordt na verzenden automatisch 7 dagen vastgezet in de WhatsApp-groep (WAHA WEBJS/NOWEB).
- De bestaande wedstrijdreminder wordt als WhatsApp-reply op de originele poll verzonden; de remindertekst blijft ongewijzigd.
- Geen dubbele poll: de reminder verwijst naar dezelfde eerder verstuurde poll.
- Het volledige WAHA message-ID van de poll wordt naast het bestaande interne poll-ID opgeslagen.
- 2,5 uur na aftrap wordt de vastgezette wedstrijdpoll automatisch losgemaakt.
- Mislukte pin/unpin-acties blokkeren de normale poll- of reminderflow niet; unpin wordt bij een volgende scheduler-tick opnieuw geprobeerd.
- Testpolls en trainingspolls worden niet automatisch vastgezet en trainingsreminders blijven ongewijzigd.
