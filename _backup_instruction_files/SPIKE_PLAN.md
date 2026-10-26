# Native UI Stack Spike — PySide6 vs C++/Qt

## Purpose
Run a throwaway, equivalent native-desktop prototype in Python/PySide6 and C++/Qt to inform the implementation-stack decision for the fresh-scratch analytics product. This spike is not product code and is not a parity implementation.

## Product implementation decision
The user selected macOS-first targets: Apple Silicon M1 or newer, macOS 14.4+, with release checks on Sonoma 14.4, Sequoia 15, and Tahoe 26. The later first Linux support target is Ubuntu 24.04 LTS x86_64; elementary OS is an optional desktop-experience check. Stage 1 now uses a Python/PySide6 backend with a Qt Quick/QML frontend. The disposable comparison bundles below remain Qt Widgets prototypes and are not production packages.

## Follow-up probe: classic Report view
The original generic placeholder-canvas probe did not represent the product direction and cannot answer the user’s visual/workflow question. Build matched, disposable Qt Widgets prototypes in PySide6 and C++/Qt that read as a classic report-authoring workspace, using Microsoft’s published documentation as a behavioral/layout reference. The user selected classic panes (not on-object interaction). This is not product code, a full clone, or a parity claim.

### Bounded UI and behavior
- Native desktop only: no browser, webview, QML migration, Microsoft source, logo, icons, screenshots, or copied assets. Use original neutral styling.
- Shared workspace anatomy: ribbon with Home/Insert/Modeling/View/Help tabs and command search; left Report/Data/Model switcher; central gray work area with white report page; bottom page tabs and add-page control; right Filters, Visualizations (Build/Format and a small supported chart set), and searchable Data panes.
- Use the shared deterministic sales CSV and show a populated Sales overview with KPI cards and monthly column / regional bar visuals.
- Equivalent supported interactions in both stacks: visual selection updates pane context; selecting a region bar filters KPIs and sample visual values and can be reset; selected chart switches among a small supported set (column/bar/line); add/switch between Overview and an in-memory blank page; Report/Data view switching and CSV preview. Model remains a clearly labelled stub. Unsupported commands should not pretend to work.
- Use Qt Widgets and a small custom-painted report surface, not an external chart library. Keep the sample data calculations deterministic and implementations/test scenarios equivalent.
- Do not claim DAX, Power Query/M, model relationships, full filter/highlight semantics, report persistence, full visual gallery, or accessibility conformance. Basic tested-control focus and accessible names are in scope.

### Comparison and evidence gates
The earlier spike comparison still needs fresh, equivalent smoke suites and builds to produce a useful comparison. It covers fixture parsing/aggregates, pane/ribbon structure, visual selection/type changes, region filter/reset, page state, Report/Data navigation, and basic accessibility names/focus. Include quoted CSV data in parser coverage so C++ does not silently diverge from Python. Compare both apps at the same viewport and fixture; record source size, setup/build effort, startup and interaction timing with conditions. Treat headless timing as limited evidence, not production performance. Rebuild before packaging assessment; stale app bundles and host-specific Qt plugin paths are not portability evidence. Report package launch failure honestly. The product's current Stage 1 uses PySide6; the spike results remain evidence for any later stack reconsideration.

The Linux target is selected as Ubuntu 24.04 LTS x86_64, but packaging remains blocked until a clean target is available. Do not install system packages or provision/start a VM without explicit approval.

## Environment and comparison protocol
- Host: Apple Silicon macOS 27.0.1, Python 3.14.4, Apple Clang 21.0.0.
- PySide6/Qt 6.11.2 is installed. Homebrew Qt 6.11.2 and CMake 4.4.4 were installed for the C++ probe after the initial environment scan; earlier notes that these tools were unavailable were historical, not current.
- Xcode and `xcodebuild` are unavailable; Command Line Tools are present.
- Parallels is installed, but the only configured VM is Windows 11; no Linux VM/container runtime is available.
- Compare identical UI scope, fixture, viewport, and tests. Record source size, setup/build steps, startup and interaction/render latency with conditions, functional/accessibility gaps, and packaging outcome. Treat headless timings as limited evidence rather than production performance.
- Rebuild both packages from current source before assessing them. Existing app bundles have unresolved runtime/Qt plugin issues and do not prove self-contained distribution; report failures honestly.
- Linux requires a declared distribution/architecture and clean target; it remains blocked here. Do not provision a new target without explicit approval.
- Include version-specific framework and licensing caveats. Do not treat Qt support as universal Linux support.

## Gate
No production stack selection follows automatically. Recommend a stack only with caveats and an explicit account of missing Linux/Xcode evidence. All prototypes and measurements remain disposable spike artifacts.
