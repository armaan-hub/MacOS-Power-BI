# Report Authoring Implementation Timeline

This timeline maps the "7. Report authoring and visuals" lane from the master roadmap into discrete, testable development increments for Analytics Studio, paralleling how we handled data import and DAX.

## Track G: Report Authoring and Visuals

### Phase G1: Canvas and Visual Lifecycle Foundation
* **G1.1 Page management:** Complete rename, delete, duplicate, hide, and reorder report pages natively; ensure proper save/reopen project state.
* **G1.2 Visual instantiation and selection:** Add a visual chooser picking from built-in types. Place, select, resize, and move visuals on a grid layout. Save/remove/reopen lifecycle for visual objects.
* **G1.3 Static components:** Text boxes, generic shapes, and images. Support persistence and basic properties.

### Phase G2: Field Wells and Data Binding
* **G2.1 Dynamic field wells:** Create per-visual configurable data bucket UI (X-axis, Y-axis, Tooltips) bound to the `model` columns.
* **G2.2 Default aggregations:** Implicit summarizations (Sum, Count, Average) for numeric fields dropped into measure wells, bypassing explicit DAX definitions.
* **G2.3 Data update propagation:** Chart rendering reacts correctly to model refreshes, active table changes, and filter context updates.

### Phase G3: Formatting and Properties
* **G3.1 Visual formatting pane:** General visual properties (X/Y coordinates, width, height, title text/toggle, background color, borders).
* **G3.2 Data colors and labels:** Per-series styling, data label toggles, and legend configurations.
* **G3.3 Format Painter and Clipboard:** Copy, Paste, Duplicate, and Format Painter across pages mapping visual definitions in JSON.

### Phase G4: Advanced Authoring Commands
* **G4.1 Z-order and Grouping:** Bring Forward/Send Backward layering. Grouping multiple visuals into single draggable units.
* **G4.2 Themes:** App-wide color palettes and default visual styling derived from a standard JSON theme file.
* **G4.3 Buttons and Actions:** UI buttons mapped to basic page-navigation actions.
