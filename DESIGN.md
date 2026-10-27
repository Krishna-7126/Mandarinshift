---
name: LocalShift
description: A restrained native desktop workspace for local file conversion and PDF tasks.
colors:
  primary: "#a64c38"
  primary-hover: "#8f3f2e"
  primary-pressed: "#783528"
  dark-focus: "#e49a82"
  dark-canvas: "#191b19"
  dark-sidebar: "#202320"
  dark-control: "#272a26"
  dark-surface: "#222522"
  dark-field: "#1b1d1b"
  dark-ink: "#f1efe7"
  dark-muted: "#b6b8af"
  dark-divider: "#3b3e39"
  dark-selection: "#71483d"
  light-canvas: "#f2f0e9"
  light-sidebar: "#e8e5dc"
  light-control: "#eeece5"
  light-surface: "#fbfaf6"
  light-field: "#fffdf7"
  light-ink: "#272825"
  light-muted: "#545650"
  light-divider: "#d5d1c7"
  light-control-divider: "#c5c2b9"
  light-selection: "#ead8d0"
typography:
  display:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "20px"
    fontWeight: 700
  title:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "17px"
    fontWeight: 700
  body:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "13px"
    fontWeight: 400
  label:
    fontFamily: "Segoe UI, sans-serif"
    fontSize: "14px"
    fontWeight: 700
rounded:
  sm: "5px"
  md: "7px"
spacing:
  compact: "4px"
  sm: "8px"
  md: "10px"
  lg: "12px"
  xl: "14px"
  2xl: "16px"
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
    textColor: "#ffffff"
    rounded: "{rounded.sm}"
  button-secondary:
    backgroundColor: "{colors.dark-control}"
    textColor: "{colors.dark-ink}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  button-secondary-light:
    backgroundColor: "{colors.light-surface}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.sm}"
    padding: "7px 13px"
  input:
    backgroundColor: "{colors.dark-field}"
    textColor: "{colors.dark-ink}"
    rounded: "{rounded.sm}"
    padding: "6px 9px"
  input-light:
    backgroundColor: "{colors.light-field}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.sm}"
    padding: "6px 9px"
  card:
    backgroundColor: "{colors.dark-surface}"
    textColor: "{colors.dark-ink}"
    rounded: "{rounded.md}"
    padding: "10px"
  card-light:
    backgroundColor: "{colors.light-surface}"
    textColor: "{colors.light-ink}"
    rounded: "{rounded.md}"
    padding: "10px"
---

# Design System: LocalShift

## Overview

**Creative North Star: "Print-room proof sheet"**

LocalShift's native interface treats conversion as a practical, inspectable job: source files, target formats, destination, and outcome remain legible as a compact work surface. Its ink-dark and paper-light themes use a single rust accent, crisp dividers, and compact Segoe UI controls. The same palette and surface logic carry from the converter into PDF tasks, settings, and the custom format wheel.

The interface is flat and workmanlike rather than ornamental. The circular radial chooser is a functional signature, not a decorative motif: its format petals, file hub, and hint pills directly communicate a contextual conversion choice. Local processing and source-preservation copy appear as small utility information rather than brand decoration.

**Key Characteristics:**
- Ink-dark or quiet paper-light surfaces, with a consistent rust action color.
- Compact native controls organized by clear strokes and tonal steps, not shadow.
- Source-to-output choices stay central; secondary details recede or reflow.
- A custom radial format chooser provides a direct, contextual alternative to the queue.

## Colors

The palette pairs a restrained rust action color with two neutral theme families; the stylesheet and radial menu implement explicit dark and light values.

### Primary
- **Proof-room Rust** (`{colors.primary}`): The common action color for conversion and other primary actions.
- **Rust Hover** (`{colors.primary-hover}`) and **Pressed Rust** (`{colors.primary-pressed}`): Darker interaction states for primary buttons.

### Neutral
- **Ink Canvas / Surface / Sidebar / Control / Field** (`{colors.dark-canvas}`, `{colors.dark-surface}`, `{colors.dark-sidebar}`, `{colors.dark-control}`, `{colors.dark-field}`): Dark theme background, cards, navigation rail, secondary controls, and editable fields.
- **Paper Canvas / Surface / Sidebar / Utility Strip / Field** (`{colors.light-canvas}`, `{colors.light-surface}`, `{colors.light-sidebar}`, `{colors.light-control}`, `{colors.light-field}`): Corresponding light theme layers, from warm window background to near-white content and field surfaces; the utility-strip tone is used on tab bars and table headings.
- **Light and Dark Ink** (`{colors.dark-ink}`, `{colors.light-ink}`): Main text in their respective themes.
- **Muted Ink** (`{colors.dark-muted}`, `{colors.light-muted}`): Secondary descriptions, destination hints, and other supporting copy.
- **Dividers** (`{colors.dark-divider}`, `{colors.light-divider}`, `{colors.light-control-divider}`): Card outlines, table structure, and quiet separators; the secondary light control uses its more distinct border.
- **Selection Wash** (`{colors.dark-selection}`, `{colors.light-selection}`): Selected table and control states.
- **Dark Focus Rose** (`{colors.dark-focus}`): Visible focus treatment over dark surfaces; light controls use the rust focus color.

**The Two-Ink Rule.** Keep each surface, its text, and its separators within one theme pairing; do not mix the dark and light neutral families on a single screen.

## Typography

**Display Font:** Segoe UI (with sans-serif fallback)  
**Body Font:** Segoe UI (with sans-serif fallback)  
**Label/Mono Font:** No separate label or monospace face is established.

