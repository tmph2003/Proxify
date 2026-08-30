# Chapter 6: Street signs and Breadcrumbs

## Core Idea
Navigation isn't just a feature of a website; it is the website. If users can't find their way around, the site might as well not exist.

## Frameworks Introduced
- **The Trunk Test**:
  - When to use: To evaluate any page's navigation effectiveness.
  - How: Imagine you've been blindfolded and dropped into a page deep in the site. You should be able to answer:
    1. What site is this? (Site ID)
    2. What page am I on? (Page name)
    3. What are the major sections of this site? (Sections)
    4. What are my options at this level? (Local navigation)
    5. Where am I in the scheme of things? ("You are here" indicators / Breadcrumbs)
    6. How can I search?

## Key Concepts
- **Persistent Navigation**: The set of navigation elements that appear on every page of a site (except perhaps forms).
- **Breadcrumbs**: A trail showing where the user is in the site's hierarchy (e.g., Home > Hardware > Tools > Hammers).
- **Site ID**: The logo or name of the site, usually in the top left corner, which should always link back to the homepage.

## Anti-patterns
- **Putting the current page name in the browser title only**: The page name needs to be a prominent, large heading on the page itself so the user knows they have arrived at the right place.
- **Tiny Breadcrumbs**: Hiding breadcrumbs or using non-standard separators. Use `>` because it visually implies motion and hierarchy.

## Key Takeaways
1. Web navigation compensates for the lost "sense of scale" and "sense of direction" we have in physical spaces.
2. Standard conventions for navigation (logo top left, search top right, utilities top right) exist for a reason—use them.
3. Every page needs a clear, prominent name that matches what the user clicked to get there.
