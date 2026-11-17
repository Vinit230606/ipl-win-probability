---
inclusion: always
---

# IPL UI/UX theme — "Under the lights"

Full specification supplied by the team (2026-11-17). The implementation lives on the
`under-the-lights` branch: tokens and components in `docs/assets/css/site.css`, team kits and
the clash rule in `docs/assets/js/teams.js`.

Summary of the rules every page follows:

- Visual and copy pass only: never change model code, data files, splits, probabilities or any
  number shown. If a change needs new data, stop and ask.
- Keep every page, URL, `?match=` parameter and nav item working. Static HTML/CSS/JS only;
  Google Fonts is the only new external resource.
- No official IPL, BCCI or franchise logos, crests, wordmarks or broadcaster graphics. Teams
  appear as a short code on a badge in team colours. Footer line: "Independent student project.
  Not affiliated with the IPL, BCCI or any franchise."
- Night is the default theme (`--sky #0A1633`, `--stand #12224A`, `--stand-raised #1A2E5C`,
  `--rope #2A3F70`, `--chalk #EEF2FA`, `--chalk-dim #9FB0D0`, `--turf #1E5E3A`,
  `--leather #C8102E` for wickets only, `--floodlight #FFF4D6` for one hero glow). A day-match
  theme applies under `prefers-color-scheme: light`.
- Barlow Condensed 600/700 for titles, headings, scoreboard figures, team codes and the
  predictor percentage; Barlow 400/500 for everything else; tabular numbers; sentence case; no
  tracked all-caps labels; no monospace; no arrows in link or button text.
- Team colour is the one bold thing: when a chase loads, `<body data-chase data-defend>` and
  `--chase`, `--chase-line`, `--chase-ink`, `--defend`, `--defend-line`, `--defend-ink` drive the
  scoreboard, predictor bar, chart halves and legend. Clash rule in OKLCH (hue < 35° and
  lightness < 0.15): the defending side uses `alt`, then chalk with a hatch.
- Model lines stay neutral (main solid chalk, baseline dashed chalk-dim, other dotted).
  Wickets are a stump glyph in leather; big overs a turf column; decided segment in turf.
- One motion moment: a 600ms pulse in the winner's colour when the chase is decided; everything
  else ≤ 250ms; none under reduced motion.
- Contrast ≥ 4.5:1 for text, ≥ 3:1 for lines and badges; 2px chalk focus outline; works from
  360px; tables and charts scroll in their own container.
