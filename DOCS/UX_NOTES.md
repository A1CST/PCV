# UX Notes

## Graph Layout
- File node centered; functions/classes as leaves.
- Semantic clustering into rings (class inner, function clusters outer) using verb-like prefixes.
- Forces adapt to node count and node degree.
- Zoom-to-fit after simulation; re-fit on ResizeObserver and slide-change.
- Labels hidden when zoomed far out to reduce clutter; visible when zoomed in.

## Modals & Responsiveness
- Settings modal: up to 860px wide (min 92vw on small screens).
- Add/New Project modals: up to 760px wide.
- First-run and global typography use `clamp()` for readability at half-screen.
