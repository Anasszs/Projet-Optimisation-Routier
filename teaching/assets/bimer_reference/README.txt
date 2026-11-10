BIMER REPORT REFERENCE - MEASURED DESIGN
=======================================

Source: user-supplied template_imt_mines_ales_bimer.pdf, five A4 pages.
The source PDF is unchanged. All five pages were rendered and visually
reviewed. design_spec.json records exact measured geometry, type hierarchy,
colour interpretation and the incomplete-font audit.

The cover is a strong geometric composition: cyan field, navy upper-left
triangle, pink upper-right triangle, white lower-left triangle with the
official school/state block, white bold title and white light-serif subtitle.
The interior is genuinely two-column, with a 12 pt sans-serif body, cyan
serif section headings, pink introductions/emphasis, and generous white
space at the right-hand corners on odd pages. There is no interior logo,
running header, footer line, or decorative border.

DECLARATIVE COVER GEOMETRY

Coordinates below are normalized to page width and height, origin top left.
They reproduce the measured A4 layout. Use the IMT colour definitions from
imt_course.sty. The source diagonals are near 45 degrees: its grid has ten
cells across and fourteen cells down. For a landscape adaptation, adjust
triangle leg lengths in physical units if exact 45-degree diagonals matter.

  \begin{tikzpicture}[remember picture,overlay]
    \begin{scope}[shift={(current page.north west)},
                   x=\paperwidth,y=-\paperheight]
      \fill[IMTCyan] (0,0) rectangle (1,1);
      \fill[IMTNavy] (0,0)--(.30,0)--(0,.214286)--cycle;
      \fill[IMTPink] (.40,0)--(1,0)--(1,.428571)--cycle;
      \fill[white] (0,.428571)--(0,1)--(.80,1)--cycle;
    \end{scope}
  \end{tikzpicture}

The main title is Helvetica Bold 30 pt, left aligned at 21 mm, with baseline
92.795 mm below the top. The Archer Light 30 pt subtitle has baselines at
109.495, 122.195, and 134.895 mm (36 pt leading). Both are white, uppercase.

The original school logo has about 49.7 mm ink width, at x=21 mm and y=249 mm.
When reusing the supplied official charter block asset with its clear-space
canvas, an outer width near 94.5 mm, left near 14 mm and top near 242 mm,
recreates that school-logo scale and position while preserving the original
block proportions. Place the unmodified official block entirely within the
white region. The secondary mark unique to the source is not included among these
reusable assets.

INTERIOR GEOMETRY AND FOLIOS

A4 side/top/bottom margins: 10.5 mm; two 92.383 mm columns; 4.233 mm gutter.
Column left edges: x=10.5 mm and x=107.117 mm. Body: Helvetica 12 pt with
14.4 pt leading; justified, no first-line indent, about 8.5 pt paragraph gap.
Subheads: Archer Bold 11 pt/13.2 pt, cyan and uppercase. Minor headings:
Archer Bold 10 pt, black. Introductory lead: Archer Semibold 10 pt/12 pt,
pink small capitals. References: Helvetica 9 pt/10.8 pt.

Only odd interior pages have the two right-edge triangles:
  cyan: (168,0), (210,0), (210,42.429) mm;
  pink: (210,240.500), (210,297), (154,297) mm.
Even pages are plain white. The folio uses Helvetica 16 pt, baseline
y=292.233 mm, centered at x=5.25 mm on even pages (black) or x=204.75 mm
on odd pages (white on pink).

Text must avoid those triangle regions. Source page 3 starts its right
column around y=31.75 mm and ends around y=243 mm. Reserve such space, use
shaped text areas, or use smaller related corner shapes for course pages
whose formulae/tables require a wider reading area. Full-width material can
interrupt the two-column prose while retaining the same editorial hierarchy.

FONT AVAILABILITY AND COLOUR

The template embeds only incomplete font subsets. Archer Light has 22 glyphs,
Archer Semibold 39, and Archer Bold 50; Helvetica Bold has only 17 populated
outlines. CID Helvetica lacks a reusable Unicode cmap. None is a complete
font suitable for arbitrary editable course text. No fonts were extracted
into this deliverable. Nimbus Sans is an installed metric-compatible
Helvetica surrogate. Bitstream Charter or Latin Modern Roman can provide a
serif contrast, but neither is Archer nor metric-compatible with Archer.

The BIMER PDF's colour-managed print values convert approximately to cyan
#00B4D5, pink #E72557 and navy #162640 in PyMuPDF. Use the charter's declared
digital palette consistently when implementing the design: #00B8DE,
#F14862 and #14223C. This is a deliberate palette choice, not a claim that
the RGB conversion of the print PDF is identical.
