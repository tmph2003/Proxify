# Chapter 4: Designing Text

## Core Idea
Great typography isn't about picking the perfect font; it's about establishing strict scales for sizing, aligning by baselines, and controlling line length and height.

## Frameworks Introduced
- **Hand-crafted Type Scales**:
  - When to use: Setting font sizes across the UI.
  - How: Don't use a strict mathematical modular scale (it yields decimal values like 31.25px and lacks mid-range options). Pick a hand-crafted scale: 12, 14, 16, 18, 20, 24, 30, 36. Avoid `em` units for sizing typography; stick to `px` or `rem`.
- **Proportional Line-height**:
  - When to use: Adjusting line spacing.
  - How: Line-height and font size are inversely proportional. Use a taller line-height (1.5 - 1.7) for small text and a shorter line-height (1 - 1.2) for large text (headlines).

## Key Concepts
- **Line Length**: For the best reading experience, paragraphs should be 45-75 characters wide (~20-35em).
- **Baseline Alignment**: When placing text of different sizes on the same line, align them by their baseline (the invisible line letters rest on), not by centering them vertically.

## Mental Models
- **Play it safe with fonts**: Use the system font stack (`-apple-system, Segoe UI, Roboto`) or neutral sans-serifs. Ignore typefaces with fewer than 5 weights, as they usually lack care/detail.
- **Not every link needs a color**: If an interface has tons of links, coloring them all creates noise. Use bolder weights or only add color on hover.

## Anti-patterns
- **Centering long form text**: If text is longer than two or three lines, it will almost always look better left-aligned.
- **Using display fonts for small text**: Fonts designed for headlines usually have tight letter-spacing and short lowercase letters. Don't use them for body copy.

## Key Takeaways
1. Align mixed font sizes by their baseline.
2. For wide text, use taller line-height so the eye can easily find the next line.
3. For all-caps text, increase letter-spacing to improve readability.
4. If a table contains numbers, right-align them so decimals line up.

## Connects To
- **Ch 2**: Weight vs contrast in typography hierarchy.
