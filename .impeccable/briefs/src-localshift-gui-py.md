# Surface Brief: LocalShift Desktop UI

Scope: Native PySide6 converter, queue, PDF catalog, radial menu, and settings.
Mode: Operate.

Audience: Windows users completing a local conversion or PDF task. The first
action is to add or browse for a file, choose a target, and verify its output.
The UI must preserve existing workflows, supported-format truth, explicit
global-gesture consent, source immutability, keyboard access, and dark/light
theme choice. External drag-source compatibility and mixed-DPI behavior remain
unverified.

Open decisions: physical DPI and mixed-monitor behavior, and external drag-source
compatibility, require operator verification.

## Direction contract

**THESIS:** Make the source-to-output decision the visual center; refuse the
generic dashboard where every card and shortcut competes equally.

**OWN-WORLD:** Use a restrained proof-sheet vocabulary: ink-like dark surfaces,
quiet paper light surfaces, one rust accent, crisp dividers, and compact native
controls. Keep detail functional and avoid gradients or decorative glyphs.

**STORY:** Users can see what they are converting, choose a destination and
format, and understand that processing stays local and originals remain intact.
Search makes the PDF suite discoverable; the radial wheel makes format choice
direct and contextual.

**FIRST VIEWPORT:** Keep primary navigation at left, a concise task heading and
theme/quick-format actions above, the drop target and queue in the main column,
and recent work in a narrower utility column. Put destination and Convert at
the queue foot; collapse secondary columns at minimum width.

**FORM:** Native Windows utility, Operate mode; user-selected “Print-room proof
sheet” direction, code-led, rank user-selected; seed:1886ef77ad56e40d.

**FINISH:** unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
