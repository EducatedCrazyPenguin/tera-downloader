---
name: Tera
description: A warm, legible Windows download workspace in the Cinema programme direction.
colors:
  primary: "#A5262D"
  primary-hover: "#8B2027"
  primary-pressed: "#711B20"
  paper: "#FAF8F4"
  ink: "#282624"
  muted: "#625C56"
  field: "#FFFFFF"
  selection: "#E9D6D3"
  disabled-background: "#E5DDD7"
  disabled-text: "#6A625C"
  progress-trough: "#E7E1D9"
typography:
  display:
    fontFamily: Georgia
    fontSize: 22pt
    fontWeight: 400
  headline:
    fontFamily: Segoe UI
    fontSize: 16pt
    fontWeight: 700
  title:
    fontFamily: Segoe UI
    fontSize: 12pt
    fontWeight: 700
  filename:
    fontFamily: Segoe UI
    fontSize: 11pt
    fontWeight: 400
  body:
    fontFamily: Segoe UI
    fontSize: 10pt
    fontWeight: 400
  label:
    fontFamily: Segoe UI
    fontSize: 10pt
    fontWeight: 700
rounded:
  square: 0px
spacing:
  field-inset: 4px
  control-gap: 6px
  action-gap: 8px
  header-gap: 10px
  settings-inset: 12px
  page-inset-y: 14px
  page-inset-x: 20px
components:
  button-primary:
    backgroundColor: "{colors.primary}"
    textColor: "{colors.field}"
    typography: "{typography.label}"
    rounded: "{rounded.square}"
    padding: 6px 10px
  button-primary-hover:
    backgroundColor: "{colors.primary-hover}"
  button-primary-pressed:
    backgroundColor: "{colors.primary-pressed}"
  button-primary-disabled:
    backgroundColor: "{colors.disabled-background}"
    textColor: "{colors.disabled-text}"
  link-field:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.body}"
    rounded: "{rounded.square}"
    padding: 5px 8px
  filename-row:
    backgroundColor: "{colors.field}"
    textColor: "{colors.ink}"
    typography: "{typography.filename}"
  filename-row-selected:
    backgroundColor: "{colors.selection}"
    textColor: "{colors.ink}"
  tab-selected:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.primary}"
    padding: 8px 14px
---

# Design System: Tera

## Overview

**Creative North Star: "Cinema programme"**

Warm paper, charcoal filenames and restrained red actions give this Windows utility the calm of a printed cinema programme. Georgia gives the Tera name a small editorial signature; Segoe UI and native controls keep the working interface familiar. Filenames receive more emphasis than occasional configuration.

This records the built Python/Tkinter interface and its `clam` ttk theme. It is a desktop system: native menus, tabs, scrollbars, file dialogs and keyboard behavior remain part of its form language. No web layout, mobile variant or generated photographic asset is implied.

**Key Characteristics:**

- Warm paper surrounding white work areas.
- One restrained red accent for primary actions, selection cues and progress.
- An editorial title above legible filename tables.
- Square native controls and flat, bordered surfaces.
- Expanding content with persistent transfer controls.

**Evidence: 3/3 — The recorded tokens and visible layout were checked against `tera_gui.py`, `desktop_integration.py`, `build_windows.py` and the two supplied native captures in `.impeccable/review/`. This documentation pass did not independently run the application, tests, installer or a live provider.** Product intent comes from `PRODUCT.md` and `.impeccable/surfaces/tera-gui-py.md`; those documents do not establish runtime results.

## Colors

The palette uses warm, low-chroma neutrals with a single deep red accent. The frontmatter owns exact values; names below describe their application.

### Primary

- **Programme red** (`primary`): Download now, Download selected, progress fill, selected tab text and the link-field caret/focus treatment. The existing authored geometric T icon uses the same red with white geometry in tray and packaging code.
- **Deep red** (`primary-hover`, `primary-pressed`): ttk primary-button active and pressed states, respectively.

### Neutral

- **Warm paper** (`paper`): root workspace, frames, selected tab background and settings canvas.
- **Charcoal** (`ink`): working text and selected filename text.
- **Warm grey** (`muted`): empty-queue guidance.
- **White work area** (`field`): editable fields and filename lists; also primary-button and icon foreground.
- **Blush selection** (`selection`): selected table rows and selected link text.
- **Quiet disabled pair** (`disabled-background`, `disabled-text`): explicitly mapped primary-button disabled states.
- **Stone trough** (`progress-trough`): background of the continuous progress indicator.

**The Restrained Accent Rule.** Use programme red for established action and state roles; keep the surrounding workspace neutral.

## Typography

Georgia is the display family. Segoe UI is the working family. These are named Tk fonts with positive point sizes; they scale through Tk rather than CSS pixels. No custom fallback stack, line height, tracking or font download is authored.

### Hierarchy

- **Display:** regular Georgia for the Tera title.
- **Headline:** bold Segoe UI for the Help / About version heading.
- **Title:** bold Segoe UI for the Firefox-login heading.
- **Filename:** regular Segoe UI for all Treeview rows, deliberately larger than general controls.
- **Body:** regular Segoe UI for controls, labels, links and supporting copy.
- **Label:** bold Segoe UI for primary buttons and table headings.

