# Brand assets — staging

Deze map is géén onderdeel van wat Home Assistant zelf gebruikt om de
integratie te tonen (HA haalt brand-icons los op, via domain, uit de publieke
[home-assistant/brands](https://github.com/home-assistant/brands)-repo) — het
is alleen een staging-plek totdat de assets daadwerkelijk als PR naar die repo
gaan, onder `custom_integrations/notify_dashboard/`. Zodra ze klaar zijn: hier
droppen en 1-op-1 overnemen in die PR.

## Verwachte bestanden

| Bestand | Formaat | Vereist |
|---|---|---|
| `icon.png` | 256×256, transparante achtergrond | Ja |
| `icon@2x.png` | 512×512 | Aanbevolen |
| `logo.png` | vierkant of breed, transparante achtergrond | Optioneel |
| `logo@2x.png` | 2x van logo.png | Optioneel, alleen samen met logo.png |
| `dark_icon.png` / `dark_logo.png` | zelfde afmetingen als hun light-variant | Optioneel, voor dark mode |

Zie de CONTRIBUTING-richtlijnen van home-assistant/brands voor de actuele,
volledige eisen (bestandsformaat, transparantie, geen tekst in het icoon) vóór
dit daadwerkelijk wordt ingediend — bovenstaande is een samenvatting, geen
vervanging daarvan.

Zie ook `../quality_scale.yaml` (regel `brands`).
