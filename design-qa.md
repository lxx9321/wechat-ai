# Direction 2.5 — Desktop Empty Design QA

## Evidence

- Source visual truth: `docs/design/direction-2.5/01-desktop-empty.png`
- Implementation route: `http://127.0.0.1:4173/`
- Initial implementation capture: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\desktop-empty-initial-1440x900.png`
- Final implementation capture: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\desktop-empty-final-1440x900.png`
- Full-view initial comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\comparison-initial-source-left-implementation-right.png`
- Full-view final comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\comparison-final-source-left-implementation-right.png`
- Focused content comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\comparison-focus-content-source-left-implementation-right.png`
- Focused Composer comparison: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\comparison-focus-composer-source-left-implementation-right.png`
- Typing/focus state capture: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\desktop-composer-typing-1440x900.png`
- Responsive capture: `C:\Users\Administrator\.codex\visualizations\2026\08\26\01a03bf2-8ffb-71c2-95cc-570a38610c10\wechat-ai-direction-2.5\desktop-empty-final-1280x900.png`

## Normalization

- State: Desktop Empty, dark theme, no authenticated/API data.
- CSS viewport: `1440 × 900`.
- Browser density: `devicePixelRatio = 1`.
- Source pixels: `1586 × 992`.
- Implementation pixels: `1440 × 900`.
- Normalized source pixels: `1440 × 900`; the source's top `1586 × 960` design canvas was cropped and resized to the target CSS viewport so browser chrome/canvas padding and density did not create false findings.
- The normalized source is saved as `reference-normalized-1440x900.png` beside the QA captures.

## Findings

- No actionable P0, P1, or P2 findings remain in the final comparison.
- Fonts and typography: the approved system-first Songti display stack and PingFang/Microsoft YaHei/system UI body stack preserve the intended editorial hierarchy, weights, line height, and readable wrapping without an online font dependency.
- Spacing and layout rhythm: the implementation follows the locked 64px header, 39/61 desktop split, approximately 40px left content inset, open prompt rows, and 104px empty Composer. The title, prompt list, and Composer now align with the intended vertical rhythm.
- Colors and tokens: blue-black/graphite surfaces, ivory hierarchy, muted secondary text, dividers, amber accent, focused border, and disabled send state are mapped to reusable CSS variables.
- Image quality and asset fidelity: the right stage uses a real raster asset with dark architectural planes and a restrained amber opening. Its crop and scale match the reference art direction; no CSS illustration, inline SVG, placeholder, or film-prop substitute is used.
- Copy and content: all approved Empty State title, supporting copy, prompt copy, Composer placeholder, and header brand are present and coherent.
- Icons: Lucide line icons are used consistently for prompt categories, menu, image action, chevrons, and send; no emoji or text-glyph substitute is present.
- States and interactions: prompt selection fills the Composer only; empty send is disabled; focus and typing states are visible; Shift+Enter inserts a newline; Enter performs only the current local send simulation; IME composition is explicitly guarded in code.
- Responsiveness: there is no horizontal overflow at 1440 or 1280. At 1024 and below, the foundation switches to one column without overlap or clipping; complete mobile UI remains intentionally outside this phase.
- Accessibility: controls use semantic buttons/textarea, visible focus treatment, labels, disabled state, and reduced-motion support. The generated stage image has empty alternative text because it is decorative.

## Open Questions / Intentional Constraints

- The raster reference appears closer to a 43/57 split and a larger Composer, but the approved implementation specification explicitly locks the desktop split to 39/61 and the default Composer to roughly 96–104px. The implementation follows the specification.
- The reference raster depicts a lit send button in its empty composition; this phase explicitly requires empty send to be disabled, so the implementation uses the disabled token until text exists.
- Desktop Chat, image messages, real API state, Drama Search, and the complete Mobile screen are outside this QA state and are not represented as implemented features.

## Comparison History

### Pass 1 — blocked

- [P2] Composer sat approximately 15px below the reference rhythm.
  - Fix: increased the desktop interaction stage bottom inset so the 104px Composer aligns with the intended baseline.
- [P2] The amber opening in the visual stage sat too far toward the right edge.
  - Fix: adjusted the raster asset scale to `1.3` with right-center transform origin, bringing the light source into the same compositional zone as the reference.
- Evidence: `comparison-initial-source-left-implementation-right.png`.

### Pass 2 — passed

- Re-captured the identical Desktop Empty state at `1440 × 900`, placed source and implementation side by side, and reviewed both the full frame and focused content/Composer crops.
- The two prior P2 findings are resolved. No actionable P0/P1/P2 differences remain.
- Evidence: `comparison-final-source-left-implementation-right.png`, `comparison-focus-content-source-left-implementation-right.png`, and `comparison-focus-composer-source-left-implementation-right.png`.

## Browser and Interaction Checks

- Final 1440 metrics: header `1440 × 64`, interaction stage `560 × 836`, visual stage approximately `880 × 836`, Composer `479 × 104`, document `1440 × 900`, horizontal overflow `false`.
- 1280 metrics: no horizontal overflow; Composer remains usable and supporting copy wraps without collision.
- 1024 breakpoint: single-column foundation is active, no horizontal overflow, no overlap; the taller page is expected because the visual stage moves below the interaction stage.
- Visual asset loaded successfully at natural size `1287 × 1222`.
- Primary interaction tested: prompt selection, focus, typing, Shift+Enter newline, Enter local send behavior, disabled/active send transition, auto-growing Composer.
- Browser console: no warning or error entries; only Vite connection debug messages and the React development informational notice.

## Implementation Checklist

- [x] Match Desktop Empty composition and hierarchy.
- [x] Use reusable tokens and component boundaries.
- [x] Use a real visual-stage raster asset and Lucide icons.
- [x] Verify Composer empty, focus, and typing states.
- [x] Verify 1440, 1280, and the 1024 responsive foundation.
- [x] Complete at least one screenshot comparison and correction loop.
- [ ] Build Desktop Chat and Image states in the next phase.
- [ ] Complete the Mobile UI in its dedicated phase.

final result: passed
