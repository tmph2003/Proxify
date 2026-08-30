# Chapter 5: Working with Color

## Core Idea
Stop relying on Hex or RGB, use HSL instead, and define a much larger, fixed palette of shades up front rather than relying on on-the-fly math or color picker guesswork.

## Frameworks Introduced
- **Ditch Hex for HSL**:
  - When to use: Whenever defining or adjusting colors.
  - How: HSL (Hue, Saturation, Lightness) maps to how humans perceive color. Adjust Lightness to create shades; adjust Saturation to control intensity. It makes tweaking colors predictable.
- **Define 5-10 Shades Up Front**:
  - When to use: When creating your color palette.
  - How: You need more colors than you think. Don't use a 5-hex-code generator. You need 8-10 greys, 5-10 shades of a primary color, and 5-10 shades of accent colors (red, yellow, green). Define them up front so you aren't guessing.

## Key Concepts
- **Lightness vs Saturation**: When creating dark shades of a color, if you only lower Lightness, the color often becomes muddy. You must increase Saturation to keep it vibrant, or slightly rotate the Hue toward the nearest bright color (like yellow or cyan).
- **Tinted Greys**: Pure greys look unnatural and cold. Add a tiny bit of saturation (e.g., matching your primary brand color's hue) to your greys to make them feel integrated and warm.

## Mental Models
- **Accessible doesn't mean ugly**: High contrast text is accessible. If a button color is too light to support white text, don't use white text—use a very dark shade of the same hue, or darken the button.
- **Don't rely on color alone**: For users with color blindness, a red error state needs a secondary indicator (like an icon or bold text).

## Anti-patterns
- **Using SASS functions for shades**: Don't use `lighten()` or `darken()` on the fly. It leads to 35 slightly different blues. Pick your 5-10 shades manually and stick to them.
- **Washed-out text**: White text on a colored background with lowered opacity looks bad. Pick a specific, lighter tinted color instead.

## Key Takeaways
1. HSL is strictly better than Hex/RGB for UI design.
2. A real UI needs a large palette. Prepare your shades before you start designing.
3. Add a slight tint to your greys to give the UI a cohesive feel.
4. If you have to squint to read it, it's not accessible.

## Connects To
- **Ch 2**: Emphasizing elements with color.
- **Ch 8**: Using accent borders.
