# Chapter 3: Layout and Spacing

## Core Idea
Give elements more breathing room than you think they need, strictly use an established spacing scale, and don't be a slave to grids.

## Frameworks Introduced
- **Start with too much white space**:
  - When to use: When adjusting layout spacing.
  - How: Give an element way too much space, then slowly remove it until you're happy. It's much easier to see when there is too much space than when there is too little.
- **Base-16 Spacing System**:
  - When to use: Deciding margins, padding, and sizes.
  - How: Base sizes off 16px. Use a hand-crafted non-linear scale where the differences between small values (12px to 16px) are proportionally large, but large values have large jumps (e.g., 64px, 96px, 128px) so you never waste time choosing between 120px and 125px.

## Key Concepts
- **Relative sizing doesn't scale**: If element B is 2.5x larger than element A on desktop, that relationship usually breaks on mobile. Things don't scale proportionally. Large elements must shrink faster than small elements on small screens.
- **Ambiguous Spacing**: When the space below a label equals the space below the input, the visual grouping breaks. Ensure there's more space *around* the group than *within* it.

## Mental Models
- **Grids are overrated**: Outsourcing all layout to a 12-column grid forces elements to scale when they shouldn't. Give components a fixed `max-width` (like a 500px card) and only let them shrink when the viewport forces them to.
- **Shrink the canvas**: Having trouble designing on a huge monitor? Shrink the canvas to 400px and design mobile-first where constraints are real.

## Anti-patterns
- **Filling the whole screen**: Spreading things out or making things wide just because you have 1400px of space.
- **Making everything fluid**: If a sidebar is 25%, it gets too wide on big screens and truncates on small screens. Use fixed widths for elements optimized for their contents.

## Key Takeaways
1. A spacing scale should never have values closer than 25% (e.g., jumping from 16px to 24px is fine, but 120 to 125 is imperceptible).
2. Elements shouldn't shrink until they absolutely have to.
3. Don't define padding relative to font size (using `em`). Padding shouldn't scale linearly with text size.

## Connects To
- **Ch 4**: Designing text and line-height.
