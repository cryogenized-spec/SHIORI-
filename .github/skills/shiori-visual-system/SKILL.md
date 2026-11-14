---
name: shiori-visual-system
description: Create or review SHIORI web, Linux, desktop and Android UI while preserving the approved Japanese ink and modern Latin logo, restrained ELF//SHELL-inspired design, charcoal/plum/lavender palette, responsive calendar-first Today view, and accessibility/performance requirements. Use for interface changes, visual refinements, layouts and user-flow tests.
---

# SHIORI visual and interaction system

SHIORI / 栞 is a professional open-source task manager first; art reinforces the identity but does not obscure the work.

## Identity

- Approved symbol: expressive black sumi-ink `栞` paired with modern Western `SHIORI` lettering; use approved project artwork, not substitute stock images.
- Palette: deep charcoal/blue-black, plum, muted violet/lavender, restrained magenta and warm parchment. Existing CSS tokens are the implementation source of truth; do not invent "official" hex values without approval.
- The ELF//SHELL-world android geisha with paper umbrella, oversized rope belt and wooden sandals belongs in splash/onboarding/about and optional atmospheric sections—not obstructive permanent overlays.
- Preserve crisp 1990s OVA/cel aesthetics where illustration is used, but treat production UI with clear typography and information hierarchy.

## Experience

- Desktop: dense optional productivity tools, accessible navigation, keyboard shortcuts and fast task operations.
- Mobile: touch-friendly one-handed quick capture, Today, Inbox, Projects and useful gestures; do not simply shrink the desktop UI.
- Today/Home must include a collapsible, navigable month calendar with task indicators, selected date filtering and persistence of show/hide preference.
- Keep core workflow accessible without decorative images, connectivity or AI.
- Support dark/light themes, reduced motion, proper contrast, visible focus, accessible names, 44px-ish touch targets where practical, and screen-reader semantics.

## Tests

Review with Playwright at desktop and mobile widths; validate keyboard navigation, local persistence, date navigation, overflow, label/text consistency and axe-core serious/critical accessibility findings. Do not compromise legibility to preserve a palette or appearance.
