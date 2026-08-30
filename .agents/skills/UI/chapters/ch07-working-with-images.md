# Chapter 7: Working with Images

## Core Idea
Images can make or break a design. Using good photos is critical, but managing contrast over them and sizing them deliberately is what makes the UI look professional.

## Frameworks Introduced
- **Text over Images (Consistent Contrast)**:
  - When to use: When overlaying text on a background photo (like a hero section).
  - How: A photo has dark and light spots. To guarantee text is readable, you must control the contrast. Use a solid color overlay (with opacity), a text shadow (to outline the text), or a gradient overlay that gets darker exactly where the text sits.
- **Intended Sizes**:
  - When to use: When sizing icons or illustrations.
  - How: Don't scale up a 16x16 icon to 32x32. It will look chunky and disproportionate. Icons are designed for a specific size. If you need a big icon, draw a big icon or place the small icon inside a larger container (like a colored circle).

## Key Concepts
- **User-Uploaded Content**: Users upload bad, low-res, improperly cropped photos. Design your UI to handle bad photos gracefully (e.g., center crop, place them in constrained shapes like circles, or use subtle overlays to mute their impact).

## Mental Models
- **Use Good Photos**: It sounds obvious, but a great UI with terrible stock photography looks like a terrible UI. Invest in good imagery, or omit it altogether.

## Anti-patterns
- **Blowing up small icons**: Scaling a 16px icon to 64px makes it look comically thick and out of place with the rest of the typography.
- **Relying on photo darkness**: Don't just pick a "dark" photo and put white text on it. A user might change the photo later. Always enforce contrast programmatically via overlays or shadows.

## Key Takeaways
1. Never assume text on an image will be readable without an overlay or shadow.
2. Don't scale icons outside of their intended size; put them in a container if you need them to occupy more space.
3. Constrain user-uploaded photos aggressively.

## Connects To
- **Ch 2**: Hierarchy is Everything (managing contrast).