**The Filename First Rule.** Preserve the larger filename face and readable row rhythm; do not gain density by shrinking filenames below surrounding controls.

## Layout

The implemented initial client area is 1020×760; the minimum is 880×680. The outer frame uses the page insets in frontmatter. Header and footer are packed before the expanding notebook so the central list gives up space first. This is window resizing within a native desktop application, with no device breakpoints.

The Downloads surface places a two-line share-link field alongside Download now and the optional Choose videos action. Destination, Change… and File actions sit immediately below. The filename queue expands through the remaining area. Name columns start at 320 pixels with a 200-pixel minimum; status columns start at 190 with a 150-pixel minimum. Other columns remain reachable through horizontal scrolling. A vertical scrollbar handles larger batches.

Treeview row height is `int(20 * tk_scaling)` pixels, computed when the application is created. The reviewed minimum-window capture at Tk scaling 2.0 shows the heading and three complete queue rows. This is capture evidence for that size and scale, not a guarantee for arbitrary text scaling. Font sizes remain point based; widget padding and column widths are Tk pixel dimensions.

Settings is a main notebook tab also reached through the header Settings action. Its General, Firefox login, Run limits and Help / About pages use inset content on a two-axis scrollable canvas. Page Up/Page Down and the scoped mouse wheel support vertical movement. Review and History retain their own search, sorting and maintenance controls.

**The Persistent Controls Rule.** Keep status, progress, Start queue/Resume, Pause now and Cancel queue below the expanding notebook. Extra file maintenance belongs in the existing File actions menu rather than another permanent queue toolbar.

## Elevation & Depth

The application authors no shadows or animated elevation. Paper, white fields, selection tint, one-pixel link-field boundaries and the `clam` theme's native-looking borders separate surfaces. Native menus and dialogs keep their platform behavior; their exact appearance is not redefined as a custom token set.

## Shapes

The visible vocabulary is rectangular, square-cornered controls and aligned table cells. Button padding, tab padding and field insets are deliberate; decorative pills and rounded cards are absent. Do not replace native affordances with glyph-only substitutes. The geometric white T on a red square is an existing authored icon, produced by drawing rectangles in the tray/build code, not an AI-generated raster asset.

## Components

### Buttons

Primary buttons use programme red, bold label typography and white text, with explicit active, pressed and disabled mappings. Secondary buttons inherit `clam` theme borders and state feedback with the shared button padding. Focus follows Tk/ttk behavior; no custom motion or hover transform is authored.

### Inputs / Fields

The share-link input is a two-line, word-wrapped native Text widget: white background, charcoal text, red caret and focus highlight, blush text selection, solid border and the link-field padding. Destination and other entries use the shared white TEntry background and field inset. Comboboxes retain native readonly selection where configured. Error and hold explanations are plain text in the existing status/help areas, not newly invented colored alert cards.

### Navigation

The main notebook contains Downloads, Choose videos, History and Settings. Selected tabs use programme-red text on paper. The header Add links returns to Downloads; Settings selects its existing page. Settings has its own nested notebook. Preserve tab labels, native keyboard focus and available scrollbars; no mobile navigation treatment exists.

### Filename Tables

Downloads, Choose videos and History share Treeview typography, bold headings, white rows and blush selection. Column headings communicate meaning without relying on color. The Choose videos table retains its Download column, Space/click selection and explicit Download selected action. Review is optional in the quick-start path.

### File Actions

A native Menubutton opens state-aware Move up, Move down, Remove pending, Restart from zero, Retry selected, Skip and Pause after file commands, followed by Change folder… and Rename…. Existing command enablement is reused. Menu placement reduces permanent chrome while preserving maintenance capabilities.

### Transfer Strip

The footer pairs plain-language status with byte totals, speed and ETA; each label wraps against half the available width. A thin red progressbar on the stone trough spans the width. Start queue changes to Resume for manual holds; Pause now and Cancel queue stay in the persistent action row. State determines enablement.

### Settings

General groups destination preferences, favorites, explicit tray use and optional notifications. Firefox login groups profile selection and login/check/disconnect actions. Run limits groups bandwidth, time, budget and daily-window controls with explanatory copy. Help / About supplies version, recovery guidance and diagnostics. These remain native controls on scrollable paper surfaces.

## Do's and Don'ts

### Do:

- **Do** use warm paper around white work areas and reserve programme red for established action and state roles.
- **Do** preserve larger filenames, visible table headings and horizontal access to overflow columns.
- **Do** keep transfer status and the essential queue controls outside the shrinking content area.
- **Do** reuse native menus, notebook tabs, scrollbars and keyboard behavior.
- **Do** check the minimum window with enlarged text when changing permanent controls or row density.

### Don't:

- **Don't** turn occasional maintenance into another permanent queue toolbar.
- **Don't** replace readable action labels with decorative glyph-only controls.
- **Don't** add gradients, shadows, pills or animated transitions as if they belonged to the built system.
- **Don't** treat the sidecar's HTML/CSS preview translations or synthesized tonal ramps as shipped native widgets or new application tokens.
