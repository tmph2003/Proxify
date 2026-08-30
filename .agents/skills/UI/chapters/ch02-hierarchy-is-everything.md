# Chapter 2: Hierarchy is Everything

## Core Idea
Visual hierarchy—dictating how important elements appear relative to one another—is the most effective tool you have for making something feel "designed."

## Frameworks Introduced
- **Hierarchy Over Size**:
  - When to use: When trying to make a headline stand out without making it comically large.
  - How: Instead of leaving heavy lifting to font size alone, use font weight (boldness) or color (contrast) to do the same job.
- **Emphasize by De-emphasizing**:
  - When to use: When a primary element still doesn't stand out despite being loud.
  - How: Soften the color or reduce the contrast of the inactive or secondary elements surrounding it.

## Key Concepts
- **Weight and Contrast Balance**: Heavy elements (like solid icons) draw more attention than text. To balance them, reduce the contrast of the icon.
- **Semantic HTML vs Visual Hierarchy**: A semantic `h1` doesn't mean it visually has to be the largest element on the page. Section titles often act as labels and should be visually smaller than the content itself.

## Mental Models
- **Use color/weight for primary vs secondary**: Instead of a 24px primary and 12px secondary font, use 16px bold dark text for primary, and 14px regular soft-grey text for secondary.
- **Labels are a last resort**: When data format is obvious (e.g., an email address or a price), don't prepend it with a bold label (e.g., "Email:"). The label ruins the hierarchy.

## Anti-patterns
- **Using grey text on colored backgrounds**: Lowering opacity of white text on a colored background makes it look washed out and disabled.
- **Naïve Label-Value formats**: Treating all data equally (e.g., "Bedrooms: 3"). Instead, combine them ("3 bedrooms") to preserve hierarchy.

## Key Takeaways
1. Not all elements are equal; deliberate de-emphasis is what makes a UI feel designed.
2. Don't use grey text on colored backgrounds; hand-pick a tinted color of the same hue.
3. Separate document hierarchy (H1, H2) from visual hierarchy.
4. When elements have different weights (like an icon next to text), adjust contrast to counterbalance.

## Connects To
- **Ch 4**: Designing text and understanding font weights.
- **Ch 5**: Working with color and adjusting contrast.
