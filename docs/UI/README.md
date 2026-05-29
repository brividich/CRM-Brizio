# Novicrom HUB — UI kit

A click-thru recreation of the Novicrom HUB *Operativa* portal in React (Babel-in-browser).

## Files
- `index.html` — wires everything into a navigable prototype (Login → Dashboard → Anomalie → Ticket detail).
- `Brand.jsx` — `BrandMark`, `BrandLockup`, `OctTile` (the chamfered orange-notch tile that recurs through the system), and the `Icons` set (1.7-stroke line icons drawn inline so they restyle with `currentColor`).
- `Components.jsx` — `Button`, `Card`, `Stat`, `Badge`, `Field`.
- `Chrome.jsx` — `Sidebar` (navy, collapsible categories, badges, footer user) and `Topbar` (page header with actions).
- `Screens.jsx` — `DashboardScreen`, `AnomalieScreen`, `TicketScreen`, `LoginScreen`.

## Interactions
- The sidebar items, dashboard tiles, "Vedi tutte →" links, and the top-bar logout all route. Anything outside the three implemented screens drops to a placeholder.
- The login form is real-state; submitting puts you into the Dashboard. Click the logout icon in the top-bar to come back.
- Categories in the sidebar collapse/expand; the active category auto-opens.

## Visual sources
Screens trace the layout, copy and component vocabulary of the `brividich/CRM-Brizio` codebase (`auth/login.html`, `core/components/sidebar.html`, dashboard module tiles) plus the two attached splash artworks. Icons are recreated from the codebase's inline-SVG stroke style; the octagonal tile shape uses CSS `clip-path` to match the chamfered corner + orange triangular notch.

## Caveats
- The codebase is HTML/CSS/JS templates — these JSX components are cosmetic re-implementations, not ports. State is local; nothing persists.
- A handful of side modules (Asset, Persone, Timbri…) are stubbed; the visual primitives are reusable so building them out is mostly composition.
