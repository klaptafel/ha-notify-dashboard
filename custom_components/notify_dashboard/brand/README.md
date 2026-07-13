# Brand assets

Since Home Assistant 2026.3, this local folder is the current standard —
see the [Brands Proxy API
announcement](https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api/).
HA core itself now serves these files directly (via
`/api/brands/integration/{domain}/{image}`, with local images taking
priority over the CDN) for its own UI — device pages, integration list,
etc. — not just for HACS's listing. HACS's own repository validation was
already checking this exact path
(`custom_components/notify_dashboard/brand/icon.png`) before that change.

The [home-assistant/brands](https://github.com/home-assistant/brands) repo
now calls its `custom_integrations/` folder "legacy" and points contributors
here instead — a submission there is no longer needed.

## Expected files

| File | Format | Required |
|---|---|---|
| `icon.png` | 256×256, transparent background | Yes |
| `icon@2x.png` | 512×512 | Recommended |
| `logo.png` | square or wide, transparent background | Optional |
| `logo@2x.png` | 2x of logo.png | Optional, only together with logo.png |
| `dark_icon.png` / `dark_logo.png` | same dimensions as their light variant | Optional, for dark mode |

All four required/recommended files above are present. `dark_icon.png`/
`dark_logo.png` are not — nice-to-have, not blocking.

See also `../quality_scale.yaml` (the `brands` rule).
