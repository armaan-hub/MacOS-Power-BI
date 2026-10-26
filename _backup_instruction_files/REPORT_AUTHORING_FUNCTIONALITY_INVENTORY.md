# Report Authoring Functionality Inventory

**Research date:** 2026-10-08. **Scope:** End-to-end Power BI Desktop Report Authoring and Visuals capabilities, compared with the current Analytics Studio project. "A to Z" here covers creating reports, adding visuals, configuring field wells, applying formats, organizing pages, and adding static components.

> The master roadmap is [POWER_BI_FUNCTIONALITY_ROADMAP.md](</Users/armaan/Power BI tool/POWER_BI_FUNCTIONALITY_ROADMAP.md>).

## 1. Power BI Desktop: the full Report Authoring journey

1. **Canvas and Page Management.** A PBIX report contains multiple pages, each with its own size (16:9, 4:3, custom), background, and wallpaper. Pages can be added, deleted, renamed, hidden, and duplicated. Users can configure page tooltips and cross-report drillthrough pages.
2. **Visual Chooser and Canvas Placement.** Users add visuals via the Visualizations pane or ribbon. Visuals are placed on the canvas and can be resized, snapped to grid, aligned, distributed, and layered (z-order).
3. **Field Wells (Data Binding).** Each visual type exposes distinct field wells (e.g., X-axis, Y-axis, Legend, Tooltips). Users drag data fields or measures into these wells. Aggregations (Sum, Average, Count, default summarizations) are configurable per field if it's not a measure.
4. **Formatting Pane.** Every visual has a robust properties pane grouped into general (position, title, background, border, shadow) and visual-specific formatting (colors, data labels, legend placement, axis scales).
5. **Static Elements.** Users can insert Text Boxes, Shapes, Buttons, and Images. Buttons can have associated actions (bookmark navigation, drillthrough, web URL, page navigation).
6. **Themes and Styling.** Reports support global JSON-based themes defining color palettes, font families, and default visual formatting properties.
7. **Visual Interactions.** Selecting a data point in one visual cross-highlights or cross-filters other visuals on the same page. Users can edit these interaction behaviors via the Format menu.
8. **Clipboard Actions & Format Painter.** Visuals, components, and their formats can be copied and pasted across pages. Format Painter applies styling configurations from one visual to another.

## 2. What Analytics Studio actually supports

Currently, Analytics Studio provides a built-in QML Report view (`Main.qml`, `ReportView.qml`) that supports tracking report pages and very basic charts (revenue bar, column, line) that don't yet feature fully dynamic field wells or comprehensive formatting.

To map Power BI 1:1, we must break down "7. Report authoring and visuals" into distinct iterative implementation milestones.
