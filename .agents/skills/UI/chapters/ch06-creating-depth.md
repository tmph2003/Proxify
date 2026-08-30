# Chapter 6: Creating Depth

## Core Idea
You can create depth and elevation in an interface without relying on skeuomorphic design, primarily by emulating a consistent light source and using layered shadows.

## Frameworks Introduced
- **Emulate a Light Source**:
  - When to use: When adding shadows, highlights, or gradients.
  - How: Pick an imaginary light source (usually straight above the element). Flat elements facing the light are lighter, elements facing away are darker. A top light source means drop shadows fall below the element, and the top edge might have a subtle 1px inner highlight.
- **Two-Part Shadows**:
  - When to use: When creating drop shadows for cards, modals, or floating elements.
  - How: Don't use a single blur. Use a small, dark, tight shadow to represent the contact shadow (where the element touches the surface), and a larger, lighter, more blurred shadow for the ambient shadow (the overall light being blocked).

## Key Concepts
- **Elevation**: Different elements sit at different heights. A modal sits higher than a dropdown, which sits higher than a card. The higher the element, the larger and softer the shadow should be.
- **Flat Depth**: Even if you don't use shadows, you can create depth by overlapping elements or using solid colored blocks as "fake" shadows behind an element.

## Mental Models
- **Overlapping Elements**: Breaking a strict grid by having a card overlap the boundary of two background colors (e.g., pulling a card up into a colored hero section) immediately creates a sense of depth and layers.

## Anti-patterns
- **Inconsistent Lighting**: Having a shadow drop to the bottom-right on one card, but straight down on another. Keep the light source global.
- **Harsh Shadows**: Pure black shadows with high opacity look dirty. Use very low opacity (5-15%) and a large blur for a natural look.

## Key Takeaways
1. A realistic shadow is composed of two parts: contact and ambient.
2. The further an object is from the surface (higher elevation), the larger and softer its shadow.
3. You can create depth without shadows purely by overlapping elements.

## Connects To
- **Ch 5**: Working with Color (shadows are just darker colors).
