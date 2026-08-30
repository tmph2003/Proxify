# Chapter 1: Starting from Scratch

## Core Idea
When starting a new design, begin with a core piece of functionality instead of the overall layout, and systematically restrict your design choices (colors, spacing, typography) from the very beginning.

## Frameworks Introduced
- **Feature-First Design**: 
  - When to use: Starting a brand new application.
  - How: Don't design the "shell" (top nav, sidebar). Start with an actual feature (e.g., a "search flights" form). You cannot know how the shell should look until you have features to put inside it.
- **Systematize Everything**:
  - When to use: When deciding on exact pixel values for spacing, sizes, and fonts.
  - How: Define a constrained set of values in advance (e.g., spacing scale: 4px, 8px, 12px, 16px, 24px) rather than nudging elements 1px at a time. It dramatically speeds up workflows and guarantees consistency.

## Key Concepts
- **Personality**: The "vibe" of a site, largely dictated by font choice, color, border radius, and language.
- **Grayscale First**: Designing in grayscale forces you to use spacing, contrast, and size for heavy lifting before relying on color.

## Mental Models
- **Think of design as process of elimination**: When you limit your choices (e.g., using a predefined scale), you just pick the value that isn't obviously wrong, rather than agonizing over infinite possibilities.
- **Think like a pessimist**: Expect features (like attachments on a comment system) to be hard to build. Don't design them until you're ready to build them.

## Anti-patterns
- **Over-investing in high fidelity early**: Agonizing over shadows and typefaces before the layout is validated.
- **Designing the whole app before implementation**: Leads to frustration when edge cases appear. Work in short cycles: design a simple feature, build it, then move on.

## Key Takeaways
1. Start with a feature, not a layout.
2. Detail comes later; hold the color and use grayscale to validate layout.
3. Choose a personality deliberately (rounded corners = playful; sharp = serious; blue = safe).
4. Limit your choices by defining sizing and spacing systems in advance.

## Connects To
- **Ch 3**: Building the spacing system.
- **Ch 4**: Building the type scale.
