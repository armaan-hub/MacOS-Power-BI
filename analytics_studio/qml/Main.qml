import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ApplicationWindow {
    id: root
    visible: true
    width: 1740
    height: 1100
    minimumWidth: 1040
    minimumHeight: 680
    title: appController.windowTitle
    color: "#f1f2f3"
    property var studioController: appController
    property string ribbonTabName: "Home"
    property string lastWorkspaceView: ""
    property bool navigationVisible: true
    property bool filtersExpanded: false
    property bool dataPaneExpanded: false
    property bool visualizationsVisible: true
    property bool inspectorVisible: true
    property bool fitZoom: true
    property real reportZoom: 0.7
    property string fieldSearchQuery: ""
    property var kpiNames: ["Revenue", "Cost", "Margin", "Units", "Orders"]
    readonly property var kpiColors: ["#107C71", "#0078D4", "#8764B8", "#D9A300", "#C65911"]

    readonly property var ribbonTabs: ["File", "Home", "Insert", "Modeling", "View", "Optimize", "Help"]
    readonly property var dataHomeGroups: [
        { title: "Data", actions: [
            { label: "Get data", visibleLabel: "Get data", width: 48, iconName: "getData", commandId: "data.openPicker", splitGetData: true, description: "Choose a connector from the full data source picker." },
            { label: "Excel workbook", visibleLabel: "Excel\nworkbook", width: 50, iconName: "excel", commandId: "data.importExcel", description: "Import a workbook from an Excel file." },
            { label: "OneLake catalog", visibleLabel: "OneLake\ncatalog", width: 50, iconName: "databaseLink", commandId: "data.oneLakeCatalog", description: "Browse the OneLake catalog." },
            { label: "SQL Server", visibleLabel: "SQL Server", width: 44, iconName: "database", commandId: "data.sqlServer", description: "Connect to SQL Server." },
            { label: "Enter data", visibleLabel: "Enter\ndata", width: 38, iconName: "tableAdd", commandId: "data.source.enterData", description: "Enter data manually." },
            { label: "Dataverse", visibleLabel: "Dataverse", width: 46, iconName: "table", commandId: "data.dataverse", description: "Connect to Dataverse." },
            { label: "Recent sources", visibleLabel: "Recent\nsources", width: 46, iconName: "history", commandId: "data.recentSources", description: "Show a recently loaded data source." },
        ]},
        { title: "Queries", actions: [
            { label: "Transform data", visibleLabel: "Transform\ndata", width: 48, iconName: "tableEdit", commandId: "disabled.transform", available: false, description: "Data transformation is not available in this release." },
            { label: "Refresh", visibleLabel: "Refresh", width: 42, iconName: "refresh", commandId: "data.refresh", description: "Reload the linked data file." }
        ]},
        { title: "Workspace", actions: [
            { label: "Report view", visibleLabel: "Report\nview", width: 42, iconName: "report", commandId: "view.report", description: "Switch to Report view." },
            { label: "Model view", visibleLabel: "Model\nview", width: 42, iconName: "model", commandId: "view.model", description: "Switch to Model view." }
        ]}
    ]
    readonly property var ribbonDefinitions: [
        { groups: [
            { title: "Project", actions: [
                { label: "New project", visibleLabel: "New", iconName: "file", commandId: "project.new", description: "Create a new project." },
                { label: "Open project", visibleLabel: "Open", iconName: "open", commandId: "project.open", description: "Open a saved Analytics Studio project." },
                { label: "Save", visibleLabel: "Save", iconName: "save", commandId: "project.save", description: "Save the current project." },
                { label: "Save as", visibleLabel: "Save as", iconName: "saveAs", commandId: "project.saveAs", description: "Save a copy to another location." }
            ]},
            { title: "Data", actions: [
                { label: "Get data", visibleLabel: "Get data", width: 48, iconName: "getData", commandId: "data.openPicker", splitGetData: true, description: "Choose a connector from the full data source picker." },
                { label: "Export project", visibleLabel: "Export", iconName: "share", commandId: "disabled.export", available: false, description: "Export formats other than the project file are not available." }
            ]}
        ]},
        { groups: [
            { title: "Clipboard", actions: [
                { label: "Paste", visibleLabel: "Paste", width: 28, iconName: "paste", commandId: "disabled.paste", available: false, description: "Pasting report objects is not available in this release." },
                { label: "Cut", visibleLabel: "Cut", width: 28, iconName: "cut", commandId: "disabled.cut", available: false, description: "Cutting report objects is not available in this release." },
                { label: "Copy", visibleLabel: "Copy", width: 28, iconName: "copy", commandId: "disabled.copy", available: false, description: "Copying report objects is not available in this release." },
                { label: "Format painter", visibleLabel: "Format\npainter", width: 40, iconName: "formatPainter", commandId: "disabled.formatPainter", available: false, description: "Visual formatting is not available in this release." }
            ]},
            { title: "Data", actions: [
                { label: "Get data", visibleLabel: "Get data", width: 48, iconName: "getData", commandId: "data.openPicker", splitGetData: true, description: "Choose a connector from the full data source picker." },
                { label: "Excel workbook", visibleLabel: "Excel\nworkbook", width: 50, iconName: "excel", commandId: "data.importExcel", description: "Import a workbook from an Excel file." },
                { label: "OneLake catalog", visibleLabel: "OneLake\ncatalog", width: 50, iconName: "databaseLink", commandId: "data.oneLakeCatalog", description: "Browse the OneLake catalog." },
                { label: "SQL Server", visibleLabel: "SQL Server", width: 44, iconName: "database", commandId: "data.sqlServer", description: "Connect to SQL Server." },
                { label: "Enter data", visibleLabel: "Enter\ndata", width: 38, iconName: "tableAdd", commandId: "data.source.enterData", description: "Manual table entry is not implemented yet." },
                { label: "Dataverse", visibleLabel: "Dataverse", width: 46, iconName: "table", commandId: "data.dataverse", description: "Connect to Dataverse." },
                { label: "Recent sources", visibleLabel: "Recent\nsources", width: 46, iconName: "history", commandId: "data.recentSources", description: "Show a recently loaded data source." }
            ]},
            { title: "Queries", actions: [
                { label: "Transform data", visibleLabel: "Transform\ndata", width: 42, iconName: "tableEdit", commandId: "disabled.transform", available: false, description: "Data transformation is not available in this release." },
                { label: "Refresh", visibleLabel: "Refresh", width: 30, iconName: "refresh", commandId: "data.refresh", description: "Reload the linked data file." }
            ]},
            { title: "Insert", actions: [
                { label: "New visual", visibleLabel: "New\nvisual", iconName: "visual", commandId: "report.addMonthly", description: "Add a monthly revenue visual to this page." },
                { label: "Text box", visibleLabel: "Text box", iconName: "text", commandId: "disabled.textBox", available: false, description: "Report text boxes are not available in this release." },
                { label: "More visuals", visibleLabel: "More\nvisuals", width: 40, iconName: "visual", commandId: "insert.moreVisuals", hasDropdown: true, description: "Browse visuals from AppSource or your files." }
            ]},
            { title: "Calculations", actions: [
                { label: "New visual calculation", visibleLabel: "New visual\ncalculation", width: 60, iconName: "dataLine", commandId: "disabled.visualCalculation", available: false, description: "Visual calculations are not available in this release." },
                { label: "New measure", visibleLabel: "New\nmeasure", width: 40, iconName: "measure", commandId: "disabled.measure", available: false, description: "DAX measures are not available in this release." },
                { label: "Quick measure", visibleLabel: "Quick\nmeasure", width: 40, iconName: "quickMeasure", commandId: "disabled.quickMeasure", available: false, description: "Quick measures are not available in this release." }
            ]},
            { title: "Sensitivity", actions: [
                { label: "Sensitivity", visibleLabel: "Sensitivity", width: 62, iconName: "security", commandId: "disabled.sensitivity", available: false, description: "Sensitivity labels are not available in this release." }
            ]},
            { title: "Share", actions: [
                { label: "Publish", visibleLabel: "Publish", width: 42, iconName: "share", commandId: "disabled.publish", available: false, description: "Publishing is not available in this release." }
            ]},
            { title: "AI", actions: [
                { label: "Prep data for Copilot", visibleLabel: "Prep data for\nCopilot", width: 62, iconName: "aiPrep", commandId: "ai.prepData", available: false, description: "Prepare data for Copilot." }
            ]},
            { title: "Copilot", actions: [
                { label: "Copilot", visibleLabel: "Copilot", width: 44, iconName: "copilot", commandId: "ai.copilot", description: "Open Copilot." }
            ]}
        ]},
        { groups: [
            { title: "Pages", compact: true, actions: [
                { label: "New page", visibleLabel: "New\npage", width: 48, hasDropdown: true, iconName: "page", commandId: "report.addPage", description: "Add a report page." }
            ]},
            { title: "Visuals", compact: true, actions: [
                { label: "New visual", visibleLabel: "New\nvisual", width: 44, appearanceAvailable: true, iconName: "newVisual", commandId: "disabled.newVisual", available: false, description: "Generic blank-visual creation is not available yet. Use the Home tab for the supported revenue charts." },
                { label: "More visuals", visibleLabel: "More\nvisuals", width: 46, hasDropdown: true, appearanceAvailable: true, iconName: "moreVisuals", commandId: "insert.moreVisuals", description: "Browse visuals from AppSource or your files." }
            ]},
            { title: "AI visuals", compact: true, actions: [
                { label: "Key influencers", visibleLabel: "Key\ninfluencers", width: 58, appearanceAvailable: true, iconName: "keyInfluencers", commandId: "disabled.keyInfluencers", available: false, description: "Key influencers visuals are not available in this release." },
                { label: "Decomposition tree", visibleLabel: "Decomposition\ntree", width: 84, appearanceAvailable: true, iconName: "decomposition", commandId: "disabled.decomposition", available: false, description: "Decomposition tree visuals are not available in this release." },
                { label: "Narrative", visibleLabel: "Narrative", width: 50, appearanceAvailable: true, iconName: "narrative", commandId: "disabled.narrative", available: false, description: "Narrative visuals are not available in this release." }
            ]},
            { title: "Elements", compact: true, actions: [
                { label: "Text box", visibleLabel: "Text\nbox", width: 38, appearanceAvailable: true, iconName: "text", commandId: "disabled.textBox", available: false, description: "Report text boxes are not available in this release." },
                { label: "Buttons", visibleLabel: "Buttons", width: 46, hasDropdown: true, appearanceAvailable: true, iconName: "button", commandId: "insert.buttons", description: "Browse the report button gallery." },
                { label: "Shapes", visibleLabel: "Shapes", width: 43, hasDropdown: true, appearanceAvailable: true, iconName: "shape", commandId: "insert.shapes", description: "Browse report shapes." },
                { label: "Image", visibleLabel: "Image", width: 34, appearanceAvailable: true, iconName: "image", commandId: "disabled.image", available: false, description: "Report images are not available in this release." }
            ]},
            { title: "Sparklines", compact: true, actions: [
                { label: "Add a sparkline", visibleLabel: "Add a\nsparkline", width: 52, iconName: "sparkline", commandId: "disabled.sparkline", available: false, description: "Sparklines are not available in this release." }
            ]}
        ]},
        { groups: [
            { title: "Data & model", actions: [
                { label: "Data view", visibleLabel: "Data\nview", iconName: "data", commandId: "view.data", description: "Switch to Data view." },
                { label: "Model view", visibleLabel: "Model\nview", iconName: "model", commandId: "view.model", description: "Switch to Model view." }
            ]},
            { title: "Relationships", actions: [
                { label: "Manage relationships", visibleLabel: "Manage\nrelationships", width: 72, iconName: "relationship", commandId: "disabled.relationships", available: false, description: "Relationship editing is not available in this release." }
            ]},
            { title: "Calculations", actions: [
                { label: "New visual calculation", visibleLabel: "New visual\ncalculation", width: 56, iconName: "dataLine", commandId: "disabled.visualCalculation", available: false, description: "Visual calculations are not available in this release." },
                { label: "New measure", visibleLabel: "New\nmeasure", width: 40, iconName: "measure", commandId: "disabled.measure", available: false, description: "DAX measures are not available in this release." },
                { label: "Quick measure", visibleLabel: "Quick\nmeasure", width: 40, iconName: "quickMeasure", commandId: "disabled.quickMeasure", available: false, description: "Quick measures are not available in this release." },
                { label: "New column", visibleLabel: "New\ncolumn", iconName: "column", commandId: "disabled.column", available: false, description: "Calculated columns are not available in this release." },
                { label: "New table", visibleLabel: "New\ntable", iconName: "tableAdd", commandId: "disabled.newTable", available: false, description: "Calculated tables are not available in this release." }
            ]},
            { title: "Calendars", actions: [
                { label: "Mark as date table", visibleLabel: "Mark as\ndate table", width: 48, iconName: "calendar", commandId: "disabled.dateTable", available: false, description: "Date table configuration is not available in this release." }
            ]},
            { title: "Page refresh", actions: [
                { label: "Change detection", visibleLabel: "Change\ndetection", width: 56, iconName: "refresh", commandId: "disabled.changeDetection", available: false, description: "Change detection is not available in this release." }
            ]},
            { title: "Parameters", actions: [
                { label: "New parameter", visibleLabel: "New\nparameter", width: 58, iconName: "form", commandId: "disabled.parameter", available: false, description: "Parameters are not available in this release." }
            ]},
            { title: "Security", actions: [
                { label: "Manage roles", visibleLabel: "Manage\nroles", iconName: "security", commandId: "disabled.roles", available: false, description: "Row-level security is not available in this release." },
                { label: "View as", visibleLabel: "View as", iconName: "eye", commandId: "disabled.viewAs", available: false, description: "Role preview is not available in this release." }
            ]},
            { title: "Q&A", actions: [
                { label: "Q&A setup", visibleLabel: "Q&A\nsetup", width: 46, iconName: "question", commandId: "disabled.qa", available: false, description: "Q&A setup is not available in this release." },
                { label: "Language", visibleLabel: "Language", width: 58, iconName: "format", commandId: "disabled.language", available: false, description: "Natural language configuration is not available in this release." },
                { label: "Linguistic schema", visibleLabel: "Linguistic\nschema", width: 58, iconName: "math", commandId: "disabled.linguisticSchema", available: false, description: "Linguistic schema editing is not available in this release." }
            ]}
        ]},
        { groups: [
            { title: "Themes", actions: [
                { label: "Default theme", visibleLabel: "Default\ntheme", iconName: "paintBrush", commandId: "disabled.theme", available: false, description: "Report themes are not available in this release." },
                { label: "Theme gallery", visibleLabel: "Theme\ngallery", iconName: "visual", commandId: "disabled.themes", available: false, description: "Theme gallery is not available in this release." }
            ]},
            { title: "Scale to fit", actions: [
                { label: "Page view", visibleLabel: "Page view", iconName: "fit", commandId: "view.zoomFit", description: "Fit the report page in the available workspace." },
                { label: "Mobile layout", visibleLabel: "Mobile\nlayout", iconName: "phone", commandId: "disabled.mobileLayout", available: false, description: "Mobile report layout is not available in this release." }
            ]},
            { title: "Page options", actions: [
                { label: "Gridlines", visibleLabel: "Gridlines", iconName: "grid", commandId: "disabled.gridlines", available: false, description: "Canvas gridlines are not available in this release." },
                { label: "Snap to grid", visibleLabel: "Snap to\ngrid", iconName: "grid", commandId: "disabled.snapGrid", available: false, description: "Grid snapping is not available in this release." },
                { label: "Lock objects", visibleLabel: "Lock\nobjects", iconName: "lock", commandId: "disabled.lockObjects", available: false, description: "Object locking is not available in this release." }
            ]},
            { title: "Show panes", actions: [
                { label: "Filters", visibleLabel: "Filters", iconName: "filter", commandId: "view.filters", description: "Show or collapse the Filters pane." },
                { label: "Bookmarks", visibleLabel: "Bookmarks", iconName: "bookmark", commandId: "disabled.bookmarks", available: false, description: "Bookmarks are not available in this release." },
                { label: "Selection", visibleLabel: "Selection", iconName: "visual", commandId: "disabled.selectionPane", available: false, description: "The Selection pane is not available in this release." },
                { label: "Performance analyzer", visibleLabel: "Performance\nanalyzer", iconName: "optimize", commandId: "disabled.performance", available: false, description: "Performance analysis is not available in this release." },
                { label: "Sync slicers", visibleLabel: "Sync\nslicers", iconName: "refresh", commandId: "disabled.syncSlicers", available: false, description: "Slicer synchronization is not available in this release." }
            ]},
            { title: "Workspace", actions: [
                { label: "Visualizations pane", visibleLabel: "Visualizations", iconName: "visual", commandId: "view.visualizations", description: "Show or hide the Visualizations pane." },
                { label: "Data pane", visibleLabel: "Data pane", iconName: "data", commandId: "view.dataPane", description: "Show or collapse the Data pane." },
                { label: "Reset layout", visibleLabel: "Reset\nlayout", iconName: "reset", commandId: "view.resetLayout", description: "Restore the default pane and zoom layout." }
            ]}
        ]},
        { groups: [
            { title: "Queries", actions: [
                { label: "Pause visuals", visibleLabel: "Pause\nvisuals", width: 52, iconName: "pause", commandId: "disabled.pauseVisuals", available: false, description: "Pausing visual queries is not available in this release." },
                { label: "Refresh visuals", visibleLabel: "Refresh\nvisuals", width: 60, iconName: "refresh", commandId: "disabled.refreshVisuals", available: false, description: "Visual-only refresh is not available in this release." }
            ]},
            { title: "Report", actions: [
                { label: "Optimization presets", visibleLabel: "Optimization\npresets", width: 76, iconName: "optimize", commandId: "disabled.optimizationPresets", available: false, description: "Optimization presets are not available in this release." }
            ]},
            { title: "Review", actions: [
                { label: "Performance analyzer", visibleLabel: "Performance\nanalyzer", width: 82, iconName: "optimize", commandId: "disabled.performance", available: false, description: "Performance analysis is not available in this release." }
            ]},
            { title: "Apply", actions: [
                { label: "Apply all slicers", visibleLabel: "Apply all\nslicers", width: 62, iconName: "checkmark", commandId: "disabled.applySlicers", available: false, description: "Slicers are not available in this release." }
            ]}
        ]},
        { groups: [
            { title: "Learn", actions: [
                { label: "Guided learning", visibleLabel: "Guided\nlearning", iconName: "book", commandId: "disabled.guidedLearning", available: false, description: "Guided learning is not available in this release." },
                { label: "Training videos", visibleLabel: "Training\nvideos", iconName: "video", commandId: "disabled.trainingVideos", available: false, description: "Training videos are not available in this release." },
                { label: "Documentation", visibleLabel: "Documentation", iconName: "format", commandId: "help.projectFormat", description: "Open the Analytics Studio project format guide." }
            ]},
            { title: "Support", actions: [
                { label: "About", visibleLabel: "About", iconName: "about", commandId: "help.about", description: "About Analytics Studio." },
                { label: "Keyboard shortcuts", visibleLabel: "Keyboard\nshortcuts", iconName: "shortcuts", commandId: "help.shortcuts", description: "Show available keyboard shortcuts." },
                { label: "Get support", visibleLabel: "Get\nsupport", iconName: "support", commandId: "disabled.support", available: false, description: "External support is not available in this release." }
            ]},
            { title: "Community", actions: [
                { label: "Community", visibleLabel: "Community", iconName: "people", commandId: "disabled.community", available: false, description: "Community links are not available in this release." },
                { label: "Submit an idea", visibleLabel: "Submit an\nidea", iconName: "lightbulb", commandId: "disabled.idea", available: false, description: "Feedback submission is not available in this release." }
            ]},
            { title: "Tools", actions: [
                { label: "Examples", visibleLabel: "Examples", iconName: "table", commandId: "disabled.examples", available: false, description: "Example projects are not available in this release." }
            ]}
        ]}
    ]

    function ribbonIndexForName(tabName) {
        const index = ribbonTabs.indexOf(tabName)
        return index >= 0 ? index : 1
    }

    function groupsForRibbonTab(tabDefinition, tabName) {
        if (appController.currentView === "Data" && tabName === "Home")
            return dataHomeGroups
        return tabDefinition.groups || []
    }

    function selectRibbonForView(viewName) {
        ribbonTabName = viewName === "Model" ? "Modeling" : "Home"
    }

    function navigateToView(viewName) {
        appController.setCurrentView(viewName)
    }

    Connections {
        target: appController
        function onStateChanged() {
            const viewName = String(appController.currentView)
            if (root.lastWorkspaceView !== viewName) {
                root.lastWorkspaceView = viewName
                root.selectRibbonForView(viewName)
            }
        }
    }

    function runCommand(commandId) {
        switch (commandId) {
        case "project.new": clearFieldSearch(); appController.executeCommand("newProject"); break
        case "project.open": clearFieldSearch(); appController.executeCommand("openProject"); break
        case "project.save": appController.executeCommand("saveProject"); break
        case "project.saveAs": appController.executeCommand("saveProjectAs"); break
        case "data.openPicker": openGetDataPicker(null); break
        case "data.importCsv": clearFieldSearch(); appController.executeCommand("importCsv"); break
        case "data.importExcel": clearFieldSearch(); appController.executeCommand("importExcel"); break
        case "data.importFile": clearFieldSearch(); appController.executeCommand("importData"); break
        case "data.oneLakeCatalog": appController.reportStagedAction("OneLake catalog", "OneLake catalog connections are not implemented yet."); break
        case "data.sqlServer": appController.reportStagedAction("SQL Server", "SQL Server connections are not implemented yet."); break
        case "data.dataverse": appController.reportStagedAction("Dataverse", "Dataverse connections are not implemented yet."); break
        case "data.enterBlank": appController.reportStagedAction("Paste data into a blank table", "Manual table entry is not implemented yet."); break
        case "data.sampleData": appController.reportStagedAction("Use sample data", "Sample data is not available in this release."); break
        case "ai.prepData": appController.reportStagedAction("Prep data for Copilot", "Copilot data preparation is not implemented yet."); break
        case "ai.copilot": appController.reportStagedAction("Copilot", "Copilot is not connected to this Analytics Studio project yet."); break
        case "data.refresh": appController.executeCommand("refreshSource"); break
        case "filter.clear": appController.executeCommand("clearFilters"); break
        case "report.addPage": appController.executeCommand("addPage"); break
        case "report.addMonthly": appController.executeCommand("addMonthlyChart"); break
        case "report.addRegion": appController.executeCommand("addRegionChart"); break
        case "view.report": navigateToView("Report"); break
        case "view.data": navigateToView("Data"); break
        case "view.model": navigateToView("Model"); break
        case "view.filters": filtersExpanded = !filtersExpanded; break
        case "view.visualizations": visualizationsVisible = !visualizationsVisible; break
        case "view.dataPane": dataPaneExpanded = !dataPaneExpanded; break
        case "view.navigation": navigationVisible = !navigationVisible; break
        case "view.togglePanes": inspectorVisible = !inspectorVisible; break
        case "view.zoomFit": zoomToFit(); break
        case "view.resetLayout":
            navigationVisible = true; filtersExpanded = false; dataPaneExpanded = false
            visualizationsVisible = true; inspectorVisible = true; zoomToFit(); break
        case "view.zoomIn": fitZoom = false; reportZoom = Math.min(1.5, reportZoom + 0.1); break
        case "view.zoomOut": fitZoom = false; reportZoom = Math.max(0.15, reportZoom - 0.1); break
        case "chart.type.column": appController.setChartType("column"); break
        case "chart.type.bar": appController.setChartType("bar"); break
        case "chart.type.line": appController.setChartType("line"); break
        case "help.about": appController.executeCommand("about"); break
        case "help.shortcuts": appController.executeCommand("shortcuts"); break
        case "help.projectFormat": appController.executeCommand("projectFormat"); break
        default: break
        }
    }

    function openGetDataPicker(focusTarget) {
        if (ribbonPopupMenu.visible) {
            ribbonPopupMenu.transferFocus = true
            ribbonPopupMenu.close()
        }
        if (shapePalette.visible) {
            shapePalette.transferFocus = true
            shapePalette.close()
        }
        getDataDialog.returnFocusItem = focusTarget
        getDataDialog.open()
    }

    function showRibbonPopup(type, sourceItem, focusTarget) {
        if (shapePalette.visible) {
            shapePalette.transferFocus = true
            shapePalette.close()
        }
        ribbonPopupMenu.menuType = type
        ribbonPopupMenu.openAt(Overlay.overlay, sourceItem, focusTarget || sourceItem)
    }

    function handleRibbonAction(commandId, sourceItem) {
        switch (commandId) {
        case "data.openPicker": openGetDataPicker(sourceItem); return
        case "data.recentSources": showRibbonPopup("recentSources", sourceItem, sourceItem); return
        case "data.source.enterData":
            appController.reportStagedAction("Enter data", "Manual table entry is not implemented.")
            return
        case "insert.moreVisuals": showRibbonPopup("moreVisuals", sourceItem, sourceItem); return
        case "insert.buttons": showRibbonPopup("buttons", sourceItem, sourceItem); return
        case "insert.shapes": shapePalette.openAt(Overlay.overlay, sourceItem, sourceItem); return
        default: runCommand(commandId); return
        }
    }

    function handleRibbonDropdown(commandId, sourceItem) {
        if (commandId === "data.openPicker")
            showRibbonPopup("commonSources", sourceItem, sourceItem)
    }

    function handlePopupAction(action, label, focusTarget) {
        if (action === "data.more") {
            Qt.callLater(function() { root.openGetDataPicker(focusTarget) })
            return
        }
        if (action === "source.csv" || action === "recent.csv") {
            Qt.callLater(function() {
                appController.connectDataSource("file_text_csv")
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        if (action === "source.excel" || action === "recent.excel") {
            Qt.callLater(function() {
                appController.connectDataSource("file_excel_workbook")
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        appController.reportStagedAction(label,
                "This menu entry is a UI surface; its workflow is not implemented yet.")
        if (focusTarget)
            Qt.callLater(function() {
                if (focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
    }

    function accentForIcon(iconName) {
        switch (iconName) {
        case "csv": case "data": case "table": case "refresh": case "getData": case "database": case "databaseMultiple": case "column": case "measure": return "#0078D4"
        case "excel": return "#217346"
        case "tableAdd": case "model": case "relationship": case "bar": return "#107C71"
        case "line": case "quickMeasure": return "#C65911"
        case "share": return "#0078D4"
        case "security": case "formatPainter": return "#8A6D1D"
        case "page": case "plus": return "#107C71"
        case "keyInfluencers": return "#647382"
        case "decomposition": case "narrative": case "newVisual": case "moreVisuals": return "#0078D4"
        case "report": case "visual": case "tableEdit": return "#107C71"
        case "filter": case "clear": return "#8A6D1D"
        default: return "#5F6B75"
        }
    }

    function galleryAccent(type) {
        switch (type) {
        case "bar": case "column": case "stackedBar": case "stackedColumn": case "bar100": case "column100":
        case "table": case "matrix": case "card": case "multiCard": case "kpi": case "slicer": return "#0078D4"
        case "line": case "area": case "stackedArea": case "waterfall": case "funnel": case "scatter": return "#C65911"
        case "pie": case "donut": case "treemap": case "ribbon": return "#8A6D1D"
        case "map": case "filledMap": case "decomposition": return "#107C71"
        default: return "#647382"
        }
    }

    function commandAvailable(commandId) {
        const reportOnly = commandId.startsWith("report.") || commandId.startsWith("chart.type.")
                || commandId === "filter.clear" || commandId === "view.filters"
                || commandId === "view.visualizations" || commandId === "view.dataPane"
                || commandId === "view.togglePanes" || commandId === "view.zoomFit"
                || commandId === "view.zoomIn" || commandId === "view.zoomOut"
                || commandId === "view.resetLayout"
        if (reportOnly && appController.currentView !== "Report") return false
        if (commandId === "data.refresh") return appController.sourceLoaded
        if (commandId === "filter.clear") return appController.filterActive
        return true
    }

    function commandUnavailableReason(commandId) {
        const reportOnly = commandId.startsWith("report.") || commandId.startsWith("chart.type.")
                || commandId === "filter.clear" || commandId === "view.filters"
                || commandId === "view.visualizations" || commandId === "view.dataPane"
                || commandId === "view.togglePanes" || commandId === "view.zoomFit"
                || commandId === "view.zoomIn" || commandId === "view.zoomOut"
                || commandId === "view.resetLayout"
        if (reportOnly && appController.currentView !== "Report")
            return "Switch to Report view to use this command."
        if (commandId === "data.refresh" && !appController.sourceLoaded)
            return "Import data before refreshing."
        if (commandId === "filter.clear" && !appController.filterActive)
            return "There is no active Region filter to clear."
        return ""
    }

    function clearFieldSearch() {
        fieldSearchQuery = ""
        appController.setFieldQuery("")
    }

    function zoomToFit() {
        fitZoom = true
        if (reportViewport.width > 0 && reportViewport.height > 0)
            reportZoom = Math.max(0.15, Math.min(1.25,
                                     (reportViewport.width - 8) / 1280,
                                     (reportViewport.height - 48) / 720))
    }

    component RibbonGroup: Item {
        id: ribbonGroup
        property string caption: ""
        property var commands: []
        property bool compact: false
        signal invoked(string commandId, var sourceItem)
        signal dropdownInvoked(string commandId, var sourceItem)
        implicitWidth: groupRow.implicitWidth + (compact ? 4 : 10)
        implicitHeight: 84
        width: implicitWidth
        height: implicitHeight

        RowLayout {
            id: groupRow
            anchors.fill: parent
            anchors.leftMargin: 5
            anchors.rightMargin: 5
            anchors.topMargin: 2
            anchors.bottomMargin: 14
            spacing: ribbonGroup.compact ? 1 : 2
            Repeater {
                model: ribbonGroup.commands
                delegate: RibbonCommand {
                    id: ribbonCommand
                    required property var modelData
                    label: String(modelData.label || "")
                    visibleLabel: String(modelData.visibleLabel || modelData.label || "")
                    iconName: String(modelData.iconName || "report")
                    iconColor: root.accentForIcon(String(modelData.iconName || "report"))
                    commandWidth: Math.max(ribbonGroup.compact ? 42 : 54, Math.round(Number(modelData.width || 34) * 1.08))
                    iconSize: ribbonGroup.compact ? 25 : 22
                    appearanceAvailable: modelData.appearanceAvailable === true
                    hasDropdown: modelData.hasDropdown === true
                    splitGetData: modelData.splitGetData === true
                    commandId: String(modelData.commandId || "")
                    description: String(modelData.description || "")
                    available: modelData.available === false ? false : root.commandAvailable(String(modelData.commandId || ""))
                    unavailableReason: root.commandUnavailableReason(String(modelData.commandId || ""))
                    onTriggered: function(id, sourceItem) { ribbonGroup.invoked(id, sourceItem) }
                    onDropdownTriggered: function(sourceItem) {
                        ribbonGroup.dropdownInvoked(String(modelData.commandId || ""), sourceItem)
                    }
                }
            }
        }
        Rectangle {
            anchors.right: parent.right
            anchors.top: parent.top
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 15
            width: 1
            color: "#d8dadd"
        }
        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.bottom: parent.bottom
            anchors.bottomMargin: 1
            text: ribbonGroup.caption
            color: "#69737d"
            font.pixelSize: 10
        }
    }

    GetDataDialog {
        id: getDataDialog
        objectName: "getDataDialog"
        controller: appController
    }

    RibbonPopupMenu {
        id: ribbonPopupMenu
        objectName: "ribbonPopupMenu"
        controller: appController
        onActionRequested: function(action, label, focusTarget) {
            root.handlePopupAction(action, label, focusTarget)
        }
    }

    ShapePalettePopup {
        id: shapePalette
        objectName: "shapePalette"
        controller: appController
        onShapeChosen: function(shapeName) {
            const focusTarget = shapePalette.returnFocusItem
            appController.reportStagedAction(shapeName + " shape",
                    "Shape creation is not implemented yet.")
            if (focusTarget)
                Qt.callLater(function() {
                    if (focusTarget.visible)
                        focusTarget.forceActiveFocus()
                })
        }
    }

    menuBar: MenuBar {
        Menu {
            title: "File"
            MenuItem { text: "New Project"; onTriggered: root.runCommand("project.new") }
            MenuItem { text: "Open Project…"; onTriggered: root.runCommand("project.open") }
            MenuSeparator {}
            MenuItem { text: "Save"; onTriggered: root.runCommand("project.save") }
            MenuItem { text: "Save As…"; onTriggered: root.runCommand("project.saveAs") }
            MenuSeparator {}
            MenuItem { text: "Import data…"; onTriggered: root.runCommand("data.importFile") }
            MenuSeparator {}
            MenuItem { text: "Quit Analytics Studio"; onTriggered: appController.executeCommand("quit") }
        }
        Menu {
            title: "View"
            MenuItem { text: "Report"; onTriggered: root.runCommand("view.report") }
            MenuItem { text: "Data"; onTriggered: root.runCommand("view.data") }
            MenuItem { text: "Model"; onTriggered: root.runCommand("view.model") }
            MenuSeparator {}
            MenuItem { text: "Fit to Page"; onTriggered: root.runCommand("view.zoomFit") }
            MenuItem { text: "Reset Layout"; onTriggered: root.runCommand("view.resetLayout") }
        }
        Menu {
            title: "Help"
            MenuItem { text: "About Analytics Studio"; onTriggered: root.runCommand("help.about") }
            MenuItem { text: "Keyboard Shortcuts"; onTriggered: root.runCommand("help.shortcuts") }
            MenuItem { text: "Project Format"; onTriggered: root.runCommand("help.projectFormat") }
        }
    }

    Shortcut { sequences: [StandardKey.New]; onActivated: root.runCommand("project.new") }
    Shortcut { sequences: [StandardKey.Open]; onActivated: root.runCommand("project.open") }
    Shortcut { sequences: [StandardKey.Save]; onActivated: root.runCommand("project.save") }
    Shortcut { sequences: [StandardKey.SaveAs]; onActivated: root.runCommand("project.saveAs") }
    Shortcut { sequences: [StandardKey.Quit]; onActivated: studioController.executeCommand("quit") }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 30
            Layout.fillHeight: false
            Layout.minimumHeight: 30
            Layout.maximumHeight: 30
            color: "#ffffff"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 9
                spacing: 0
                Repeater {
                    model: root.ribbonTabs
                    delegate: Button {
                        required property int index
                        required property var modelData
                            Layout.preferredWidth: Math.max(46, tabLabel.implicitWidth + 18)
                        Layout.fillHeight: true
                        text: String(modelData)
                        checkable: true
                        checked: root.ribbonTabName === String(modelData)
                        padding: 0
                        hoverEnabled: true
                        background: Rectangle { color: "transparent" }
                        contentItem: Text {
                            id: tabLabel
                            text: String(modelData)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: root.ribbonTabName === String(modelData) ? "#263a49" : "#52616e"
                            font.pixelSize: 11
                            font.weight: root.ribbonTabName === String(modelData) ? Font.DemiBold : Font.Normal
                        }
                        Rectangle {
                            visible: root.ribbonTabName === String(modelData)
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 2
                            color: "#107C71"
                        }
                        onClicked: root.ribbonTabName = String(modelData)
                    }
                }
                Item { Layout.fillWidth: true }
                Button {
                    text: "Share"
                    enabled: false
                    Layout.preferredWidth: 54
                    Layout.preferredHeight: 22
                    padding: 4
                    Accessible.name: "Share report"
                    Accessible.description: "Sharing is not available in this release."
                    ToolTip.visible: hovered
                    ToolTip.text: "Sharing is not available in this release."
                    background: Rectangle {
                        radius: 3
                        color: parent.enabled ? (parent.hovered ? "#006f65" : "#107c71") : "#eef0f1"
                        border.color: parent.enabled ? "#0d7269" : "#dfe3e5"
                    }
                    contentItem: RowLayout {
                        Icon { name: "share"; color: "#9aa3a9"; implicitWidth: 15; implicitHeight: 15 }
                        Text {
                            Layout.fillWidth: true
                            text: "Share"
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: "#8d969c"
                            font.pixelSize: 10
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 92
            Layout.fillHeight: false
            Layout.minimumHeight: 92
            Layout.maximumHeight: 92
            color: "#f8f9fa"
            border.color: "#d4d8dc"
            clip: true
            StackLayout {
                anchors.fill: parent
                anchors.leftMargin: 5
                anchors.rightMargin: 5
                currentIndex: root.ribbonIndexForName(root.ribbonTabName)
                Repeater {
                    model: root.ribbonDefinitions
                    delegate: Flickable {
                        required property int index
                        required property var modelData
                        property var tabDefinition: modelData
                        property string tabName: root.ribbonTabs[index]
                        clip: true
                        contentWidth: ribbonRow.implicitWidth
                        contentHeight: height
                        boundsBehavior: Flickable.StopAtBounds
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        RowLayout {
                            id: ribbonRow
                            height: parent.height
                            spacing: 2
                            Repeater {
                                model: root.groupsForRibbonTab(tabDefinition, tabName)
                                delegate: RibbonGroup {
                                    required property var modelData
                                    caption: String(modelData.title || "")
                                    commands: modelData.actions || []
                                    compact: Boolean(modelData.compact)
                                    onInvoked: function(id, sourceItem) { root.handleRibbonAction(id, sourceItem) }
                                    onDropdownInvoked: function(id, sourceItem) { root.handleRibbonDropdown(id, sourceItem) }
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            visible: appController.sourceWarning !== ""
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 29 : 0
            Layout.fillHeight: false
            Layout.minimumHeight: visible ? 29 : 0
            Layout.maximumHeight: visible ? 29 : 0
            color: "#fbf5e9"
            border.color: "#e7d7b6"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 12
                Icon { name: "about"; color: "#9a7940"; implicitWidth: 16; implicitHeight: 16 }
                Text {
                    Layout.fillWidth: true
                    text: appController.sourceWarning
                    color: "#66583d"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                    Accessible.name: "Data source recovery warning"
                }
                Button {
                    text: "Relink data source"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#f2ead8" : "#f8f3e9"; border.color: "#e0d2b5" }
                    contentItem: Text { text: parent.text; color: "#705e3c"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.runCommand("data.importFile")
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 300
            spacing: 0

            Rectangle {
                visible: root.navigationVisible
                Layout.preferredWidth: visible ? 32 : 0
                Layout.fillHeight: true
                color: "#f8f9fa"
                border.color: "#d6dbe0"
                ColumnLayout {
                    anchors.fill: parent
                    anchors.topMargin: 5
                    spacing: 2
                    Repeater {
                        model: [
                            { name: "Report", icon: "report", enabled: true },
                            { name: "Data", icon: "data", enabled: true },
                            { name: "Model", icon: "model", enabled: true },
                            { name: "DAX", icon: "dax", enabled: false },
                            { name: "TMDL", icon: "tmdl", enabled: false }
                        ]
                        delegate: Button {
                            required property var modelData
                            Layout.fillWidth: true
                            Layout.preferredHeight: 32
                            Layout.leftMargin: 3
                            Layout.rightMargin: 3
                            enabled: Boolean(modelData.enabled)
                            hoverEnabled: true
                            padding: 1
                            ToolTip.visible: hovered && !enabled
                            ToolTip.text: String(modelData.name) + " view is not available in this release."
                            Accessible.name: String(modelData.name) + " view"
                            Accessible.description: enabled ? "Switch to " + String(modelData.name) + " view." : "This view is not available in this release."
                            background: Rectangle {
                                radius: 3
                                color: modelData.enabled && appController.currentView === modelData.name ? "#e3f0ef" : (parent.hovered ? "#f0f4f6" : "transparent")
                                Rectangle {
                                    visible: modelData.enabled && appController.currentView === modelData.name
                                    width: 3
                                    anchors.left: parent.left
                                    anchors.top: parent.top
                                    anchors.bottom: parent.bottom
                                    radius: 2
                                    color: "#107c71"
                                }
                            }
                            contentItem: Item {
                                Icon {
                                    anchors.centerIn: parent
                                    name: String(modelData.icon)
                                    color: modelData.enabled ? (appController.currentView === modelData.name ? "#0078D4" : root.accentForIcon(String(modelData.icon))) : "#a8afb5"
                                    width: 18
                                    height: 18
                                }
                            }
                            onClicked: root.navigateToView(String(modelData.name))
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            StackLayout {
                id: viewStack
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: appController.currentView === "Report" ? 0
                              : (appController.currentView === "Data" ? 1 : 2)
                Rectangle {
                    id: reportWorkspace
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    color: "#e7e8ea"
                    clip: true
                    Flickable {
                        id: reportViewport
                        anchors.fill: parent
                        clip: true
                        boundsBehavior: Flickable.StopAtBounds
                        contentWidth: Math.max(width, 1280 * root.reportZoom + 8)
                        contentHeight: Math.max(height, 720 * root.reportZoom + 48)
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        onWidthChanged: if (root.fitZoom) Qt.callLater(root.zoomToFit)
                        onHeightChanged: if (root.fitZoom) Qt.callLater(root.zoomToFit)

                        Item {
                            id: reportPagePositioner
                            width: reportViewport.contentWidth
                            height: reportViewport.contentHeight
                            Rectangle {
                                id: reportPage
                                width: 1280 * root.reportZoom
                                height: 720 * root.reportZoom
                                anchors.centerIn: parent
                                color: "#ffffff"
                                border.color: "#d0d4d8"
                                border.width: 1
                                clip: true
                                Item {
                                    id: reportPageBody
                                    width: 1280
                                    height: 720
                                    transform: Scale { xScale: root.reportZoom; yScale: root.reportZoom; origin.x: 0; origin.y: 0 }

                                    ColumnLayout {
                                        anchors.fill: parent
                                        anchors.margins: 20
                                        spacing: 14
                                        Item {
                                            objectName: "reportEmptyState"
                                            visible: !appController.sourceLoaded
                                            Layout.fillWidth: true
                                            Layout.fillHeight: true
                                            ColumnLayout {
                                                anchors.centerIn: parent
                                                spacing: 12
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: "Add data to your report"
                                                    color: "#30383e"
                                                    font.pixelSize: 26
                                                    font.weight: Font.DemiBold
                                                }
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    textFormat: Text.RichText
                                                    text: "Once loaded, your data will appear in the <b>Data pane</b>."
                                                    color: "#39444c"
                                                    font.pixelSize: 18
                                                }
                                                GridLayout {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    Layout.topMargin: 8
                                                    columns: 4
                                                    columnSpacing: 14
                                                    rowSpacing: 0
                                                    Repeater {
                                                        model: [
                                                            { title: "Import data from Excel", icon: "excelTile", tint: "#cdebd8", command: "data.importExcel", active: true, description: "Open a workbook picker and import an Excel file." },
                                                            { title: "Import data from SQL Server", icon: "sqlServer", tint: "#edf5fb", command: "data.sqlServer", active: true, description: "Start a SQL Server connection." },
                                                            { title: "Paste data into a blank table", icon: "pasteTable", tint: "#fffdf3", command: "data.enterBlank", active: true, description: "Paste data into a new table." },
                                                            { title: "Use sample data", icon: "sampleData", tint: "#f3f3f3", command: "data.sampleData", active: true, description: "Load a sample data set." }
                                                        ]
                                                        delegate: Button {
                                                            required property var modelData
                                                            Layout.preferredWidth: 185
                                                            Layout.preferredHeight: 140
                                                            Layout.minimumWidth: 130
                                                            enabled: Boolean(modelData.active)
                                                            padding: 0
                                                            hoverEnabled: true
                                                            Accessible.name: String(modelData.title)
                                                            Accessible.description: enabled
                                                                    ? (modelData.description || String(modelData.title))
                                                                    : String(modelData.title) + " is not available in this release."
                                                            ToolTip.visible: hovered && !enabled
                                                            ToolTip.text: String(modelData.title) + " is not available in this release."
                                                            background: Rectangle {
                                                                radius: 3
                                                                color: "#ffffff"
                                                                border.color: parent.hovered && parent.enabled ? "#9bbdca" : "#d8dcdf"
                                                                Rectangle {
                                                                    anchors.left: parent.left
                                                                    anchors.right: parent.right
                                                                    anchors.top: parent.top
                                                                    height: 98
                                                                    color: modelData.tint
                                                                    radius: 3
                                                                }
                                                            }
                                                            contentItem: Item {
                                                                Icon {
                                                                    anchors.horizontalCenter: parent.horizontalCenter
                                                                    anchors.top: parent.top
                                                                    anchors.topMargin: 31
                                                                    name: String(modelData.icon)
                                                                    color: modelData.active ? "#107c71" : "#718191"
                                                                    width: 36
                                                                    height: 36
                                                                }
                                                                Text {
                                                                    anchors.left: parent.left
                                                                    anchors.right: parent.right
                                                                    anchors.bottom: parent.bottom
                                                                    anchors.leftMargin: 11
                                                                    anchors.rightMargin: 8
                                                                    anchors.bottomMargin: 10
                                                                    text: String(modelData.title)
                                                                    color: parent.parent.enabled ? "#25323b" : "#65717a"
                                                                    font.pixelSize: 12
                                                                    wrapMode: Text.Wrap
                                                                    maximumLineCount: 2
                                                                    elide: Text.ElideRight
                                                                }
                                                            }
                                                            onClicked: root.runCommand(String(modelData.command))
                                                        }
                                                    }
                                                }
                                                Button {
                                                    id: getDataAnotherSourceButton
                                                    Layout.alignment: Qt.AlignHCenter
                                                    Layout.preferredHeight: 31
                                                    text: "Get data from another source  →"
                                                    enabled: true
                                                    flat: true
                                                    Accessible.name: "Get data from another source"
                                                    Accessible.description: "Open the full data source picker."
                                                    background: Rectangle { color: "transparent" }
                                                    contentItem: Text {
                                                        text: parent.text
                                                        color: "#107c71"
                                                        font.pixelSize: 15
                                                        font.weight: Font.DemiBold
                                                        horizontalAlignment: Text.AlignHCenter
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                    onClicked: root.openGetDataPicker(getDataAnotherSourceButton)
                                                }
                                            }
                                        }
                                        Text {
                                            visible: appController.sourceLoaded
                                            Layout.fillHeight: false
                                            text: appController.activePageName
                                            color: "#293b49"
                                            font.pixelSize: 23
                                            font.weight: Font.DemiBold
                                        }
                                        Text {
                                            visible: appController.sourceLoaded
                                            Layout.fillHeight: false
                                            text: appController.sourceLoaded
                                                  ? "Report canvas  ·  " + appController.sourceName
                                                  : "Report canvas  ·  no data source"
                                            color: "#697987"
                                            font.pixelSize: 11
                                        }

                                        RowLayout {
                                            visible: appController.sourceLoaded && root.hasAnyKpis()
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 88
                                            Layout.fillHeight: false
                                            spacing: 10
                                            Repeater {
                                                model: root.kpiNames
                                                delegate: Rectangle {
                                                    required property var modelData
                                                    required property int index
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    visible: appController.activePageVisuals.indexOf(String(modelData) + " KPI") >= 0
                                                    radius: 6
                                                    color: "#ffffff"
                                                    border.color: "#d9e0e5"
                                                    Rectangle {
                                                        width: 3
                                                        anchors.left: parent.left
                                                        anchors.top: parent.top
                                                        anchors.bottom: parent.bottom
                                                        color: root.kpiColors[index % root.kpiColors.length]
                                                    }
                                                    ColumnLayout {
                                                        anchors.fill: parent
                                                        anchors.leftMargin: 15
                                                        anchors.rightMargin: 12
                                                        anchors.topMargin: 12
                                                        anchors.bottomMargin: 12
                                                        spacing: 4
                                                        Text { text: String(modelData); color: "#657583"; font.pixelSize: 10 }
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: appController.reportKpis[String(modelData)] || "—"
                                                            color: "#293e4d"
                                                            font.pixelSize: 19
                                                            font.weight: Font.DemiBold
                                                            elide: Text.ElideRight
                                                        }
                                                    }
                                                }
                                            }
                                        }

                                        RowLayout {
                                            visible: appController.sourceLoaded && root.hasAnyCharts()
                                            Layout.fillWidth: true
                                            Layout.fillHeight: appController.sourceLoaded && root.hasAnyCharts()
                                            spacing: 12
                                            ChartCard {
                                                visible: appController.activePageVisuals.indexOf("Monthly revenue") >= 0
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                title: "Monthly revenue"
                                                visualName: "Monthly revenue"
                                                chartType: appController.monthlyChartType
                                                seriesColor: "#0078D4"
                                                series: appController.monthlySeries
                                                selected: appController.selectedVisual === "Monthly revenue"
                                                emptyMessage: "No monthly revenue values found in this source."
                                                onRequestedSelection: function(name) { appController.selectVisual(name) }
                                            }
                                            ChartCard {
                                                visible: appController.activePageVisuals.indexOf("Region revenue") >= 0
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                title: "Region revenue"
                                                visualName: "Region revenue"
                                                chartType: appController.regionChartType
                                                seriesColor: "#107C71"
                                                series: appController.regionSeries
                                                selected: appController.selectedVisual === "Region revenue"
                                                filterOnCategory: true
                                                emptyMessage: "No region revenue values found in this source."
                                                onRequestedSelection: function(name) { appController.selectVisual(name) }
                                                onCategoryRequested: function(label) { appController.setRegionFilter(label) }
                                            }
                                        }

                                        Item {
                                            visible: appController.sourceLoaded && !root.hasAnyCharts() && !root.hasAnyKpis()
                                            Layout.fillWidth: true
                                            Layout.fillHeight: appController.sourceLoaded && !root.hasAnyCharts() && !root.hasAnyKpis()
                                            ColumnLayout {
                                                anchors.centerIn: parent
                                                spacing: 7
                                                Icon { Layout.alignment: Qt.AlignHCenter; name: "visual"; color: "#9aa6af"; implicitWidth: 30; implicitHeight: 30 }
                                                Text { text: "This page is blank"; color: "#4d5d69"; font.pixelSize: 14; font.weight: Font.DemiBold }
                                                Text { text: "Choose a visual from Insert to add it to this page."; color: "#78848d"; font.pixelSize: 11 }
                                            }
                                        }
                                    }

                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0

                    DataView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        appController: root.studioController
                    }

                    Rectangle {
                        Layout.preferredWidth: 210
                        Layout.minimumWidth: 190
                        Layout.fillHeight: true
                        color: "#ffffff"
                        border.color: "#d5d9dd"

                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0

                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                color: "#f8f9fa"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 9
                                    Icon { name: "data"; color: "#107c71"; implicitWidth: 16; implicitHeight: 16 }
                                    Text { Layout.fillWidth: true; text: "Data fields"; color: "#344553"; font.pixelSize: 11; font.weight: Font.DemiBold }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: "#dce1e4" }

                            Text {
                                Layout.fillWidth: true
                                Layout.leftMargin: 10
                                Layout.rightMargin: 10
                                Layout.topMargin: 8
                                text: appController.sourceLoaded ? "Linked data · " + appController.sourceName : "No linked data source"
                                color: appController.sourceLoaded ? "#64798a" : "#78858d"
                                font.pixelSize: 9
                                elide: Text.ElideRight
                                Accessible.name: text
                            }
                            Text {
                                Layout.fillWidth: true
                                Layout.leftMargin: 10
                                Layout.rightMargin: 10
                                Layout.topMargin: 4
                                Layout.bottomMargin: 7
                                text: appController.sourceLoaded
                                      ? appController.rowCount + " rows · " + appController.columnCount + " source fields"
                                      : "Browse fields from the linked data file. Saved table metadata is in Model view."
                                color: "#74818a"
                                font.pixelSize: 8
                                wrapMode: Text.Wrap
                            }
                            TextField {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 25
                                Layout.leftMargin: 8
                                Layout.rightMargin: 8
                                Layout.bottomMargin: 6
                                text: root.fieldSearchQuery
                                placeholderText: "Search fields"
                                enabled: appController.sourceLoaded
                                font.pixelSize: 9
                                color: "#40515e"
                                onTextChanged: {
                                    if (root.fieldSearchQuery !== text)
                                        root.fieldSearchQuery = text
                                    appController.setFieldQuery(text)
                                }
                                Accessible.name: "Search source fields"
                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: "#cfd7dd" }
                            }
                            ListView {
                                id: dataFieldsList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: appController.filteredFields
                                clip: true
                                delegate: RowLayout {
                                    required property var modelData
                                    width: ListView.view.width
                                    height: 25
                                    spacing: 5
                                    Layout.leftMargin: 8
                                    Layout.rightMargin: 7
                                    Icon {
                                        name: ["Revenue", "Cost", "Margin", "Units", "Orders"].indexOf(String(modelData)) >= 0 ? "measure" : "column"
                                        color: ["Revenue", "Cost", "Margin", "Units", "Orders"].indexOf(String(modelData)) >= 0 ? "#0078D4" : "#107C71"
                                        implicitWidth: 14
                                        implicitHeight: 14
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: String(modelData)
                                        color: "#3f505d"
                                        font.pixelSize: 9
                                        elide: Text.ElideRight
                                        Accessible.name: String(modelData) + " source field"
                                    }
                                }
                                Text {
                                    anchors.centerIn: parent
                                    width: parent.width - 20
                                    visible: appController.filteredFields.length === 0
                                    text: appController.sourceLoaded ? "No matching fields." : "Import a CSV or Excel workbook to browse its source fields."
                                    color: "#76838d"
                                    font.pixelSize: 9
                                    wrapMode: Text.Wrap
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Button {
                                    visible: !appController.sourceLoaded
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    anchors.top: parent.verticalCenter
                                    anchors.topMargin: 24
                                    text: "Import data"
                                    Accessible.name: "Import data from Data fields pane"
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Choose a CSV file or Excel workbook to browse its source fields."
                                    background: Rectangle { radius: 3; color: parent.hovered ? "#e7f1f8" : "#f4f8fb"; border.color: "#cbdde9" }
                                    contentItem: Text { text: parent.text; color: "#315f7d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: root.runCommand("data.importFile")
                                }
                            }
                        }
                    }
                }

                RowLayout {
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    spacing: 0
                    ModelView {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        appController: root.studioController
                        onImportRequested: root.runCommand("data.importFile")
                    }
                    Rectangle {
                        Layout.preferredWidth: 210
                        Layout.fillHeight: true
                        color: "#ffffff"
                        border.color: "#d5d9dd"
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                color: "#f8f9fa"
                                Text { anchors.verticalCenter: parent.verticalCenter; anchors.left: parent.left; anchors.leftMargin: 12; text: "Properties"; color: "#344553"; font.pixelSize: 11; font.weight: Font.DemiBold }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: "#dce1e4" }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.margins: 12
                                spacing: 10
                                Text { text: "Model"; color: "#3a4c59"; font.pixelSize: 10; font.weight: Font.DemiBold }
                                Text { Layout.fillWidth: true; text: "Data source"; color: "#687681"; font.pixelSize: 9 }
                                TextField {
                                    Layout.fillWidth: true
                                    text: appController.sourceLoaded ? appController.sourceName : "No data source"
                                    readOnly: true
                                    font.pixelSize: 10
                                    color: "#5a6871"
                                    background: Rectangle { radius: 3; color: "#f7f8f9"; border.color: "#d6dce0" }
                                }
                                Text { text: "Tables"; color: "#687681"; font.pixelSize: 9 }
                                Text { text: String(appController.modelTables.length); color: "#334653"; font.pixelSize: 11 }
                                Text { text: "Relationships"; color: "#687681"; font.pixelSize: 9 }
                                Text { text: String(appController.modelRelationships.length); color: "#334653"; font.pixelSize: 11 }
                                Item { Layout.fillHeight: true }
                                Text { Layout.fillWidth: true; text: "Model changes are read-only in this release."; color: "#7a858d"; font.pixelSize: 9; wrapMode: Text.Wrap }
                            }
                        }
                    }
                    Rectangle {
                        Layout.preferredWidth: 220
                        Layout.fillHeight: true
                        color: "#ffffff"
                        border.color: "#d5d9dd"
                        ColumnLayout {
                            anchors.fill: parent
                            spacing: 0
                            Rectangle {
                                Layout.fillWidth: true
                                Layout.preferredHeight: 38
                                color: "#f8f9fa"
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    Icon { name: "data"; color: "#64798a"; implicitWidth: 16; implicitHeight: 16 }
                                    Text { Layout.fillWidth: true; text: "Data"; color: "#344553"; font.pixelSize: 11; font.weight: Font.DemiBold }
                                    Text { text: String(appController.modelTables.length); color: "#73808a"; font.pixelSize: 9 }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: "#dce1e4" }
                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: appController.modelTables
                                clip: true
                                delegate: ColumnLayout {
                                    required property var modelData
                                    width: ListView.view.width
                                    spacing: 0
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 31
                                        Layout.leftMargin: 8
                                        Icon { name: "table"; color: "#637c8e"; implicitWidth: 15; implicitHeight: 15 }
                                        Text { Layout.fillWidth: true; text: String(modelData); color: "#3f505d"; font.pixelSize: 10; elide: Text.ElideRight }
                                    }
                                    Repeater {
                                        model: appController.sourceLoaded && appController.modelTables.length === 1 ? appController.headers : []
                                        delegate: RowLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 24
                                            Layout.leftMargin: 26
                                            Icon { name: "column"; color: "#85939c"; implicitWidth: 12; implicitHeight: 12 }
                                            Text { Layout.fillWidth: true; text: String(modelData); color: "#586872"; font.pixelSize: 9; elide: Text.ElideRight }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            Rectangle {
                id: reportDock
                visible: appController.currentView === "Report" && root.inspectorVisible
                Layout.preferredWidth: visible ? ((root.filtersExpanded ? 145 : 24)
                                                  + (root.visualizationsVisible ? 160 : 24)
                                                  + (root.dataPaneExpanded ? 160 : 24)) : 0
                Layout.fillHeight: true
                color: "#ffffff"
                border.color: "#d4d9dd"
                RowLayout {
                    anchors.fill: parent
                    spacing: 0
                    Item {
                        Layout.preferredWidth: root.filtersExpanded ? 145 : 24
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: root.filtersExpanded ? "#ffffff" : "#f8f9fa"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: root.filtersExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 29
                                    Layout.leftMargin: 7
                                    Icon { name: "filter"; color: "#61798b"; implicitWidth: 14; implicitHeight: 14 }
                                    Text { Layout.fillWidth: true; text: "Filters"; color: "#354755"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    ToolButton {
                                        onClicked: root.filtersExpanded = false
                                        Accessible.name: "Collapse Filters pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Filters pane"
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapseLeft"; color: "#657784"; implicitWidth: 14; implicitHeight: 14 }
                                    }
                                }
                                ColumnLayout {
                                    visible: root.filtersExpanded
                                    Layout.fillWidth: true
                                    Layout.margins: 10
                                    spacing: 7
                                    Text { text: "Report filters"; color: "#64727d"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 86
                                        color: "#ffffff"
                                        border.color: "#d9dfe3"
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 6
                                            Text { text: "Region"; color: "#495b68"; font.pixelSize: 10; font.weight: Font.DemiBold }
                                            ComboBox {
                                                id: regionCombo
                                                Layout.fillWidth: true
                                                model: appController.regions
                                                currentIndex: Math.max(0, appController.regions.indexOf(appController.currentRegion))
                                                enabled: appController.sourceLoaded && appController.regions.length > 1
                                                onActivated: function(index) { appController.setRegionFilter(String(appController.regions[index])) }
                                                background: Rectangle {
                                                    radius: 3
                                                    color: "#ffffff"
                                                    border.color: regionCombo.activeFocus ? "#718da1" : "#ccd4da"
                                                }
                                                contentItem: Text {
                                                    leftPadding: 8
                                                    rightPadding: regionCombo.indicator.width + 6
                                                    text: regionCombo.displayText
                                                    color: regionCombo.enabled ? "#455661" : "#86919a"
                                                    font.pixelSize: 10
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideRight
                                                }
                                                delegate: ItemDelegate {
                                                    width: regionCombo.width
                                                    text: String(modelData)
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text {
                                                        text: String(modelData)
                                                        color: "#455661"
                                                        font.pixelSize: 10
                                                        verticalAlignment: Text.AlignVCenter
                                                        elide: Text.ElideRight
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Button {
                                        text: "Clear filters"
                                        enabled: appController.filterActive
                                        background: Rectangle { radius: 3; color: parent.enabled ? "#f3f5f6" : "#f7f8f9"; border.color: "#d7dde1" }
                                        contentItem: Text { text: parent.text; color: parent.enabled ? "#445762" : "#98a1a8"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        onClicked: root.runCommand("filter.clear")
                                    }
                                    Item { Layout.fillHeight: true }
                                    Text { Layout.fillWidth: true; text: "Page filters are not available in this release."; color: "#79858d"; font.pixelSize: 9; wrapMode: Text.Wrap }
                                }
                                ToolButton {
                                    visible: !root.filtersExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    padding: 0
                                    hoverEnabled: true
                                    focusPolicy: Qt.StrongFocus
                                    Accessible.name: "Expand Filters pane"
                                    Accessible.description: appController.filterActive
                                                            ? "Open Region filters. A filter is currently active."
                                                            : "Open the Region filter controls."
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Filters · Region"
                                    background: Rectangle {
                                        color: parent.activeFocus ? "#e5f1f8" : (parent.hovered ? "#eef3f6" : "#f8f9fa")
                                        border.color: parent.activeFocus ? "#0078D4" : "#e0e3e6"
                                    }
                                    contentItem: Item {
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 7; name: "filter"; color: "#8A6D1D"; implicitWidth: 15; implicitHeight: 15 }
                                        Text { anchors.centerIn: parent; text: "Filters"; rotation: -90; color: "#526573"; font.pixelSize: 8 }
                                        Rectangle {
                                            visible: appController.filterActive
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            anchors.bottom: parent.bottom
                                            anchors.bottomMargin: 7
                                            width: 7
                                            height: 7
                                            radius: 4
                                            color: "#D9A300"
                                        }
                                    }
                                    onClicked: root.filtersExpanded = true
                                }
                            }
                        }
                    }

                    Item {
                        Layout.preferredWidth: root.visualizationsVisible ? 160 : 24
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: "#ffffff"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: root.visualizationsVisible
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 29
                                    Layout.leftMargin: 7
                                    Layout.rightMargin: 3
                                    Icon { name: "visual"; color: "#107C71"; implicitWidth: 14; implicitHeight: 14 }
                                    Text { Layout.fillWidth: true; text: "Visualizations"; color: "#354755"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    ToolButton {
                                        padding: 0
                                        implicitWidth: 22
                                        implicitHeight: 22
                                        Accessible.name: "Collapse Visualizations pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Visualizations pane"
                                        onClicked: root.visualizationsVisible = false
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapsePane"; color: "#657784"; implicitWidth: 14; implicitHeight: 14 }
                                    }
                                }
                                Rectangle { visible: root.visualizationsVisible; Layout.fillWidth: true; height: 1; color: "#e1e5e8" }
                                ColumnLayout {
                                    visible: root.visualizationsVisible
                                    Layout.fillWidth: true
                                    Layout.fillHeight: false
                                    Layout.alignment: Qt.AlignTop
                                    Layout.leftMargin: 5
                                    Layout.rightMargin: 5
                                    Layout.topMargin: 4
                                    Layout.bottomMargin: 4
                                    spacing: 3
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Build visual"
                                        color: "#354755"
                                        font.pixelSize: 10
                                        font.weight: Font.DemiBold
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 26
                                        spacing: 2
                                        Repeater {
                                            model: [
                                                { label: "Build", icon: "visual", active: true },
                                                { label: "Format", icon: "paintBrush", active: false },
                                                { label: "Analytics", icon: "dataTrending", active: false }
                                            ]
                                            delegate: Button {
                                                required property var modelData
                                                Layout.fillWidth: true
                                                Layout.fillHeight: true
                                                enabled: Boolean(modelData.active)
                                                hoverEnabled: true
                                                padding: 1
                                                Accessible.name: String(modelData.label) + " visualization pane"
                                                Accessible.description: enabled ? "Build visual is available." : String(modelData.label) + " settings are not available in this release."
                                                ToolTip.visible: hovered && !enabled
                                                ToolTip.text: String(modelData.label) + " settings are not available in this release."
                                                background: Rectangle {
                                                    color: "transparent"
                                                    Rectangle {
                                                        anchors.left: parent.left
                                                        anchors.right: parent.right
                                                        anchors.bottom: parent.bottom
                                                        height: 2
                                                        color: modelData.active ? "#107c71" : "transparent"
                                                    }
                                                }
                                                contentItem: Icon {
                                                    name: String(modelData.icon)
                                                    color: parent.enabled ? "#107c71" : "#9ba5ad"
                                                    implicitWidth: 16
                                                    implicitHeight: 16
                                                }
                                            }
                                        }
                                    }
                                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e1e5e8" }
                                    Item {
                                        id: visualGallery
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 175

                                        Repeater {
                                            model: [
                                                { type: "bar", name: "Clustered bar chart", icon: "bar", accent: "#107C71", active: true },
                                                { type: "stackedBar", name: "Stacked bar chart", icon: "stackedBar" },
                                                { type: "bar100", name: "100% stacked bar chart", icon: "barCluster" },
                                                { type: "column", name: "Clustered column chart", icon: "column", accent: "#0078D4", active: true },
                                                { type: "stackedColumn", name: "Stacked column chart", icon: "stackedColumn" },
                                                { type: "column100", name: "100% stacked column chart", icon: "columnCluster" },
                                                { type: "line", name: "Line chart", icon: "line", accent: "#C65911", active: true },
                                                { type: "area", name: "Area chart", icon: "area" },
                                                { type: "stackedArea", name: "Stacked area chart", icon: "area" },
                                                { type: "lineStackedColumn", name: "Line and stacked column chart", icon: "combo" },
                                                { type: "lineClusteredColumn", name: "Line and clustered column chart", icon: "combo" },
                                                { type: "ribbon", name: "Ribbon chart", icon: "ribbonChart" },
                                                { type: "waterfall", name: "Waterfall chart", icon: "waterfall" },
                                                { type: "funnel", name: "Funnel chart", icon: "funnel" },
                                                { type: "scatter", name: "Scatter chart", icon: "scatter" },
                                                { type: "pie", name: "Pie chart", icon: "pie" },
                                                { type: "donut", name: "Donut chart", icon: "donut" },
                                                { type: "treemap", name: "Treemap", icon: "treemap" },
                                                { type: "map", name: "Map", icon: "map" },
                                                { type: "filledMap", name: "Filled map", icon: "filledMap" },
                                                { type: "shapeMap", name: "Shape map", icon: "map" },
                                                { type: "arcgisMap", name: "ArcGIS Maps", icon: "map" },
                                                { type: "gauge", name: "Gauge", icon: "gauge" },
                                                { type: "card", name: "Card", icon: "card" },
                                                { type: "kpi", name: "KPI", icon: "kpi" },
                                                { type: "slicer", name: "Slicer", icon: "slicer" },
                                                { type: "table", name: "Table", icon: "table" },
                                                { type: "matrix", name: "Matrix", icon: "matrix" },
                                                { type: "rScript", name: "R visual", icon: "script" },
                                                { type: "pythonScript", name: "Python visual", icon: "script" },
                                                { type: "keyInfluencers", name: "Key influencers", icon: "keyInfluencers" },
                                                { type: "decomposition", name: "Decomposition tree", icon: "decomposition" },
                                                { type: "qa", name: "Q&A visual", icon: "qaVisual" },
                                                { type: "scorecard", name: "Scorecard", icon: "kpi" },
                                                { type: "removed", name: "", icon: "" },
                                                { type: "visualFilter", name: "Visual filter", icon: "filter" },
                                                { type: "quickVisual", name: "Quick visual", icon: "filter" },
                                                { type: "smartVisual", name: "Smart visual", icon: "filter" },
                                                { type: "image", name: "Image", icon: "image" },
                                                { type: "moreVisuals", name: "More visuals", icon: "apps" }
                                            ]
                                            delegate: Item {
                                                id: visualTypeTile
                                                required property int index
                                                required property var modelData
                                                property bool typeSelected: Boolean(modelData.active) && appController.selectedChartType === modelData.type
                                                x: (index % 6) * (visualGallery.width / 6)
                                                y: Math.floor(index / 6) * (visualGallery.height / 7)
                                                width: visualGallery.width / 6
                                                height: visualGallery.height / 7
                                                Rectangle {
                                                    anchors.fill: parent
                                                    visible: visualTypeTile.modelData.type === "removed"
                                                    color: "#ffffff"
                                                    Accessible.ignored: true
                                                }
                                                HoverHandler {
                                                    id: visualTypeHover
                                                    enabled: visualTypeTile.modelData.type !== "removed"
                                                }
                                                ToolTip.visible: visualTypeHover.hovered
                                                ToolTip.text: Boolean(modelData.active)
                                                        ? (appController.selectedVisual
                                                           ? "Set chart type: " + String(modelData.name)
                                                           : "Add a monthly revenue visual as " + String(modelData.name))
                                                        : String(modelData.name) + " is not available in this release."
                                                Button {
                                                    anchors.fill: parent
                                                    visible: visualTypeTile.modelData.type !== "removed"
                                                    enabled: Boolean(visualTypeTile.modelData.active)
                                                    padding: 1
                                                    hoverEnabled: true
                                                    Accessible.name: String(visualTypeTile.modelData.name) + " visual"
                                                    Accessible.description: enabled
                                                            ? (visualTypeTile.typeSelected ? "Selected chart type. " : "")
                                                              + (appController.selectedVisual
                                                                 ? "Set the selected chart to " + String(visualTypeTile.modelData.name).toLowerCase() + "."
                                                                 : "Add a monthly revenue chart using this chart type.")
                                                        : String(visualTypeTile.modelData.name) + " visuals are not available in this release."
                                                    background: Rectangle {
                                                        radius: 2
                                                        color: visualTypeTile.typeSelected ? "#2878c8" : (visualTypeHover.hovered && parent.enabled ? "#33d9e2e7" : "transparent")
                                                        opacity: visualTypeTile.typeSelected ? 0.12 : 1
                                                        border.width: visualTypeTile.typeSelected || parent.activeFocus ? 1 : 0
                                                        border.color: parent.activeFocus ? "#0078D4" : "#8aaebf"
                                                    }
                                                    contentItem: Item {
                                                        Accessible.ignored: true
                                                        Icon {
                                                            anchors.centerIn: parent
                                                            name: String(visualTypeTile.modelData.icon || "question")
                                                            color: visualTypeTile.modelData.accent || "#647382"
                                                            implicitWidth: 19
                                                            implicitHeight: 19
                                                        }
                                                    }
                                                    onClicked: {
                                                        if (!appController.selectedVisual)
                                                            root.runCommand("report.addMonthly")
                                                        root.runCommand("chart.type." + String(visualTypeTile.modelData.type))
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e1e5e8" }
                                    Text {
                                        Layout.fillWidth: true
                                        text: "Values"
                                        color: "#354755"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 22
                                        color: "#ffffff"
                                        border.color: "#cfd5d9"
                                        border.width: 1
                                        Text {
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 4
                                            verticalAlignment: Text.AlignVCenter
                                            text: appController.selectedVisual && appController.sourceLoaded ? "Revenue" : "Add data fields here"
                                            color: appController.selectedVisual && appController.sourceLoaded ? "#425563" : "#78858d"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        Layout.topMargin: 2
                                        text: "Drill through"
                                        color: "#354755"
                                        font.pixelSize: 9
                                        font.weight: Font.DemiBold
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 17
                                        Text { Layout.fillWidth: true; text: "Cross-report"; color: "#52616b"; font.pixelSize: 9 }
                                        Item {
                                            Layout.preferredWidth: 24
                                            Layout.preferredHeight: 12
                                            Accessible.name: "Cross-report drill-through; unavailable and off"
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 6
                                                color: "#c6ccd0"
                                                Rectangle {
                                                    width: 8
                                                    height: 8
                                                    anchors.left: parent.left
                                                    anchors.leftMargin: 2
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    radius: 4
                                                    color: "#ffffff"
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 17
                                        Text { Layout.fillWidth: true; text: "Keep all filters"; color: "#52616b"; font.pixelSize: 9 }
                                        Item {
                                            Layout.preferredWidth: 24
                                            Layout.preferredHeight: 12
                                            Accessible.name: "Keep all filters; fixed on"
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 6
                                                color: "#107c71"
                                                Rectangle {
                                                    width: 8
                                                    height: 8
                                                    anchors.right: parent.right
                                                    anchors.rightMargin: 2
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    radius: 4
                                                    color: "#ffffff"
                                                }
                                            }
                                        }
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 20
                                        color: "#ffffff"
                                        border.color: "#cfd5d9"
                                        Text {
                                            anchors.fill: parent
                                            anchors.leftMargin: 6
                                            anchors.rightMargin: 4
                                            verticalAlignment: Text.AlignVCenter
                                            text: "Add drill-through fields here"
                                            color: "#78858d"
                                            font.pixelSize: 8
                                            elide: Text.ElideRight
                                        }
                                    }
                                }
                                ToolButton {
                                    visible: !root.visualizationsVisible
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    padding: 0
                                    hoverEnabled: true
                                    focusPolicy: Qt.StrongFocus
                                    Accessible.name: "Expand Visualizations pane"
                                    Accessible.description: "Open chart type and report visual controls."
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Visualizations"
                                    background: Rectangle {
                                        color: parent.activeFocus ? "#e5f1f8" : (parent.hovered ? "#eef3f6" : "#f8f9fa")
                                        border.color: parent.activeFocus ? "#0078D4" : "#e0e3e6"
                                    }
                                    contentItem: Item {
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 9; name: "visual"; color: "#107C71"; implicitWidth: 17; implicitHeight: 17 }
                                        Text { anchors.centerIn: parent; text: "Visualizations"; rotation: -90; color: "#526573"; font.pixelSize: 9 }
                                    }
                                    onClicked: root.visualizationsVisible = true
                                }
                            }
                        }
                    }

                    Item {
                        Layout.preferredWidth: root.dataPaneExpanded ? 160 : 24
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: root.dataPaneExpanded ? "#ffffff" : "#f8f9fa"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: root.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 29
                                    Layout.leftMargin: 7
                                    Icon { name: "data"; color: "#60798b"; implicitWidth: 14; implicitHeight: 14 }
                                    Text { Layout.fillWidth: true; text: "Data"; color: "#354755"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    ToolButton {
                                        padding: 0
                                        implicitWidth: 22
                                        implicitHeight: 22
                                        onClicked: root.dataPaneExpanded = false
                                        Accessible.name: "Collapse Data pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Data pane"
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapsePane"; color: "#657784"; implicitWidth: 14; implicitHeight: 14 }
                                    }
                                }
                                TextField {
                                    visible: root.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 24
                                    Layout.leftMargin: 7
                                    Layout.rightMargin: 7
                                    text: root.fieldSearchQuery
                                    placeholderText: "Search fields"
                                    enabled: appController.sourceLoaded
                                    font.pixelSize: 10
                                    color: "#40515e"
                                    onTextChanged: {
                                        if (root.fieldSearchQuery !== text)
                                            root.fieldSearchQuery = text
                                        appController.setFieldQuery(text)
                                    }
                                    Accessible.name: "Search data fields"
                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: "#cfd7dd" }
                                }
                                Text {
                                    visible: root.dataPaneExpanded && appController.sourceLoaded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 21
                                    Layout.leftMargin: 9
                                    Layout.rightMargin: 7
                                    text: appController.rowCount + " rows · " + appController.columnCount + " fields"
                                    color: "#587488"
                                    font.pixelSize: 8
                                    elide: Text.ElideRight
                                    Accessible.name: text
                                }
                                ListView {
                                    visible: root.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    model: appController.filteredFields
                                    clip: true
                                    delegate: RowLayout {
                                        required property var modelData
                                        width: ListView.view.width
                                        height: 22
                                        spacing: 5
                                        Layout.leftMargin: 8
                                        Icon {
                                            name: ["Revenue", "Cost", "Margin", "Units", "Orders"].indexOf(String(modelData)) >= 0 ? "measure" : "column"
                                            color: ["Revenue", "Cost", "Margin", "Units", "Orders"].indexOf(String(modelData)) >= 0 ? "#0078D4" : "#107C71"
                                            implicitWidth: 14
                                            implicitHeight: 14
                                        }
                                        Text {
                                            Layout.fillWidth: true
                                            text: String(modelData)
                                            color: "#3f505d"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                            Accessible.name: String(modelData) + " field; listed for reference"
                                        }
                                    }
                                    Text {
                                        anchors.centerIn: parent
                                        visible: appController.filteredFields.length === 0
                                        text: appController.sourceLoaded ? "No matching fields" : "Import a CSV or Excel workbook to browse its fields."
                                        color: "#76838d"
                                        font.pixelSize: 9
                                        wrapMode: Text.Wrap
                                    }
                                    Button {
                                        visible: !appController.sourceLoaded
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.top: parent.verticalCenter
                                        anchors.topMargin: 16
                                        text: "Import data"
                                        Accessible.name: "Import data from Data pane"
                                        background: Rectangle { radius: 3; color: parent.hovered ? "#e7f1f8" : "#f4f8fb"; border.color: "#cbdde9" }
                                        contentItem: Text { text: parent.text; color: "#315f7d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        onClicked: root.runCommand("data.importFile")
                                    }
                                }
                                ToolButton {
                                    visible: !root.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    padding: 0
                                    hoverEnabled: true
                                    focusPolicy: Qt.StrongFocus
                                    Accessible.name: "Expand Data pane"
                                    Accessible.description: appController.sourceLoaded
                                                            ? String(appController.columnCount) + " fields available. Open searchable field list."
                                                            : "No data source loaded. Open the Data pane for import options."
                                    ToolTip.visible: hovered
                                    ToolTip.text: appController.sourceLoaded
                                                  ? "Data · " + appController.columnCount + " fields"
                                                  : "Data · no source"
                                    background: Rectangle {
                                        color: parent.activeFocus ? "#e5f1f8" : (parent.hovered ? "#eef3f6" : "#f8f9fa")
                                        border.color: parent.activeFocus ? "#0078D4" : "#e0e3e6"
                                    }
                                    contentItem: Item {
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 7; name: "data"; color: "#0078D4"; implicitWidth: 15; implicitHeight: 15 }
                                        Text { anchors.centerIn: parent; text: "Data"; rotation: -90; color: "#526573"; font.pixelSize: 8 }
                                    }
                                    onClicked: root.dataPaneExpanded = true
                                }
                            }
                        }
                    }
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 31
            Layout.fillHeight: false
            Layout.minimumHeight: 31
            Layout.maximumHeight: 31
            spacing: 0
            Rectangle { Layout.preferredWidth: root.navigationVisible ? 32 : 0; Layout.fillHeight: true; color: "#f8f9fa"; border.color: "#d6dbe0" }
                                RowLayout {
                                    visible: appController.currentView === "Report"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 4
                Repeater {
                    model: appController.pages
                    delegate: Button {
                        required property int index
                        required property var modelData
                        Layout.preferredWidth: Math.max(90, pageLabel.implicitWidth + 28)
                        Layout.fillHeight: true
                        text: String(modelData.name)
                        onClicked: appController.setActivePage(index)
                        background: Rectangle {
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.topMargin: 5
                            anchors.bottomMargin: 4
                            radius: 4
                            color: index === appController.activePageIndex ? "#e8eff3" : "transparent"
                            border.color: index === appController.activePageIndex ? "#cedbe3" : "transparent"
                        }
                        contentItem: Text {
                            id: pageLabel
                            text: String(modelData.name)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: "#506372"
                            font.pixelSize: 10
                        }
                    }
                }
                ToolButton {
                    text: "+"
                    Accessible.name: "Add report page"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "+"; color: "#55728a"; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.runCommand("report.addPage")
                }
                Item { Layout.fillWidth: true }
                Text { text: appController.activePageName; color: "#6d7b86"; font.pixelSize: 9; Layout.rightMargin: 10 }
            }
            Item { visible: appController.currentView !== "Report"; Layout.fillWidth: true }
            Rectangle { visible: reportDock.visible; Layout.preferredWidth: reportDock.width; Layout.fillHeight: true; color: "#ffffff"; border.color: "#d4d9dd" }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 22
            Layout.fillHeight: false
            Layout.minimumHeight: 22
            Layout.maximumHeight: 22
            color: "#ffffff"
            border.color: "#d4d9dd"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 12
                spacing: 8
                Text {
                    Layout.fillWidth: true
                    text: appController.statusMessage
                    color: "#687782"
                    font.pixelSize: 9
                    elide: Text.ElideRight
                }
                Text { text: appController.currentView + " view"; color: "#78858e"; font.pixelSize: 9 }
                Rectangle { width: 1; Layout.fillHeight: true; color: "#d9dee2" }
                ToolButton {
                    id: zoomOutButton
                    visible: appController.currentView === "Report"
                    text: "−"
                    padding: 0
                    implicitWidth: 20
                    implicitHeight: 18
                    Accessible.name: "Zoom out"
                    background: Rectangle { radius: 3; color: zoomOutButton.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "−"; color: "#526a7b"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.runCommand("view.zoomOut")
                }
                Slider {
                    id: zoomSlider
                    visible: appController.currentView === "Report"
                    Layout.preferredWidth: 105
                    from: 0.15
                    to: 1.5
                    value: root.reportZoom
                    onMoved: { root.fitZoom = false; root.reportZoom = value }
                    Accessible.name: "Report zoom"
                    background: Rectangle {
                        x: zoomSlider.leftPadding
                        y: zoomSlider.topPadding + zoomSlider.availableHeight / 2 - height / 2
                        width: zoomSlider.availableWidth
                        height: 3
                        radius: 2
                        color: "#d9dfe3"
                        Rectangle { width: zoomSlider.visualPosition * parent.width; height: parent.height; radius: 2; color: "#6f899a" }
                    }
                    handle: Rectangle {
                        x: zoomSlider.leftPadding + zoomSlider.visualPosition * (zoomSlider.availableWidth - width)
                        y: zoomSlider.topPadding + zoomSlider.availableHeight / 2 - height / 2
                        implicitWidth: 12
                        implicitHeight: 12
                        radius: 6
                        color: "#ffffff"
                        border.color: "#6f899a"
                    }
                }
                ToolButton {
                    id: zoomInButton
                    visible: appController.currentView === "Report"
                    text: "+"
                    padding: 0
                    implicitWidth: 20
                    implicitHeight: 18
                    Accessible.name: "Zoom in"
                    background: Rectangle { radius: 3; color: zoomInButton.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "+"; color: "#526a7b"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.runCommand("view.zoomIn")
                }
                Button {
                    visible: appController.currentView === "Report"
                    text: Math.round(root.reportZoom * 100) + "%"
                    flat: true
                    padding: 2
                    font.pixelSize: 9
                    Accessible.name: "Zoom percentage; activate to fit page"
                    background: Rectangle { color: "transparent" }
                    contentItem: Text { text: parent.text; color: "#62727d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: root.runCommand("view.zoomFit")
                }
            }
        }
    }

    function hasAnyKpis() {
        const visuals = appController.activePageVisuals
        for (let i = 0; i < visuals.length; ++i)
            if (String(visuals[i]).indexOf(" KPI") >= 0) return true
        return false
    }

    function hasAnyCharts() {
        const visuals = appController.activePageVisuals
        return visuals.indexOf("Monthly revenue") >= 0 || visuals.indexOf("Region revenue") >= 0
    }

    onClosing: function(close) {
        if (!appController.confirmClose())
            close.accepted = false
    }

    Component.onCompleted: {
        root.lastWorkspaceView = String(appController.currentView)
        root.selectRibbonForView(root.lastWorkspaceView)
        Qt.callLater(root.zoomToFit)
    }
}
