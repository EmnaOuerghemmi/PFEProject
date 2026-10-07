# Design System: PIQBIT — Site carrière
**Project ID:** 8065312161493365037

## 1. Visual Theme & Atmosphere

Warm, editorial, and confident — a recruitment site for a Tunisian software
studio, not a dark SaaS dashboard cosplaying as a landing page. The mood is
**airy and disciplined**: generous white space, a warm paper-like ground,
crisp card geometry, and a single accent color spent deliberately rather than
everywhere. Two anchors bookend the palette — a warm cream ground for reading,
and a deep teal used sparingly as punctuation (header, footer, one closing
band) — so the page reads as considered, not decorated. The overall register
is closer to a well-typeset print portfolio than a tech-startup template:
confident typography carries the hierarchy; color is reserved for calls to
action and status.

## 2. Color Palette & Roles

**Ground & surfaces**
- Warm Parchment Cream (`#F2ECDE`) — primary page background. The paper the
  whole site sits on.
- Lighter Cream (`#FAF6EC`) — nested/alternate sections on the cream ground.
- Pure White (`#FFFFFF`) — floating cards, panels, the header once scrolled.
- Soft Off-White (`#FBF8F1`) — subtle recessed surface inside a card.
- Tinted Parchment (`#F6F1E4`) — a tinted block inside a white card (e.g. a
  quote or highlighted stat).

**Ink (text)**
- Deep Slate Ink (`#1B2B2B`) — primary text on light grounds, near-black but
  warm, never pure black.
- Soft Slate (`#3D4F4F`) — secondary text, body copy under headings.
- Muted Grey-Teal (`#788888`) — captions, eyebrows, metadata.
- Faint Grey-Teal (`#A4B0B0`) — the most receded text, disabled-adjacent.

**Lines**
- Warm Hairline (`#ECE3CF`) — default divider on cream/white.
- Stronger Hairline (`#DACFB8`) — card borders, emphasized dividers.

**Deep Teal (the second anchor — used as punctuation, not as a ground)**
- Deep Teal (`#06222A`) — header bar, footer, the one closing CTA band. Never
  used for body sections; reserved for framing the page top and bottom.
- Near-Black Teal (`#041A20`) — footer's darkest tier / hover depth.
- Ink on Teal — Near-White (`#F4FBFB`) — text on the deep-teal surfaces.
- Muted on Teal (`rgba(244,251,251,.65)`) — secondary text on deep teal.

**Emerald Accent (spent sparingly — CTAs and active states only, never a
large fill)**
- Emerald (`#10B981`) — primary buttons, active nav state, the one accent
  color of the whole system.
- Emerald Hover (`#0EA371`) — darkens on press/hover.
- Emerald Tint (`#D1FAE5`) — soft background for a badge or highlighted stat.
- Deep Emerald Ink (`#064E3B`) — text sitting on the emerald tint.

**Status (used only inside data — badges, pills — never as page chrome)**
- Success (`#3DA76F`) / tint `#DDF1E5`
- Warning (`#D7903A`) / tint `#FBE9CF`
- Danger (`#D45B5B`) / tint `#FADADA`
- Info (`#5687B8`) / tint `#DDE9F4`

## 3. Typography Rules

- **Headings** — Plus Jakarta Sans, weight 800, tight negative letter-spacing
  (‑0.02 to ‑0.035em at display sizes). Headings are the loudest thing on the
  page; body copy stays quiet by comparison.
- **Body copy** — Inter, weight 400, comfortable line-height (1.5–1.6),
  measured to ~55–65 characters at paragraph width — never full-bleed text.
- **Eyebrows / labels** — small caps-style: 11–12px, weight 800, letter-
  spacing 0.12–0.14em, uppercase, in Muted Grey-Teal. Used above every section
  title as a one-line context marker, never decorative.
- **Numerals** (stat counters, prices, step numbers) — tabular figures so
  columns of digits align; never let a counter animation jitter sideways.

## 4. Component Stylings

* **Buttons** — Pill-shaped (fully rounded). Primary: solid Emerald fill,
  white text, soft emerald-tinted shadow, lifts 2px and darkens on hover.
  Secondary/ghost: transparent fill, a warm hairline border, ink text; border
  turns emerald on hover. On a deep-teal surface, the "light" button variant
  is solid white with ink text — never a second emerald button competing with
  the first.
* **Cards / Containers** — Generously rounded corners (20–28px), white fill,
  a warm hairline border (not a shadow) as the default separator; on hover,
  a soft warm-tinted shadow appears and the card lifts 3–4px. Corners scale
  with the container's importance: small utility chips get 8–12px, hero/CTA
  containers get up to 28–32px.
* **Inputs / Forms** — Not a heavy focus of this system (the site is mostly
  read-and-click, not data entry), but where present: white fill, warm
  hairline border, rounded 12px, emerald focus ring.
* **Section bands** — Most sections sit directly on the cream ground with no
  card wrapper. Exactly one or two sections per page break from cream to the
  Deep Teal surface — used as full-width punctuation (a closing call-to-
  action, the site header/footer), never as a repeating pattern.
* **Decorative accents** — A single soft, diluted emerald radial glow may sit
  behind a hero or a closing CTA, entirely contained within its section
  (never bleeding past its own box edge). No gradients on large surfaces, no
  particle/mesh backgrounds, no glassmorphism beyond a light frosted header.

## 5. Layout Principles

- Content reads in a centered column (~1160–1200px) with generous side
  gutters; full-bleed only for section backgrounds (header, footer, the
  closing teal band), never for reading content itself.
- Vertical rhythm is generous: 56–96px between major sections, so the page
  breathes rather than crowds.
- Grids favor **unequal weight** over uniform tiles — e.g. a "bento" layout
  where one or two cards are visually heavier than their neighbors — over a
  flat, evenly-sized card grid, so the eye has somewhere to land first.
- Every section opens with a short eyebrow label + a heading; body content
  follows, never the reverse.
- Motion is restrained and meaningful: entrance reveals on scroll from an
  already-visible resting state, a subtle hover lift on interactive cards,
  a counter that ticks up once. No autoplaying carousels, no parallax.
