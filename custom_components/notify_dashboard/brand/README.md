# Brand assets

HACS's own repository validation checks this exact path
(`custom_components/notify_dashboard/brand/icon.png`) directly and only
falls back to checking the public
[home-assistant/brands](https://github.com/home-assistant/brands) repo if
it's missing — so these files are live for HACS purposes as-is.

Home Assistant core itself is a separate story: it still fetches brand
icons for its own UI (device pages, integration list, ...) from that public
brands repo, by domain, not from here. Submitting this folder as a PR under
`custom_integrations/notify_dashboard/` there is what's needed to get the
icon showing up in HA's own UI, not just HACS's listing.

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
