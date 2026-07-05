# Brand assets — staging

This folder is not part of what Home Assistant itself uses to display the
integration (HA fetches brand icons separately, by domain, from the public
[home-assistant/brands](https://github.com/home-assistant/brands) repo) — it's
just a staging spot until the assets actually go out as a PR to that repo,
under `custom_integrations/notify_dashboard/`. Once they're ready: drop them
here and carry the folder over 1-to-1 into that PR.

## Expected files

| File | Format | Required |
|---|---|---|
| `icon.png` | 256×256, transparent background | Yes |
| `icon@2x.png` | 512×512 | Recommended |
| `logo.png` | square or wide, transparent background | Optional |
| `logo@2x.png` | 2x of logo.png | Optional, only together with logo.png |
| `dark_icon.png` / `dark_logo.png` | same dimensions as their light variant | Optional, for dark mode |

See home-assistant/brands' CONTRIBUTING guidelines for the current, full
requirements (file format, transparency, no text in the icon) before this
actually gets submitted — the above is a summary, not a replacement for that.

See also `../quality_scale.yaml` (the `brands` rule).