**Character:** Compact, familiar Windows utility typography. Weight and size changes establish hierarchy without introducing a separate display voice.

### Hierarchy
- **Display** (700, 20px): Main task heading.
- **Title** (700, 17px): Brand name and dialog heading.
- **Label** (700, 14–15px): Queue count, drop target heading, catalog heading, and card title.
- **Body** (400, 13px): Default control and supporting copy.
- **Radial labels** (10–12pt, medium to demi-bold): Format names and short guidance painted into the custom wheel.

**The One-Family Rule.** Use Segoe UI throughout; distinguish task labels from supporting text through weight and observed size steps, not a second typeface.

## Layout

The main window is a fixed left navigation rail beside a flexible task area. In the converter, a central drop-and-queue work area carries file, format, destination, and Convert actions; recent work is a narrower utility panel when space allows. The PDF suite places search and category filtering above a scrollable, category-grouped tool catalog. Settings and task-specific forms use compact native rows and grouped fields.

The main window opens at 1020 × 680 and has a 760 × 560 minimum. The converter responds to its available width: below 1020px it hides the output-detail table column, below 900px it also hides the size column, and below 700px it hides the recent-work panel. The PDF tool catalog switches from three columns to two below 900px and one below 600px of catalog viewport width. Rendered review captures show light and dark states at both the larger and compact named window sizes; these are code and capture observations, not physical-display calibration.

Spacing is compact and repeated: common layout gaps and margins use 8–14px, with 4px for tight internal groupings and 16px around larger forms. Preserve usable control padding rather than compressing labels into the remaining width.

**The Reflow-By-Width Rule.** Keep the task actionable as space narrows: remove secondary converter details first, then the recent panel; make PDF catalog cards single-column at the narrowest observed viewport.

## Elevation & Depth

The system has no shadow vocabulary. It conveys depth through adjacent neutral tones, outlined cards and fields, separators, and selected-state fills. The radial wheel uses overlapping circles, an overlay tint, and a brighter selected petal as functional focus cues, not elevation shadows.

**The Flat Surface Rule.** Let tonal contrast and fine borders define the work surface; do not add drop shadows as a substitute for its existing dividers.

## Shapes

Most controls use gently rounded native rectangles: buttons and fields use a 5px radius, cards use 6–7px corners, and the drop target uses a dashed rectangular outline. Borders stay crisp and quiet. The radial chooser is the deliberate geometric exception: circular format petals orbit a round file hub, with rounded filename and instruction pills.

## Components

### Buttons
- **Character:** Compact, labeled actions with one rust primary and quieter outlined secondary actions.
- **Shape:** Softly rounded corners (5px).
- **Primary:** Rust fill, white text, and 7px × 13px padding; the Convert call-to-action uses slightly roomier 8px × 14px padding.
- **Hover / Focus:** Hover and pressed states deepen the rust; keyboard focus receives a contrasting 2px outline (rose on dark surfaces, rust on light).
- **Secondary:** Theme-surface fill, muted border, and left-aligned text for reversible or supporting actions.

### Cards / Containers
- **Character:** Quiet, flat work groupings separated from the canvas by one fine border.
- **Corner Style:** 6–7px on queue, recent, and status cards; the PDF suite tool card uses a similar outline.
- **Background:** Theme-specific surface colors; drop target uses a dashed border.
- **Shadow Strategy:** None; see Elevation & Depth.
- **Internal Padding:** Common panels use 8–10px; PDF tool cards use 11px vertical and 13px horizontal padding.

### Inputs / Fields
- **Character:** Native, compact controls that keep file names, format choices, and search directly editable.
- **Style:** Dark or light field fill, one-pixel divider, 5px corners, and 6px × 9px padding.
- **Focus:** Two-pixel contrasting outline, with a warmer rose in the dark theme.
- **Error / Disabled:** Disabled primary actions use a subdued theme-appropriate fill and muted text; status copy uses semantic success, warning, or error colors.

### Navigation
- **Character:** Persistent left rail with plainly named workflow destinations.
- **Style:** Transparent text buttons at rest, stronger surface on hover, and a restrained rust-tinted fill and text for the active destination. The rail retains its utility/status panel and Settings link.

### PDF Tool Card
Focusable button cards present a bold task title, muted explanation, and—when needed—an availability notice. Search and category filters act on the grouped, scrollable catalog; the card grid adapts between one, two, and three columns at the observed widths.

### Radial Format Wheel
The wheel surrounds a quiet file hub with circular petals for supported target formats. Hovering a petal offsets it outward and increases its contrast; filename and action hints sit in rounded pills above and below. Arrow keys, Enter, Escape, and number keys provide direct selection, so the geometry remains a functional control rather than decoration.

## Do's and Don'ts

### Do:
- **Do** use the rust primary consistently for the most important action and its active states.
- **Do** keep dark and light surfaces internally paired with their own ink and divider colors.
- **Do** use borders and tonal layering instead of shadows to separate work groups.
- **Do** preserve the queue-first workflow and the wheel as distinct, purposeful ways to choose a conversion.
- **Do** keep secondary converter columns and PDF catalog cards responsive at the code-defined width thresholds.

### Don't:
- **Don't** introduce gradients or decorative glyphs as ornament; this system uses flat surfaces and labeled controls.
- **Don't** flatten the PDF catalog into an ungrouped wall of equally styled actions.
- **Don't** treat an observed window-size capture as proof of physical-display, mixed-DPI, or assistive-technology validation.
