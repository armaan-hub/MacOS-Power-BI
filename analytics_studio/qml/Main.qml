import QtQuick 6.5
import QtQuick.Controls 6.5
import QtQuick.Layouts 6.5

ApplicationWindow {
    id: mainWindow
    visible: true
    width: 1740
    height: 1100
    minimumWidth: 1040
    minimumHeight: 680
    title: mainWindow.studioController.windowTitle
    color: "#f1f2f3"
    required property var studioController
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
    property var selectedReportFilterValues: []
    readonly property var kpiNames: mainWindow.studioController.reportKpiNames
    readonly property var kpiColors: ["#107C71", "#0078D4", "#8764B8", "#D9A300", "#C65911"]

    readonly property var ribbonTabs: ["File", "Home", "Insert", "Modeling", "View", "Optimize", "Help"]
    readonly property var dataHomeGroups: [
        { title: "Data", actions: [
            { label: "Get data", visibleLabel: "Get data", width: 48, iconName: "getData", commandId: "data.openPicker", splitGetData: true, description: "Choose a connector from the full data source picker." },
            { label: "Excel workbook", visibleLabel: "Excel\nworkbook", width: 50, iconName: "excel", commandId: "data.importExcel", description: "Import a workbook from an Excel file." },
            { label: "OneLake catalog", visibleLabel: "OneLake\ncatalog", width: 50, iconName: "databaseLink", commandId: "disabled.oneLake", available: false, description: "OneLake connections require an external service and are not available in this local release." },
            { label: "SQL Server", visibleLabel: "SQL Server", width: 44, iconName: "database", commandId: "data.sqlServer", description: "Connect to SQL Server over ODBC, preview a table or view, and import it locally." },
            { label: "Enter data", visibleLabel: "Enter\ndata", width: 38, iconName: "tableAdd", commandId: "data.source.enterData", description: "Create a local table from typed or pasted delimited data." },
            { label: "Dataverse", visibleLabel: "Dataverse", width: 46, iconName: "table", commandId: "disabled.dataverse", available: false, description: "Dataverse connections require an external service and are not available in this local release." },
            { label: "Recent sources", visibleLabel: "Recent\nsources", width: 46, iconName: "history", commandId: "data.recentSources", description: "Show a recently loaded data source." },
        ]},
        { title: "Queries", actions: [
            { label: "Transform data", visibleLabel: "Transform\ndata", width: 48, iconName: "tableEdit", commandId: "data.transform", description: "Preview and apply local steps to the active table." },
            { label: "Refresh", visibleLabel: "Refresh", width: 42, iconName: "refresh", commandId: "data.refresh", description: "Reload the active linked source and its included dependent queries." },
            { label: "Refresh all", visibleLabel: "Refresh\nall", width: 46, iconName: "refresh", commandId: "data.refreshAll", description: "Reload every supported linked source and rebuild included saved queries." }
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
                { label: "Export data", visibleLabel: "Export", iconName: "share", commandId: "project.exportData", description: "Export the active table to a CSV file." }
            ]}
        ]},
        { groups: [
            { title: "Clipboard", actions: [
                { label: "Paste", visibleLabel: "Paste", width: 28, iconName: "paste", commandId: "format.paste", description: "Paste a visual from the clipboard." },
                { label: "Cut", visibleLabel: "Cut", width: 28, iconName: "cut", commandId: "format.cut", description: "Cut the selected visual." },
                { label: "Copy", visibleLabel: "Copy", width: 28, iconName: "copy", commandId: "format.copy", description: "Copy the selected visual." },
                { label: "Format painter", visibleLabel: "Format\npainter", width: 40, iconName: "formatPainter", commandId: "format.painter", description: "Copy format of the selected report visual." }
            ]},
            { title: "Data", actions: [
                { label: "Get data", visibleLabel: "Get data", width: 48, iconName: "getData", commandId: "data.openPicker", splitGetData: true, description: "Choose a connector from the full data source picker." },
                { label: "Excel workbook", visibleLabel: "Excel\nworkbook", width: 50, iconName: "excel", commandId: "data.importExcel", description: "Import a workbook from an Excel file." },
                { label: "OneLake catalog", visibleLabel: "OneLake\ncatalog", width: 50, iconName: "databaseLink", commandId: "disabled.oneLake", available: false, description: "OneLake connections require an external service and are not available in this local release." },
                { label: "SQL Server", visibleLabel: "SQL Server", width: 44, iconName: "database", commandId: "data.sqlServer", description: "Connect to SQL Server over ODBC, preview a table or view, and import it locally." },
                { label: "Enter data", visibleLabel: "Enter\ndata", width: 38, iconName: "tableAdd", commandId: "data.source.enterData", description: "Create a local table from typed or pasted delimited data." },
                { label: "Dataverse", visibleLabel: "Dataverse", width: 46, iconName: "table", commandId: "disabled.dataverse", available: false, description: "Dataverse connections require an external service and are not available in this local release." },
                { label: "Recent sources", visibleLabel: "Recent\nsources", width: 46, iconName: "history", commandId: "data.recentSources", description: "Show a recently loaded data source." }
            ]},
            { title: "Queries", actions: [
                { label: "Transform data", visibleLabel: "Transform\ndata", width: 42, iconName: "tableEdit", commandId: "data.transform", description: "Preview and apply local steps to the active table." },
                { label: "Refresh", visibleLabel: "Refresh", width: 30, iconName: "refresh", commandId: "data.refresh", description: "Reload the active linked source and its included dependent queries." },
                { label: "Refresh all", visibleLabel: "Refresh\nall", width: 38, iconName: "refresh", commandId: "data.refreshAll", description: "Reload every supported linked source and rebuild included saved queries." }
            ]},
            { title: "Insert", actions: [
                { label: "New visual", visibleLabel: "New\nvisual", iconName: "visual", commandId: "report.addMonthly", description: "Add a monthly revenue visual to this page." },
                { label: "Text box", visibleLabel: "Text box", iconName: "text", commandId: "disabled.textBox", available: false, description: "Report text boxes are not available in this release." },
                { label: "More visuals", visibleLabel: "More\nvisuals", width: 40, iconName: "visual", commandId: "insert.moreVisuals", hasDropdown: true, description: "Browse visuals from AppSource or your files." }
            ]},
            { title: "Calculations", actions: [
                { label: "New visual calculation", visibleLabel: "New visual\ncalculation", width: 60, iconName: "dataLine", commandId: "disabled.visualCalculation", available: false, description: "Visual calculations are not available in this release." },
                { label: "New measure", visibleLabel: "New\nmeasure", width: 40, iconName: "measure", commandId: "data.newMeasure", description: "Create a local DAX measure for the loaded table." },
                { label: "Quick measure", visibleLabel: "Quick\nmeasure", width: 40, iconName: "quickMeasure", commandId: "data.quickMeasure", description: "Create a sum, average, or count measure for a selected field." }
            ]},
            { title: "Sensitivity", actions: [
                { label: "Sensitivity", visibleLabel: "Sensitivity", width: 62, iconName: "security", commandId: "disabled.sensitivity", available: false, description: "Sensitivity labels are not available in this release." }
            ]},
            { title: "Share", actions: [
                { label: "Publish", visibleLabel: "Publish", width: 42, iconName: "share", commandId: "service.publish", description: "Publishing is not available in this release." }
            ]},
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
                { label: "Buttons", visibleLabel: "Buttons", width: 46, hasDropdown: false, appearanceAvailable: true, iconName: "button", commandId: "insert.buttons", description: "Insert a clickable report button to trigger actions." },
                { label: "Shapes", visibleLabel: "Shapes", width: 43, hasDropdown: true, appearanceAvailable: true, iconName: "shape", commandId: "insert.shapes", available: false, description: "Report shape objects are not available in this release." },
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
                { label: "Manage relationships", visibleLabel: "Manage\nrelationships", width: 72, iconName: "relationship", commandId: "model.manageRelationships", description: "Create, edit, or remove relationships between loaded model tables." }
            ]},
            { title: "Calculations", actions: [
                { label: "New visual calculation", visibleLabel: "New visual\ncalculation", width: 56, iconName: "dataLine", commandId: "disabled.visualCalculation", available: false, description: "Visual calculations are not available in this release." },
                { label: "New measure", visibleLabel: "New\nmeasure", width: 40, iconName: "measure", commandId: "data.newMeasure", description: "Create a local DAX measure for the loaded table." },
                { label: "Quick measure", visibleLabel: "Quick\nmeasure", width: 40, iconName: "quickMeasure", commandId: "data.quickMeasure", description: "Create a sum, average, or count measure for a selected field." },
                { label: "New column", visibleLabel: "New\ncolumn", iconName: "column", commandId: "model.newCalculatedColumn", description: "Create, edit, or remove a local DAX calculated column on the active table." },
                { label: "New table", visibleLabel: "New\ntable", iconName: "tableAdd", commandId: "newCalculatedTable", description: "Create a DISTINCT calculated table from a loaded model column." }
            ]},
            { title: "Calendars", actions: [
                { label: "New calendar table", visibleLabel: "New calendar\ntable", width: 52, iconName: "calendar", commandId: "model.newCalendarTable", description: "Generate a saved, contiguous calendar table from dates or the model's date columns." },
                { label: "Mark as date table", visibleLabel: "Mark as\ndate table", width: 48, iconName: "calendar", commandId: "model.markDateTable", description: "Mark or unmark a loaded Date or DateTime column as a date table." }
            ]},
            { title: "Page refresh", actions: [
                { label: "Change detection", visibleLabel: "Change\ndetection", width: 56, iconName: "refresh", commandId: "disabled.changeDetection", available: false, description: "Change detection is not available in this release." }
            ]},
            { title: "Parameters", actions: [
                { label: "New parameter", visibleLabel: "New\nparameter", width: 58, iconName: "form", commandId: "disabled.parameter", available: false, description: "Parameters are not available in this release." }
            ]},
            { title: "Security", actions: [
                { label: "Manage roles", visibleLabel: "Manage\nroles", width: 48, iconName: "security", commandId: "security.manageRoles", description: "Create and edit security roles for the dataset." },
                { label: "View as", visibleLabel: "View as", width: 42, iconName: "eye", commandId: "security.viewAs", description: "View the report as a specific security role." }
            ]},
            { title: "Q&A", actions: [
                { label: "Q&A setup", visibleLabel: "Q&A\nsetup", width: 46, iconName: "question", commandId: "ai.qa", available: true, description: "Q&A setup is not available in this release." },
                { label: "Language", visibleLabel: "Language", width: 58, iconName: "format", commandId: "disabled.language", available: false, description: "Natural language configuration is not available in this release." },
                { label: "Linguistic schema", visibleLabel: "Linguistic\nschema", width: 58, iconName: "math", commandId: "disabled.linguisticSchema", available: false, description: "Linguistic schema editing is not available in this release." }
            ]}
        ]},
        { groups: [
            { title: "Themes", actions: [
                { label: "Default theme", visibleLabel: "Default\ntheme", iconName: "paintBrush", commandId: "theme.default", description: "Apply the default Power BI theme." },
                { label: "Executive theme", visibleLabel: "Executive\ntheme", iconName: "paintBrush", commandId: "theme.executive", description: "Apply a dark blue/grey corporate theme." },
                { label: "High Contrast", visibleLabel: "High\nContrast", iconName: "paintBrush", commandId: "theme.highContrast", description: "Apply High Contrast theme for accessibility." },
                { label: "Sunset theme", visibleLabel: "Sunset\ntheme", iconName: "paintBrush", commandId: "theme.sunset", description: "Apply the Sunset warm color theme." }
            ]},
            { title: "Scale to fit", actions: [
                { label: "Page view", visibleLabel: "Page view", iconName: "fit", commandId: "view.zoomFit", description: "Fit the report page in the available workspace." },
                { label: "Mobile layout", visibleLabel: "Mobile\nlayout", iconName: "phone", commandId: "view.mobileLayout", description: "Mobile report layout is not available in this release." }
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
        if (mainWindow.studioController.currentView === "Data" && tabName === "Home")
            return dataHomeGroups
        return tabDefinition.groups || []
    }

    function selectRibbonForView(viewName) {
        ribbonTabName = viewName === "Model" ? "Modeling" : "Home"
    }

    function navigateToView(viewName) {
        mainWindow.studioController.setCurrentView(viewName)
    }

    Connections {
        target: mainWindow.studioController
        function onStateChanged() {
            const viewName = String(mainWindow.studioController.currentView)
            if (mainWindow.lastWorkspaceView !== viewName) {
                mainWindow.lastWorkspaceView = viewName
                mainWindow.selectRibbonForView(viewName)
            }
        }
    }

    function runCommand(commandId) {
        switch (commandId) {
        case "project.new": clearFieldSearch(); mainWindow.studioController.executeCommand("newProject"); break
        case "project.open": clearFieldSearch(); mainWindow.studioController.executeCommand("openProject"); break
        case "project.save": mainWindow.studioController.executeCommand("saveProject"); break
        case "project.saveAs": mainWindow.studioController.executeCommand("saveProjectAs"); break
        case "project.exportData": mainWindow.studioController.executeCommand("exportData"); break
        case "data.openPicker": openGetDataPicker(null); break
        case "data.sqlServer": clearFieldSearch(); mainWindow.studioController.connectDataSource("microsoft_sql_server"); break
        case "data.importCsv": clearFieldSearch(); mainWindow.studioController.executeCommand("importCsv"); break
        case "data.importExcel": clearFieldSearch(); mainWindow.studioController.executeCommand("importExcel"); break
        case "data.importFile": clearFieldSearch(); mainWindow.studioController.executeCommand("importData"); break
        case "data.enterBlank": mainWindow.studioController.executeCommand("pasteData"); break
        case "data.sampleData": mainWindow.studioController.executeCommand("sampleData"); break
        case "data.transform": mainWindow.studioController.executeCommand("transformData"); break
        case "data.newMeasure": mainWindow.studioController.executeCommand("newMeasure"); break
        case "data.quickMeasure": mainWindow.studioController.executeCommand("quickMeasure"); break
        case "model.manageRelationships": mainWindow.studioController.executeCommand("manageRelationships"); break
        case "model.newCalculatedColumn": mainWindow.studioController.executeCommand("newCalculatedColumn"); break
        case "model.newCalendarTable": mainWindow.studioController.executeCommand("newCalendarTable"); break
        case "model.markDateTable": mainWindow.studioController.executeCommand("markDateTable"); break
        case "security.manageRoles": mainWindow.studioController.executeCommand("manageRoles"); break
        case "security.viewAs": mainWindow.studioController.executeCommand("viewAsRoles"); break
        case "service.publish": mainWindow.studioController.executeCommand("publishReport"); break
        case "view.mobileLayout": mainWindow.studioController.executeCommand("toggleMobileLayout"); break
        case "ai.qa": mainWindow.studioController.executeCommand("qaSetup"); break
        case "data.refresh": mainWindow.studioController.executeCommand("refreshSource"); break
        case "data.refreshAll": mainWindow.studioController.executeCommand("refreshAllSources"); break
        case "filter.clear": mainWindow.studioController.executeCommand("clearFilters"); break
        case "report.addPage": mainWindow.studioController.executeCommand("addPage"); break
        case "report.addMonthly": mainWindow.studioController.executeCommand("addMonthlyChart"); break
        case "report.addRegion": mainWindow.studioController.executeCommand("addRegionChart"); break
        case "insert.textBox":
            let tc = mainWindow.studioController.activeVisualObjects.length + 1;
            mainWindow.studioController.add_visual("text_box", "Text Box " + tc, 100, 100, 200, 80);
            break
        case "insert.image":
            let ic = mainWindow.studioController.activeVisualObjects.length + 1;
            mainWindow.studioController.add_visual("image", "Image " + ic, 100, 100, 250, 150);
            break
        case "insert.buttons":
            let bc = mainWindow.studioController.activeVisualObjects.length + 1;
            mainWindow.studioController.add_visual("button", "Button " + bc, 100, 100, 100, 35);
            break
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
        case "format.copy": mainWindow.studioController.copy_selected_visual(); break
        case "format.cut": mainWindow.studioController.cut_selected_visual(); break
        case "format.paste": mainWindow.studioController.paste_visual(); break
        case "format.painter": mainWindow.studioController.copy_format(); break
        case "arrange.bringToFront": mainWindow.studioController.bring_to_front(); break
        case "arrange.sendToBack": mainWindow.studioController.send_to_back(); break
        case "arrange.bringForward": mainWindow.studioController.bring_forward(); break
        case "arrange.sendBackward": mainWindow.studioController.send_backward(); break
        case "arrange.group": mainWindow.studioController.group_visuals(); break
        case "arrange.ungroup": mainWindow.studioController.ungroup_visuals(); break
        case "theme.default": mainWindow.studioController.set_report_theme("Default"); break
        case "theme.executive": mainWindow.studioController.set_report_theme("Executive"); break
        case "theme.highContrast": mainWindow.studioController.set_report_theme("High Contrast"); break
        case "theme.sunset": mainWindow.studioController.set_report_theme("Sunset"); break
        // Dynamic chart type handler below in default
        case "help.about": mainWindow.studioController.executeCommand("about"); break
        case "help.shortcuts": mainWindow.studioController.executeCommand("shortcuts"); break
        case "help.projectFormat": mainWindow.studioController.executeCommand("projectFormat"); break
        default:
            if (commandId.startsWith("chart.type.")) {
                mainWindow.studioController.set_visual_type(mainWindow.studioController.selectedVisual, commandId.substring(11))
            }
            break
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
            mainWindow.studioController.executeCommand("enterData")
            return
        case "insert.moreVisuals": showRibbonPopup("moreVisuals", sourceItem, sourceItem); return
        case "insert.buttons": mainWindow.runCommand(commandId); return
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
            Qt.callLater(function() { mainWindow.openGetDataPicker(focusTarget) })
            return
        }
        if (action.indexOf("recent.") === 0) {
            const recentIndex = Number(action.substring("recent.".length))
            Qt.callLater(function() {
                mainWindow.studioController.openRecentSource(recentIndex)
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        if (action === "source.csv") {
            Qt.callLater(function() {
                mainWindow.studioController.connectDataSource("file_text_csv")
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        if (action === "source.excel") {
            Qt.callLater(function() {
                mainWindow.studioController.connectDataSource("file_excel_workbook")
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        if (action === "source.json" || action === "source.xml" || action === "source.parquet") {
            Qt.callLater(function() {
                const sourceId = action === "source.json" ? "file_json"
                               : (action === "source.xml" ? "file_xml" : "file_parquet")
                mainWindow.studioController.connectDataSource(sourceId)
                if (focusTarget && focusTarget.visible)
                    focusTarget.forceActiveFocus()
            })
            return
        }
        mainWindow.studioController.reportStagedAction(label,
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
        if (reportOnly && mainWindow.studioController.currentView !== "Report") return false
        if (commandId === "data.refresh") return mainWindow.studioController.canRefreshSource
        if (commandId === "data.refreshAll") return mainWindow.studioController.canRefreshAllSources
        if (commandId === "model.manageRelationships") return mainWindow.studioController.canManageRelationships
        if (commandId === "model.markDateTable")
            return mainWindow.studioController.tableCatalog.some(function(table) { return Boolean(table.loaded) })
        if (commandId === "model.newCalculatedColumn") return mainWindow.studioController.sourceLoaded
        if (commandId === "data.transform") return mainWindow.studioController.sourceLoaded
        if (commandId === "project.exportData") return mainWindow.studioController.sourceLoaded
        if (commandId === "filter.clear") return mainWindow.studioController.filterActive
        return true
    }

    function commandUnavailableReason(commandId) {
        const reportOnly = commandId.startsWith("report.") || commandId.startsWith("chart.type.")
                || commandId === "filter.clear" || commandId === "view.filters"
                || commandId === "view.visualizations" || commandId === "view.dataPane"
                || commandId === "view.togglePanes" || commandId === "view.zoomFit"
                || commandId === "view.zoomIn" || commandId === "view.zoomOut"
                || commandId === "view.resetLayout"
        if (reportOnly && mainWindow.studioController.currentView !== "Report")
            return "Switch to Report view to use this command."
        if (commandId === "data.transform" && !mainWindow.studioController.sourceLoaded)
            return "Load a table before transforming data."
        if (commandId === "project.exportData" && !mainWindow.studioController.sourceLoaded)
            return "Load a table before exporting data."
        if (commandId === "data.refresh" && !mainWindow.studioController.canRefreshSource)
            return mainWindow.studioController.sourceLoaded
                    ? "Inline tables have no linked file to refresh."
                    : "Import data before refreshing."
        if (commandId === "data.refreshAll" && !mainWindow.studioController.canRefreshAllSources)
            return "Import or connect at least one linked source before refreshing all."
        if (commandId === "model.manageRelationships" && !mainWindow.studioController.canManageRelationships)
            return "Load at least two tables before managing relationships."
        if (commandId === "model.markDateTable"
                && !mainWindow.studioController.tableCatalog.some(function(table) { return Boolean(table.loaded) }))
            return "Load a model table before marking a date table."
        if (commandId === "model.newCalculatedColumn" && !mainWindow.studioController.sourceLoaded)
            return "Load a table before creating a calculated column."
        if (commandId === "filter.clear" && !mainWindow.studioController.filterActive)
            return "There is no active Region filter to clear."
        return ""
    }

    function clearFieldSearch() {
        fieldSearchQuery = ""
        mainWindow.studioController.setFieldQuery("")
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
                    iconColor: mainWindow.accentForIcon(String(modelData.iconName || "report"))
                    commandWidth: Math.max(ribbonGroup.compact ? 42 : 54, Math.round(Number(modelData.width || 34) * 1.08))
                    iconSize: ribbonGroup.compact ? 25 : 22
                    appearanceAvailable: modelData.appearanceAvailable === true
                    hasDropdown: modelData.hasDropdown === true
                    splitGetData: modelData.splitGetData === true
                    commandId: String(modelData.commandId || "")
                    description: String(modelData.description || "")
                    available: modelData.available === false ? false : mainWindow.commandAvailable(String(modelData.commandId || ""))
                    unavailableReason: mainWindow.commandUnavailableReason(String(modelData.commandId || ""))
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

    Shortcut {
        sequence: StandardKey.Delete
        onActivated: {
            let visName = mainWindow.studioController.selectedVisual
            if (visName && mainWindow.studioController.activeVisualObjects) {
                for (let i = 0; i < mainWindow.studioController.activeVisualObjects.length; ++i) {
                    if (mainWindow.studioController.activeVisualObjects[i].title === visName) {
                        mainWindow.studioController.remove_visual(mainWindow.studioController.activeVisualObjects[i].id)
                        break
                    }
                }
            }
        }
    }
    Shortcut {
        sequence: "Backspace"
        onActivated: {
            let visName = mainWindow.studioController.selectedVisual
            if (visName && mainWindow.studioController.activeVisualObjects && !focus) {
                for (let i = 0; i < mainWindow.studioController.activeVisualObjects.length; ++i) {
                    if (mainWindow.studioController.activeVisualObjects[i].title === visName) {
                        mainWindow.studioController.remove_visual(mainWindow.studioController.activeVisualObjects[i].id)
                        break
                    }
                }
            }
        }
    }

    GetDataDialog {
        id: getDataDialog
        objectName: "getDataDialog"
        controller: mainWindow.studioController
    }

    RibbonPopupMenu {
        id: ribbonPopupMenu
        objectName: "ribbonPopupMenu"
        controller: mainWindow.studioController
        onActionRequested: function(action, label, focusTarget) {
            mainWindow.handlePopupAction(action, label, focusTarget)
        }
    }

    ShapePalettePopup {
        id: shapePalette
        objectName: "shapePalette"
        controller: mainWindow.studioController
        onShapeChosen: function(shapeName) {
            const focusTarget = shapePalette.returnFocusItem
            let v_count = mainWindow.studioController.activeVisualObjects.length + 1;
            mainWindow.studioController.add_visual("shape", shapeName, 100, 100, 100, 100);
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
            MenuItem { text: "New Project"; onTriggered: mainWindow.runCommand("project.new") }
            MenuItem { text: "Open Project…"; onTriggered: mainWindow.runCommand("project.open") }
            MenuSeparator {}
            MenuItem { text: "Save"; onTriggered: mainWindow.runCommand("project.save") }
            MenuItem { text: "Save As…"; onTriggered: mainWindow.runCommand("project.saveAs") }
            MenuSeparator {}
            MenuItem { text: "Import data…"; onTriggered: mainWindow.runCommand("data.importFile") }
            MenuSeparator {}
            MenuItem { text: "Quit Analytics Studio"; onTriggered: mainWindow.studioController.executeCommand("quit") }
        }
        Menu {
            title: "View"
            MenuItem { text: "Report"; onTriggered: mainWindow.runCommand("view.report") }
            MenuItem { text: "Data"; onTriggered: mainWindow.runCommand("view.data") }
            MenuItem { text: "Model"; onTriggered: mainWindow.runCommand("view.model") }
            MenuSeparator {}
            MenuItem { text: "Fit to Page"; onTriggered: mainWindow.runCommand("view.zoomFit") }
            MenuItem { text: "Reset Layout"; onTriggered: mainWindow.runCommand("view.resetLayout") }
        }
        Menu {
            title: "Format"
            MenuItem { text: "Copy Visual"; onTriggered: mainWindow.runCommand("format.copy") }
            MenuItem { text: "Paste Visual"; onTriggered: mainWindow.runCommand("format.paste") }
            MenuItem { text: "Cut Visual"; onTriggered: mainWindow.runCommand("format.cut") }
            MenuSeparator {}
            MenuItem { text: "Format Painter"; onTriggered: mainWindow.runCommand("format.painter") }
            MenuSeparator {}
            MenuItem { text: "Bring Forward"; onTriggered: mainWindow.runCommand("arrange.bringForward") }
            MenuItem { text: "Send Backward"; onTriggered: mainWindow.runCommand("arrange.sendBackward") }
            MenuItem { text: "Bring to Front"; onTriggered: mainWindow.runCommand("arrange.bringToFront") }
            MenuItem { text: "Send to Back"; onTriggered: mainWindow.runCommand("arrange.sendToBack") }
            MenuSeparator {}
            MenuItem { text: "Group"; onTriggered: mainWindow.runCommand("arrange.group") }
            MenuItem { text: "Ungroup"; onTriggered: mainWindow.runCommand("arrange.ungroup") }
        }
        Menu {
            title: "Help"
            MenuItem { text: "About Analytics Studio"; onTriggered: mainWindow.runCommand("help.about") }
            MenuItem { text: "Keyboard Shortcuts"; onTriggered: mainWindow.runCommand("help.shortcuts") }
            MenuItem { text: "Project Format"; onTriggered: mainWindow.runCommand("help.projectFormat") }
        }
    }

    Shortcut { sequences: [StandardKey.New]; onActivated: mainWindow.runCommand("project.new") }
    Shortcut { sequences: [StandardKey.Open]; onActivated: mainWindow.runCommand("project.open") }
    Shortcut { sequences: [StandardKey.Save]; onActivated: mainWindow.runCommand("project.save") }
    Shortcut { sequences: [StandardKey.Copy]; onActivated: mainWindow.runCommand("format.copy") }
    Shortcut { sequences: [StandardKey.Paste]; onActivated: mainWindow.runCommand("format.paste") }
    Shortcut { sequences: [StandardKey.Cut]; onActivated: mainWindow.runCommand("format.cut") }
    Shortcut { sequences: [StandardKey.SaveAs]; onActivated: mainWindow.runCommand("project.saveAs") }
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
                    model: mainWindow.ribbonTabs
                    delegate: Button {
                        required property int index
                        required property var modelData
                            Layout.preferredWidth: Math.max(46, tabLabel.implicitWidth + 18)
                        Layout.fillHeight: true
                        text: String(modelData)
                        checkable: true
                        checked: mainWindow.ribbonTabName === String(modelData)
                        padding: 0
                        hoverEnabled: true
                        background: Rectangle { color: "transparent" }
                        contentItem: Text {
                            id: tabLabel
                            text: String(modelData)
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                            color: mainWindow.ribbonTabName === String(modelData) ? "#263a49" : "#52616e"
                            font.pixelSize: 11
                            font.weight: mainWindow.ribbonTabName === String(modelData) ? Font.DemiBold : Font.Normal
                        }
                        Rectangle {
                            visible: mainWindow.ribbonTabName === String(modelData)
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.bottom: parent.bottom
                            height: 2
                            color: "#107C71"
                        }
                        onClicked: mainWindow.ribbonTabName = String(modelData)
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
                currentIndex: mainWindow.ribbonIndexForName(mainWindow.ribbonTabName)
                Repeater {
                    model: mainWindow.ribbonDefinitions
                    delegate: Flickable {
                        required property int index
                        required property var modelData
                        property var tabDefinition: modelData
                        property string tabName: mainWindow.ribbonTabs[index]
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
                                model: mainWindow.groupsForRibbonTab(tabDefinition, tabName)
                                delegate: RibbonGroup {
                                    required property var modelData
                                    caption: String(modelData.title || "")
                                    commands: modelData.actions || []
                                    compact: Boolean(modelData.compact)
                                    onInvoked: function(id, sourceItem) { mainWindow.handleRibbonAction(id, sourceItem) }
                                    onDropdownInvoked: function(id, sourceItem) { mainWindow.handleRibbonDropdown(id, sourceItem) }
                                }
                            }
                        }
                    }
                }
            }
        }

        Rectangle {
            visible: mainWindow.studioController.sourceWarning !== ""
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
                    text: mainWindow.studioController.sourceWarning
                    color: "#66583d"
                    font.pixelSize: 10
                    elide: Text.ElideRight
                    Accessible.name: "Data source recovery warning"
                }
                Button {
                    text: "Relink data source"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#f2ead8" : "#f8f3e9"; border.color: "#e0d2b5" }
                    contentItem: Text { text: parent.text; color: "#705e3c"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: mainWindow.runCommand("data.importFile")
                }
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 300
            spacing: 0

            Rectangle {
                visible: mainWindow.navigationVisible
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
                                color: modelData.enabled && mainWindow.studioController.currentView === modelData.name ? "#e3f0ef" : (parent.hovered ? "#f0f4f6" : "transparent")
                                Rectangle {
                                    visible: modelData.enabled && mainWindow.studioController.currentView === modelData.name
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
                                    color: modelData.enabled ? (mainWindow.studioController.currentView === modelData.name ? "#0078D4" : mainWindow.accentForIcon(String(modelData.icon))) : "#a8afb5"
                                    width: 18
                                    height: 18
                                }
                            }
                            onClicked: mainWindow.navigateToView(String(modelData.name))
                        }
                    }
                    Item { Layout.fillHeight: true }
                }
            }

            StackLayout {
                id: viewStack
                Layout.fillWidth: true
                Layout.fillHeight: true
                currentIndex: mainWindow.studioController.currentView === "Report" ? 0
                              : (mainWindow.studioController.currentView === "Data" ? 1 : 2)
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
                        contentWidth: Math.max(width, 1280 * mainWindow.reportZoom + 8)
                        contentHeight: Math.max(height, 720 * mainWindow.reportZoom + 48)
                        ScrollBar.horizontal: ScrollBar { policy: ScrollBar.AsNeeded }
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        onWidthChanged: if (mainWindow.fitZoom) Qt.callLater(mainWindow.zoomToFit)
                        onHeightChanged: if (mainWindow.fitZoom) Qt.callLater(mainWindow.zoomToFit)

                        Item {
                            id: reportPagePositioner
                            width: reportViewport.contentWidth
                            height: reportViewport.contentHeight
                            Rectangle {
                                id: reportPage
                                width: 1280 * mainWindow.reportZoom
                                height: 720 * mainWindow.reportZoom
                                anchors.centerIn: parent
                                color: "#ffffff"
                                border.color: "#d0d4d8"
                                border.width: 1
                                clip: true
                                Item {
                                    id: reportPageBody
                                    width: 1280
                                    height: 720
                                    transform: Scale { xScale: mainWindow.reportZoom; yScale: mainWindow.reportZoom; origin.x: 0; origin.y: 0 }

                                    Item {
                                        anchors.fill: parent

                                        // Empty state overlay when no visual exists
                                        Item {
                                            objectName: "reportEmptyState"
                                            visible: mainWindow.studioController.activeVisualObjects.length === 0
                                            anchors.fill: parent
                                            ColumnLayout {
                                                anchors.centerIn: parent
                                                spacing: 12
                                                Text {
                                                    Layout.alignment: Qt.AlignHCenter
                                                    text: "Choose a visual from Insert to add it to this page."
                                                    color: "#30383e"
                                                    font.pixelSize: 22
                                                    font.weight: Font.DemiBold
                                                }
                                            }
                                        }

                                        Repeater {
                                            model: mainWindow.studioController.activeVisualObjects
                                            delegate: Item {
                                                x: Number(modelData.x)
                                                y: Number(modelData.y)
                                                width: Number(modelData.width)
                                                height: Number(modelData.height)

                                                ChartCard {
                                                    visible: modelData.type !== "button" && modelData.type !== "text_box" && modelData.type !== "image" && String(modelData.type).indexOf("shape:") !== 0 && modelData.type !== "shape"
                                                    anchors.fill: parent
                                                    title: String(modelData.title)
                                                    visualName: String(modelData.title)
                                                    chartType: String(modelData.type)
                                                    selected: mainWindow.studioController.selectedVisual === String(modelData.title)
                                                    seriesColor: modelData.color ? String(modelData.color) : "#0078D4" 
                                                    emptyMessage: "No data is available yet."

                                                    series: (modelData.type === "column" || modelData.type === "bar" || modelData.type === "line" || modelData.type === "area") ? mainWindow.studioController.visualSeries(String(modelData.title)) : []

                                                    filterOnCategory: true

                                                    onCategoryRequested: function(label) {
                                                        mainWindow.studioController.toggle_cross_filter(String(modelData.title), label)
                                                    }

                                                    onRequestedSelection: function(visualName) {
                                                        if (mainWindow.studioController.formatPainterActive) {
                                                            mainWindow.studioController.apply_format_painter(visualName)
                                                        }
                                                        mainWindow.studioController.selectVisual(visualName)
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "text_box"
                                                    anchors.fill: parent
                                                    color: "transparent"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "transparent"
                                                    border.width: 1
                                                    
                                                    TextArea {
                                                        anchors.fill: parent
                                                        anchors.margins: 4
                                                        text: modelData.text || "Type here..."
                                                        font.pixelSize: 14
                                                        wrapMode: Text.WordWrap
                                                        background: Rectangle { color: "transparent" }
                                                        color: "#202020"
                                                        onPressed: function(mouse) {
                                                            mainWindow.studioController.selectVisual(String(modelData.title))
                                                        }
                                                        onTextChanged: {
                                                            if (activeFocus) {
                                                                // In a real app we'd update the controller's property here
                                                            }
                                                        }
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "image"
                                                    anchors.fill: parent
                                                    color: "#f8f9fa"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "#cbd1d6"
                                                    border.width: 1
                                                    
                                                    Icon {
                                                        anchors.centerIn: parent
                                                        name: "image"
                                                        color: "#adb6bc"
                                                        implicitWidth: 48
                                                        implicitHeight: 48
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        onClicked: mainWindow.studioController.selectVisual(String(modelData.title))
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "slicer"
                                                    anchors.fill: parent
                                                    color: "#ffffff"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "#e1e5e8"
                                                    border.width: 1
                                                    
                                                    ColumnLayout {
                                                        anchors.fill: parent
                                                        anchors.margins: 6
                                                        spacing: 2
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: modelData.title
                                                            font.pixelSize: 11
                                                            color: "#5e6973"
                                                        }
                                                        ScrollView {
                                                            Layout.fillWidth: true
                                                            Layout.fillHeight: true
                                                            clip: true
                                                            ListView {
                                                                id: slicerList2
                                                                property string visualTitle: String(modelData.title)
                                                                model: modelData.type === "slicer" ? mainWindow.studioController.visualSeries(String(modelData.title)) : []
                                                                property var activeFilters: mainWindow.studioController.selectedCrossFiltersForVisual(String(modelData.title)) || []
                                                                delegate: Item {
                                                                    width: slicerList.width
                                                                    height: 22
                                                                    RowLayout {
                                                                        anchors.fill: parent
                                                                        spacing: 6
                                                                        Rectangle {
                                                                            Layout.preferredWidth: 14
                                                                            Layout.preferredHeight: 14
                                                                            border.width: 1
                                                                            border.color: "#333333"
                                                                            color: slicerList.activeFilters.indexOf(String(modelData.label)) !== -1 ? "#0078D4" : "transparent"
                                                                        }
                                                                        Text {
                                                                            Layout.fillWidth: true
                                                                            text: String(modelData.label)
                                                                            font.pixelSize: 11
                                                                            color: "#333333"
                                                                        }
                                                                    }
                                                                    MouseArea {
                                                                        anchors.fill: parent
                                                                        onClicked: {
                                                                            mainWindow.studioController.selectVisual(String(parent.parent.parent.parent.parent.modelData.title))
                                                                            mainWindow.studioController.toggle_cross_filter(String(parent.parent.parent.parent.parent.modelData.title), String(modelData.label))
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        propagateComposedEvents: true
                                                        onPressed: function(mouse) {
                                                            // We cannot swallow click if we want scrollbars/list items to work, 
                                                            // so let's just select
                                                            mainWindow.studioController.selectVisual(String(modelData.title))
                                                            mouse.accepted = false
                                                        }
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "button"
                                                    anchors.fill: parent
                                                    color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#e5f1f8" : "#f3f2f1"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "#cccccc"
                                                    border.width: 1
                                                    radius: 4

                                                    Text {
                                                        anchors.centerIn: parent
                                                        text: modelData.text || modelData.title
                                                        font.pixelSize: 12
                                                        color: "#333333"
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        onClicked: function(mouse) {
                                                            mainWindow.studioController.selectVisual(String(modelData.title))
                                                            // Execute Button Action (Control-click is standard, but here double click or regular click in view mode)
                                                            if (modelData.actionUrl && mouse.modifiers & Qt.ControlModifier) {
                                                                Qt.openUrlExternally(modelData.actionUrl)
                                                            }
                                                        }
                                                        onDoubleClicked: {
                                                            if (modelData.actionUrl) {
                                                                Qt.openUrlExternally(modelData.actionUrl)
                                                            }
                                                        }
                                                    }
                                                }

                                                Rectangle {
                                                    visible: String(modelData.type).indexOf("shape") === 0
                                                    anchors.fill: parent
                                                    color: "transparent"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "transparent"
                                                    border.width: 1
                                                    
                                                    ShapeGlyph {
                                                        anchors.fill: parent
                                                        anchors.margins: 4
                                                        shapeName: String(modelData.title)
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        onClicked: mainWindow.studioController.selectVisual(String(modelData.title))
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "slicer"
                                                    anchors.fill: parent
                                                    color: "#ffffff"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "#e1e5e8"
                                                    border.width: 1
                                                    
                                                    ColumnLayout {
                                                        anchors.fill: parent
                                                        anchors.margins: 6
                                                        spacing: 2
                                                        Text {
                                                            Layout.fillWidth: true
                                                            text: modelData.title
                                                            font.pixelSize: 11
                                                            color: "#5e6973"
                                                        }
                                                        ScrollView {
                                                            Layout.fillWidth: true
                                                            Layout.fillHeight: true
                                                            clip: true
                                                            ListView {
                                                                id: slicerList
                                                                property string visualTitle: String(modelData.title)
                                                                model: modelData.type === "slicer" ? mainWindow.studioController.visualSeries(String(modelData.title)) : []
                                                                property var activeFilters: mainWindow.studioController.selectedCrossFiltersForVisual(String(modelData.title)) || []
                                                                delegate: Item {
                                                                    width: slicerList.width
                                                                    height: 22
                                                                    RowLayout {
                                                                        anchors.fill: parent
                                                                        spacing: 6
                                                                        Rectangle {
                                                                            Layout.preferredWidth: 14
                                                                            Layout.preferredHeight: 14
                                                                            border.width: 1
                                                                            border.color: "#333333"
                                                                            color: slicerList.activeFilters.indexOf(String(modelData.label)) !== -1 ? "#0078D4" : "transparent"
                                                                        }
                                                                        Text {
                                                                            Layout.fillWidth: true
                                                                            text: String(modelData.label)
                                                                            font.pixelSize: 11
                                                                            color: "#333333"
                                                                        }
                                                                    }
                                                                    MouseArea {
                                                                        anchors.fill: parent
                                                                        onClicked: {
                                                                            mainWindow.studioController.selectVisual(String(parent.parent.parent.parent.parent.modelData.title))
                                                                            mainWindow.studioController.toggle_cross_filter(String(parent.parent.parent.parent.parent.modelData.title), String(modelData.label))
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        propagateComposedEvents: true
                                                        onPressed: function(mouse) {
                                                            // We cannot swallow click if we want scrollbars/list items to work, 
                                                            // so let's just select
                                                            mainWindow.studioController.selectVisual(String(modelData.title))
                                                            mouse.accepted = false
                                                        }
                                                    }
                                                }

                                                Rectangle {
                                                    visible: modelData.type === "button"
                                                    anchors.fill: parent
                                                    color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#e5f1f8" : "#f3f2f1"
                                                    border.color: mainWindow.studioController.selectedVisual === String(modelData.title) ? "#0078D4" : "#cccccc"
                                                    border.width: 1
                                                    radius: 4

                                                    Text {
                                                        anchors.centerIn: parent
                                                        text: modelData.text || modelData.title
                                                        font.pixelSize: 12
                                                        color: "#333333"
                                                    }
                                                    
                                                    MouseArea {
                                                        anchors.fill: parent
                                                        onClicked: function(mouse) {
                                                            mainWindow.studioController.selectVisual(String(modelData.title))
                                                            // Execute Button Action (Control-click is standard, but here double click or regular click in view mode)
                                                            if (modelData.actionUrl && mouse.modifiers & Qt.ControlModifier) {
                                                                Qt.openUrlExternally(modelData.actionUrl)
                                                            }
                                                        }
                                                        onDoubleClicked: {
                                                            if (modelData.actionUrl) {
                                                                Qt.openUrlExternally(modelData.actionUrl)
                                                            }
                                                        }
                                                    }
                                                }
                                                
                                                DragHandler {
                                                    target: parent
                                                    onActiveChanged: {
                                                        if (!active) {
                                                            mainWindow.studioController.move_visual(String(modelData.id), Math.round(parent.x / 10) * 10, Math.round(parent.y / 10) * 10);
                                                        }
                                                    }
                                                }
                                                
                                                Rectangle {
                                                    width: 14
                                                    height: 14
                                                    anchors.right: parent.right
                                                    anchors.bottom: parent.bottom
                                                    color: "transparent"
                                                    visible: mainWindow.studioController.selectedVisual === String(modelData.title)
                                                    
                                                    Canvas {
                                                        anchors.fill: parent
                                                        onPaint: {
                                                            var ctx = getContext("2d");
                                                            ctx.strokeStyle = "#8aaebf";
                                                            ctx.lineWidth = 1;
                                                            ctx.beginPath();
                                                            ctx.moveTo(width, 0);
                                                            ctx.lineTo(0, height);
                                                            ctx.moveTo(width, 5);
                                                            ctx.lineTo(5, height);
                                                            ctx.moveTo(width, 10);
                                                            ctx.lineTo(10, height);
                                                            ctx.stroke();
                                                        }
                                                    }

                                                    MouseArea {
                                                        anchors.fill: parent
                                                        cursorShape: Qt.SizeFDiagCursor
                                                        property real startX
                                                        property real startY
                                                        property real startWidth
                                                        property real startHeight
                                                        onPressed: function(mouse) {
                                                            startX = mouse.x
                                                            startY = mouse.y
                                                            startWidth = parent.parent.width
                                                            startHeight = parent.parent.height
                                                        }
                                                        onPositionChanged: function(mouse) {
                                                            if (pressed) {
                                                                let newWidth = Math.max(50, startWidth + (mouse.x - startX))
                                                                let newHeight = Math.max(50, startHeight + (mouse.y - startY))
                                                                parent.parent.width = newWidth
                                                                parent.parent.height = newHeight
                                                            }
                                                        }
                                                        onReleased: {
                                                            mainWindow.studioController.resize_visual(String(modelData.id), Math.round(parent.parent.width / 10) * 10, Math.round(parent.parent.height / 10) * 10);
                                                        }
                                                    }
                                                }
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
                        appController: mainWindow.studioController
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
                                text: mainWindow.studioController.sourceLoaded ? "Linked data · " + mainWindow.studioController.sourceName : "No linked data source"
                                color: mainWindow.studioController.sourceLoaded ? "#64798a" : "#78858d"
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
                                text: mainWindow.studioController.sourceLoaded
                                      ? mainWindow.studioController.rowCount + " rows · " + mainWindow.studioController.columnCount + " source fields"
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
                                text: mainWindow.fieldSearchQuery
                                placeholderText: "Search fields"
                                enabled: mainWindow.studioController.sourceLoaded
                                font.pixelSize: 9
                                color: "#40515e"
                                onTextChanged: {
                                    if (mainWindow.fieldSearchQuery !== text)
                                        mainWindow.fieldSearchQuery = text
                                    mainWindow.studioController.setFieldQuery(text)
                                }
                                Accessible.name: "Search source fields"
                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: "#cfd7dd" }
                            }
                            ListView {
                                id: dataFieldsList
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: mainWindow.studioController.filteredFields
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
                                    visible: mainWindow.studioController.filteredFields.length === 0
                                    text: mainWindow.studioController.sourceLoaded ? "No matching fields." : "Import a CSV, Excel, JSON, XML, or Parquet file to browse its source fields."
                                    color: "#76838d"
                                    font.pixelSize: 9
                                    wrapMode: Text.Wrap
                                    horizontalAlignment: Text.AlignHCenter
                                }
                                Button {
                                    visible: !mainWindow.studioController.sourceLoaded
                                    anchors.horizontalCenter: parent.horizontalCenter
                                    anchors.top: parent.verticalCenter
                                    anchors.topMargin: 24
                                    text: "Import data"
                                    Accessible.name: "Import data from Data fields pane"
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Choose a supported CSV, Excel, JSON, XML, or Parquet file to browse its source fields."
                                    background: Rectangle { radius: 3; color: parent.hovered ? "#e7f1f8" : "#f4f8fb"; border.color: "#cbdde9" }
                                    contentItem: Text { text: parent.text; color: "#315f7d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                    onClicked: mainWindow.runCommand("data.importFile")
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
                        appController: mainWindow.studioController
                        onImportRequested: mainWindow.runCommand("data.importFile")
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
                                    text: mainWindow.studioController.sourceLoaded ? mainWindow.studioController.sourceName : "No data source"
                                    readOnly: true
                                    font.pixelSize: 10
                                    color: "#5a6871"
                                    background: Rectangle { radius: 3; color: "#f7f8f9"; border.color: "#d6dce0" }
                                }
                                Text { text: "Tables"; color: "#687681"; font.pixelSize: 9 }
                                Text { text: String(mainWindow.studioController.modelTables.length); color: "#334653"; font.pixelSize: 11 }
                                Text { text: "Relationships"; color: "#687681"; font.pixelSize: 9 }
                                Text { text: String(mainWindow.studioController.modelRelationships.length); color: "#334653"; font.pixelSize: 11 }
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
                                    Text { text: String(mainWindow.studioController.modelTables.length); color: "#73808a"; font.pixelSize: 9 }
                                }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: "#dce1e4" }
                            ListView {
                                Layout.fillWidth: true
                                Layout.fillHeight: true
                                model: mainWindow.studioController.modelTables
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
                                        model: mainWindow.studioController.sourceLoaded ? mainWindow.studioController.headers : []
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
                visible: mainWindow.studioController.currentView === "Report" && mainWindow.inspectorVisible
                Layout.preferredWidth: visible ? ((mainWindow.filtersExpanded ? 145 : 32)
                                                  + (mainWindow.visualizationsVisible ? 172 : 24)
                                                  + (mainWindow.dataPaneExpanded ? 160 : 33)) : 0
                Layout.fillHeight: true
                color: "#ffffff"
                border.color: "#d4d9dd"
                RowLayout {
                    anchors.fill: parent
                    spacing: 0
                    Item {
                        Layout.preferredWidth: mainWindow.filtersExpanded ? 145 : 32
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: mainWindow.filtersExpanded ? "#ffffff" : "#f8f9fa"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: mainWindow.filtersExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 29
                                    Layout.leftMargin: 7
                                    Icon { name: "filter"; color: "#61798b"; implicitWidth: 14; implicitHeight: 14 }
                                    Text { Layout.fillWidth: true; text: "Filters"; color: "#354755"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    ToolButton {
                                        onClicked: mainWindow.filtersExpanded = false
                                        Accessible.name: "Collapse Filters pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Filters pane"
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapseLeft"; color: "#657784"; implicitWidth: 14; implicitHeight: 14 }
                                    }
                                }
                                ColumnLayout {
                                    visible: mainWindow.filtersExpanded
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
                                                model: mainWindow.studioController.regions
                                                currentIndex: Math.max(0, mainWindow.studioController.regions.indexOf(mainWindow.studioController.currentRegion))
                                                enabled: mainWindow.studioController.sourceLoaded && mainWindow.studioController.regions.length > 1
                                                onActivated: function(index) { mainWindow.studioController.setRegionFilter(String(mainWindow.studioController.regions[index])) }
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
                                        enabled: mainWindow.studioController.filterActive
                                        background: Rectangle { radius: 3; color: parent.enabled ? "#f3f5f6" : "#f7f8f9"; border.color: "#d7dde1" }
                                        contentItem: Text { text: parent.text; color: parent.enabled ? "#445762" : "#98a1a8"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        onClicked: mainWindow.runCommand("filter.clear")
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 450
                                        color: "#ffffff"
                                        border.color: "#d9dfe3"
                                        ColumnLayout {
                                            anchors.fill: parent
                                            anchors.margins: 8
                                            spacing: 6
                                            Text {
                                                text: filterScopeCombo.currentIndex === 0
                                                      ? "Report filters"
                                                      : (filterScopeCombo.currentIndex === 1
                                                         ? "Page filters"
                                                         : (mainWindow.studioController.selectedVisual.length > 0
                                                         ? String(mainWindow.studioController.selectedVisual) + " filters"
                                                         : "Visual filters"))
                                                color: "#495b68"
                                                font.pixelSize: 10
                                                font.weight: Font.DemiBold
                                            }
                                            ComboBox {
                                                id: filterScopeCombo
                                                Layout.fillWidth: true
                                                model: ["Report", "Page", "Selected visual"]
                                                currentIndex: 1
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: filterScopeCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                contentItem: Text {
                                                    leftPadding: 8
                                                    rightPadding: filterScopeCombo.indicator.width + 6
                                                    text: filterScopeCombo.displayText
                                                    color: "#455661"
                                                    font.pixelSize: 9
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideRight
                                                }
                                                delegate: ItemDelegate {
                                                    width: filterScopeCombo.width
                                                    text: String(modelData)
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text { text: String(modelData); color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                }
                                            }
                                            ComboBox {
                                                id: visualFilterTargetCombo
                                                visible: filterScopeCombo.currentIndex === 2
                                                Layout.fillWidth: true
                                                model: mainWindow.studioController.activePageVisuals
                                                currentIndex: model.indexOf(mainWindow.studioController.selectedVisual)
                                                enabled: count > 0
                                                onActivated: function(index) {
                                                    mainWindow.studioController.selectVisual(String(model[index]))
                                                }
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: visualFilterTargetCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                contentItem: Text {
                                                    leftPadding: 8
                                                    rightPadding: visualFilterTargetCombo.indicator.width + 6
                                                    text: visualFilterTargetCombo.displayText || "Choose a visual"
                                                    color: visualFilterTargetCombo.enabled ? "#455661" : "#86919a"
                                                    font.pixelSize: 9
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideRight
                                                }
                                                delegate: ItemDelegate {
                                                    width: visualFilterTargetCombo.width
                                                    text: String(modelData)
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text { text: String(modelData); color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                text: filterScopeCombo.currentIndex === 0
                                                      ? "Filter every report page with one or two conditions per field. Conditions follow active relationships."
                                                      : (filterScopeCombo.currentIndex === 1
                                                         ? "Filter this page with one or two conditions per field. Conditions follow active relationships."
                                                         : "Conditions here affect only the chosen visual and follow active relationships.")
                                                color: "#79858d"
                                                font.pixelSize: 8
                                                wrapMode: Text.Wrap
                                            }
                                            ScrollView {
                                                id: pageFilterList
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 56
                                                clip: true
                                                    ColumnLayout {
                                                        width: pageFilterList.availableWidth
                                                        Repeater {
                                                        model: filterScopeCombo.currentIndex === 0
                                                               ? mainWindow.studioController.activeReportFilters
                                                               : (filterScopeCombo.currentIndex === 1
                                                                  ? mainWindow.studioController.activePageFilters
                                                                  : mainWindow.studioController.activeVisualFilters)
                                                        delegate: RowLayout {
                                                            required property var modelData
                                                            Layout.fillWidth: true
                                                            spacing: 3
                                                            Text {
                                                                Layout.fillWidth: true
                                                                text: String(modelData.tableName) + " · " + String(modelData.column) + " " + String(modelData.displayValue)
                                                                color: "#536570"
                                                                font.pixelSize: 8
                                                                elide: Text.ElideRight
                                                                ToolTip.visible: filterRowMouse.containsMouse
                                                                ToolTip.text: String(modelData.tableName) + " · " + String(modelData.column) + " " + String(modelData.displayValue)
                                                                MouseArea { id: filterRowMouse; anchors.fill: parent; hoverEnabled: true }
                                                            }
                                                            ToolButton {
                                                                Accessible.name: filterScopeCombo.currentIndex === 0
                                                                                 ? "Remove report filter"
                                                                                 : (filterScopeCombo.currentIndex === 1
                                                                                    ? "Remove page filter"
                                                                                    : "Remove visual filter")
                                                                onClicked: {
                                                                    if (filterScopeCombo.currentIndex === 0)
                                                                        mainWindow.studioController.removeReportFilter(Number(modelData.index))
                                                                    else if (filterScopeCombo.currentIndex === 1)
                                                                        mainWindow.studioController.removePageFilter(Number(modelData.index))
                                                                    else
                                                                        mainWindow.studioController.removeVisualFilter(Number(modelData.index))
                                                                }
                                                                contentItem: Text { text: "×"; color: "#657784"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                                background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                            Text {
                                                visible: filterScopeCombo.currentIndex === 0
                                                         ? mainWindow.studioController.activeReportFilters.length === 0
                                                         : (filterScopeCombo.currentIndex === 1
                                                            ? mainWindow.studioController.activePageFilters.length === 0
                                                            : mainWindow.studioController.activeVisualFilters.length === 0)
                                                text: filterScopeCombo.currentIndex === 0
                                                      ? "No report filters set."
                                                      : (filterScopeCombo.currentIndex === 1
                                                         ? "No page filters set."
                                                         : "No filters on this visual.")
                                                color: "#89949c"
                                                font.pixelSize: 8
                                            }
                                            ComboBox {
                                                id: pageFilterFieldCombo
                                                Layout.fillWidth: true
                                                model: mainWindow.studioController.pageFilterFields
                                                textRole: "label"
                                                currentIndex: count > 0 ? 0 : -1
                                                enabled: count > 0
                                                onActivated: function(index) {
                                                    pageFilterValueCombo.currentIndex = pageFilterValueCombo.count > 0 ? 0 : -1
                                                    if (pageFilterValueCombo.count === 0) pageFilterValueCombo.editText = ""
                                                    pageFilterOperatorCombo.currentIndex = 0
                                                    secondFilterOperatorCombo.currentIndex = 0
                                                    filterLogicCombo.currentIndex = 0
                                                    secondConditionCheck.checked = false
                                                    secondFilterValue.text = ""
                                                    filterValueSearch.text = ""
                                                    mainWindow.selectedReportFilterValues = []
                                                    relativeDateDirectionCombo.currentIndex = 0
                                                    relativeDateCount.value = 1
                                                    relativeDateUnitCombo.currentIndex = 0
                                                    relativeDateIncludeToday.checked = true
                                                }
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: pageFilterFieldCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                contentItem: Text {
                                                    leftPadding: 8
                                                    rightPadding: pageFilterFieldCombo.indicator.width + 6
                                                    text: pageFilterFieldCombo.displayText || "Choose a table field"
                                                    color: pageFilterFieldCombo.enabled ? "#455661" : "#86919a"
                                                    font.pixelSize: 9
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideRight
                                                }
                                                delegate: ItemDelegate {
                                                    required property string label
                                                    width: pageFilterFieldCombo.width
                                                    text: label
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                }
                                            }
                                            ComboBox {
                                                id: pageFilterOperatorCombo
                                                Layout.fillWidth: true
                                                model: {
                                                    const fields = mainWindow.studioController.pageFilterFields
                                                    if (pageFilterFieldCombo.currentIndex < 0 || pageFilterFieldCombo.currentIndex >= fields.length) return []
                                                    const field = fields[pageFilterFieldCombo.currentIndex]
                                                    if (filterScopeCombo.currentIndex !== 2)
                                                        return mainWindow.studioController.pageFilterOperators(String(field.columnType))
                                                    return mainWindow.studioController.visualFilterOperators(
                                                        String(field.tableId), String(field.column), String(field.columnType),
                                                        String(mainWindow.studioController.selectedVisual)
                                                    )
                                                }
                                                textRole: "label"
                                                valueRole: "value"
                                                currentIndex: count > 0 ? 0 : -1
                                                enabled: pageFilterFieldCombo.currentIndex >= 0
                                                onActivated: function(index) {
                                                    mainWindow.selectedReportFilterValues = []
                                                    const op = String(currentValue)
                                                    if (op === "is_any_of" || op === "is_none_of") {
                                                        pageFilterValueCombo.currentIndex = -1
                                                        pageFilterValueCombo.editText = ""
                                                        secondConditionCheck.checked = false
                                                        filterValueSearch.text = ""
                                                    } else if (op === "is_blank" || op === "is_not_blank") {
                                                        pageFilterValueCombo.currentIndex = -1
                                                        pageFilterValueCombo.editText = ""
                                                    } else if (op === "relative_date" || op === "relative_time") {
                                                        pageFilterValueCombo.currentIndex = -1
                                                        pageFilterValueCombo.editText = ""
                                                        secondConditionCheck.checked = false
                                                        relativeDateDirectionCombo.currentIndex = 0
                                                        relativeDateCount.value = 1
                                                        relativeDateUnitCombo.currentIndex = 0
                                                        relativeDateIncludeToday.checked = true
                                                    } else if (op === "top_n") {
                                                        pageFilterValueCombo.currentIndex = -1
                                                        pageFilterValueCombo.editText = ""
                                                        secondConditionCheck.checked = false
                                                        topNDirectionCombo.currentIndex = 0
                                                        topNCount.value = 5
                                                        topNOrderByCombo.currentIndex = topNOrderByCombo.count > 0 ? 0 : -1
                                                    }
                                                }
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: pageFilterOperatorCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                contentItem: Text {
                                                    leftPadding: 8
                                                    rightPadding: pageFilterOperatorCombo.indicator.width + 6
                                                    text: pageFilterOperatorCombo.displayText || "Choose a filter condition"
                                                    color: pageFilterOperatorCombo.enabled ? "#455661" : "#86919a"
                                                    font.pixelSize: 9
                                                    verticalAlignment: Text.AlignVCenter
                                                    elide: Text.ElideRight
                                                }
                                                delegate: ItemDelegate {
                                                    required property string label
                                                    width: pageFilterOperatorCombo.width
                                                    text: label
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                }
                                            }
                                            RowLayout {
                                                visible: String(pageFilterOperatorCombo.currentValue) === "relative_date"
                                                         || String(pageFilterOperatorCombo.currentValue) === "relative_time"
                                                Layout.fillWidth: true
                                                spacing: 4
                                                ComboBox {
                                                    id: relativeDateDirectionCombo
                                                    Layout.preferredWidth: 66
                                                    model: ["Last", "This", "Next"]
                                                    currentIndex: 0
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: relativeDateDirectionCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 6
                                                        rightPadding: relativeDateDirectionCombo.indicator.width + 4
                                                        text: relativeDateDirectionCombo.displayText
                                                        color: "#455661"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                    delegate: ItemDelegate {
                                                        width: relativeDateDirectionCombo.width
                                                        text: String(modelData)
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: String(modelData); color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                    }
                                                }
                                                SpinBox {
                                                    id: relativeDateCount
                                                    Layout.preferredWidth: 64
                                                    from: 1
                                                    to: 1000
                                                    value: 1
                                                    editable: true
                                                    enabled: relativeDateDirectionCombo.currentText !== "This"
                                                }
                                                ComboBox {
                                                    id: relativeDateUnitCombo
                                                    Layout.fillWidth: true
                                                    model: String(pageFilterOperatorCombo.currentValue) === "relative_time"
                                                           ? [
                                                               { label: "Minutes", value: "minutes" },
                                                               { label: "Hours", value: "hours" }
                                                           ]
                                                           : [
                                                               { label: "Days", value: "days" },
                                                               { label: "Weeks", value: "weeks" },
                                                               { label: "Weeks (Calendar)", value: "calendar_weeks" },
                                                               { label: "Months", value: "months" },
                                                               { label: "Months (Calendar)", value: "calendar_months" },
                                                               { label: "Years", value: "years" },
                                                               { label: "Years (Calendar)", value: "calendar_years" }
                                                           ]
                                                    textRole: "label"
                                                    valueRole: "value"
                                                    currentIndex: 0
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: relativeDateUnitCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 6
                                                        rightPadding: relativeDateUnitCombo.indicator.width + 4
                                                        text: relativeDateUnitCombo.displayText
                                                        color: "#455661"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                        elide: Text.ElideRight
                                                    }
                                                    delegate: ItemDelegate {
                                                        required property string label
                                                        width: relativeDateUnitCombo.width
                                                        text: label
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                    }
                                                }
                                            }
                                            Text {
                                                visible: String(pageFilterOperatorCombo.currentValue) === "relative_time"
                                                Layout.fillWidth: true
                                                text: "Relative-time windows use UTC; values without a timezone are treated as UTC."
                                                color: "#79858d"
                                                font.pixelSize: 8
                                                wrapMode: Text.Wrap
                                            }
                                            RowLayout {
                                                visible: String(pageFilterOperatorCombo.currentValue) === "top_n"
                                                Layout.fillWidth: true
                                                spacing: 4
                                                ComboBox {
                                                    id: topNDirectionCombo
                                                    Layout.preferredWidth: 68
                                                    model: [
                                                        { label: "Top", value: "top" },
                                                        { label: "Bottom", value: "bottom" }
                                                    ]
                                                    textRole: "label"
                                                    valueRole: "value"
                                                    currentIndex: 0
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: topNDirectionCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 6
                                                        rightPadding: topNDirectionCombo.indicator.width + 4
                                                        text: topNDirectionCombo.displayText
                                                        color: "#455661"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                    delegate: ItemDelegate {
                                                        required property string label
                                                        width: topNDirectionCombo.width
                                                        text: label
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                    }
                                                }
                                                SpinBox {
                                                    id: topNCount
                                                    Layout.preferredWidth: 58
                                                    from: 1
                                                    to: 1000
                                                    value: 5
                                                    editable: true
                                                }
                                                ComboBox {
                                                    id: topNOrderByCombo
                                                    Layout.fillWidth: true
                                                    model: mainWindow.studioController.topNOrderByFields
                                                    textRole: "label"
                                                    valueRole: "column"
                                                    currentIndex: count > 0 ? 0 : -1
                                                    enabled: count > 0
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: topNOrderByCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 6
                                                        rightPadding: topNOrderByCombo.indicator.width + 4
                                                        text: topNOrderByCombo.displayText || "By"
                                                        color: topNOrderByCombo.enabled ? "#455661" : "#86919a"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                        elide: Text.ElideRight
                                                    }
                                                    delegate: ItemDelegate {
                                                        required property string label
                                                        width: topNOrderByCombo.width
                                                        text: label
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                    }
                                                }
                                            }
                                            Text {
                                                visible: String(pageFilterOperatorCombo.currentValue) === "top_n"
                                                Layout.fillWidth: true
                                                text: "Top N ranks Region categories by the sum of the selected numeric field."
                                                color: "#79858d"
                                                font.pixelSize: 8
                                                wrapMode: Text.Wrap
                                            }
                                            CheckBox {
                                                id: relativeDateIncludeToday
                                                visible: String(pageFilterOperatorCombo.currentValue) === "relative_date"
                                                         && relativeDateDirectionCombo.currentText !== "This"
                                                         && String(relativeDateUnitCombo.currentValue).indexOf("calendar_") !== 0
                                                Layout.fillWidth: true
                                                checked: true
                                                implicitHeight: 18
                                                text: "Include today"
                                                Accessible.name: text
                                                contentItem: Text {
                                                    text: relativeDateIncludeToday.text
                                                    leftPadding: relativeDateIncludeToday.indicator.width + 5
                                                    color: "#536570"
                                                    font.pixelSize: 8
                                                    verticalAlignment: Text.AlignVCenter
                                                }
                                            }
                                            ComboBox {
                                                id: pageFilterValueCombo
                                                visible: String(pageFilterOperatorCombo.currentValue) !== "is_any_of"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "is_none_of"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_date"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_time"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "top_n"
                                                Layout.fillWidth: true
                                                editable: true
                                                model: {
                                                    const fields = mainWindow.studioController.pageFilterFields
                                                    if (pageFilterFieldCombo.currentIndex < 0 || pageFilterFieldCombo.currentIndex >= fields.length) return []
                                                    const field = fields[pageFilterFieldCombo.currentIndex]
                                                    return mainWindow.studioController.pageFilterValues(String(field.tableId), String(field.column))
                                                }
                                                textRole: "label"
                                                valueRole: "value"
                                                currentIndex: count > 0 ? 0 : -1
                                                enabled: pageFilterFieldCombo.currentIndex >= 0
                                                         && String(pageFilterOperatorCombo.currentValue) !== "is_blank"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "is_not_blank"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_date"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_time"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "top_n"
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: pageFilterValueCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                contentItem: TextInput {
                                                    leftPadding: 8
                                                    rightPadding: pageFilterValueCombo.indicator.width + 6
                                                    text: pageFilterValueCombo.editable ? pageFilterValueCombo.editText : pageFilterValueCombo.displayText
                                                    color: pageFilterValueCombo.enabled ? "#455661" : "#86919a"
                                                    font.pixelSize: 9
                                                    verticalAlignment: TextInput.AlignVCenter
                                                    readOnly: !pageFilterValueCombo.editable
                                                    selectByMouse: true
                                                    onTextEdited: pageFilterValueCombo.editText = text
                                                }
                                                delegate: ItemDelegate {
                                                    required property string label
                                                    width: pageFilterValueCombo.width
                                                    text: label
                                                    background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                    contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                }
                                            }
                                            TextField {
                                                id: filterValueSearch
                                                visible: String(pageFilterOperatorCombo.currentValue) === "is_any_of"
                                                         || String(pageFilterOperatorCombo.currentValue) === "is_none_of"
                                                Layout.fillWidth: true
                                                placeholderText: "Search values"
                                                selectByMouse: true
                                                font.pixelSize: 9
                                                color: "#455661"
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: filterValueSearch.activeFocus ? "#718da1" : "#ccd4da" }
                                            }
                                            ListView {
                                                id: multiValueChoices
                                                visible: filterValueSearch.visible
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: 68
                                                clip: true
                                                model: {
                                                    const fields = mainWindow.studioController.pageFilterFields
                                                    if (pageFilterFieldCombo.currentIndex < 0 || pageFilterFieldCombo.currentIndex >= fields.length) return []
                                                    const field = fields[pageFilterFieldCombo.currentIndex]
                                                    return mainWindow.studioController.searchPageFilterValues(
                                                        String(field.tableId), String(field.column), String(filterValueSearch.text)
                                                    )
                                                }
                                                delegate: CheckBox {
                                                    required property string label
                                                    required property string value
                                                    width: multiValueChoices.width
                                                    height: 20
                                                    text: label
                                                    checked: mainWindow.selectedReportFilterValues.indexOf(value) >= 0
                                                    Accessible.name: label
                                                    contentItem: Text {
                                                        text: parent.text
                                                        leftPadding: parent.indicator.width + 4
                                                        color: "#536570"
                                                        font.pixelSize: 8
                                                        verticalAlignment: Text.AlignVCenter
                                                        elide: Text.ElideRight
                                                    }
                                                    onToggled: {
                                                        const updated = mainWindow.selectedReportFilterValues.slice()
                                                        const selectedIndex = updated.indexOf(value)
                                                        if (checked && selectedIndex < 0)
                                                            updated.push(value)
                                                        else if (!checked && selectedIndex >= 0)
                                                            updated.splice(selectedIndex, 1)
                                                        mainWindow.selectedReportFilterValues = updated
                                                    }
                                                }
                                            }
                                            Text {
                                                visible: multiValueChoices.visible
                                                Layout.fillWidth: true
                                                text: mainWindow.selectedReportFilterValues.length + " selected"
                                                color: "#79858d"
                                                font.pixelSize: 8
                                            }
                                            CheckBox {
                                                id: secondConditionCheck
                                                visible: String(pageFilterOperatorCombo.currentValue) !== "is_any_of"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "is_none_of"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_date"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "relative_time"
                                                         && String(pageFilterOperatorCombo.currentValue) !== "top_n"
                                                Layout.fillWidth: true
                                                implicitHeight: 18
                                                text: "Add a second condition"
                                                Accessible.name: text
                                                contentItem: Text {
                                                    text: secondConditionCheck.text
                                                    leftPadding: secondConditionCheck.indicator.width + 5
                                                    color: "#536570"
                                                    font.pixelSize: 8
                                                    verticalAlignment: Text.AlignVCenter
                                                }
                                            }
                                            RowLayout {
                                                visible: secondConditionCheck.checked
                                                Layout.fillWidth: true
                                                spacing: 4
                                                ComboBox {
                                                    id: filterLogicCombo
                                                    Layout.preferredWidth: 50
                                                    model: ["AND", "OR"]
                                                    currentIndex: 0
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: filterLogicCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 6
                                                        rightPadding: filterLogicCombo.indicator.width + 4
                                                        text: filterLogicCombo.displayText
                                                        color: "#455661"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                    }
                                                    delegate: ItemDelegate {
                                                        width: filterLogicCombo.width
                                                        text: String(modelData)
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: String(modelData); color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter }
                                                    }
                                                }
                                                ComboBox {
                                                    id: secondFilterOperatorCombo
                                                    Layout.fillWidth: true
                                                    model: {
                                                        const fields = mainWindow.studioController.pageFilterFields
                                                        if (pageFilterFieldCombo.currentIndex < 0 || pageFilterFieldCombo.currentIndex >= fields.length) return []
                                                        return mainWindow.studioController.pageFilterOperators(
                                                            String(fields[pageFilterFieldCombo.currentIndex].columnType)
                                                        ).filter(function(item) {
                                                            return item.value !== "is_any_of"
                                                                   && item.value !== "is_none_of"
                                                                   && item.value !== "relative_date"
                                                                   && item.value !== "relative_time"
                                                        })
                                                    }
                                                    textRole: "label"
                                                    valueRole: "value"
                                                    currentIndex: 0
                                                    onActivated: function(index) {
                                                        if (String(currentValue) === "is_blank" || String(currentValue) === "is_not_blank")
                                                            secondFilterValue.text = ""
                                                    }
                                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: secondFilterOperatorCombo.activeFocus ? "#718da1" : "#ccd4da" }
                                                    contentItem: Text {
                                                        leftPadding: 8
                                                        rightPadding: secondFilterOperatorCombo.indicator.width + 6
                                                        text: secondFilterOperatorCombo.displayText
                                                        color: "#455661"
                                                        font.pixelSize: 9
                                                        verticalAlignment: Text.AlignVCenter
                                                        elide: Text.ElideRight
                                                    }
                                                    delegate: ItemDelegate {
                                                        required property string label
                                                        width: secondFilterOperatorCombo.width
                                                        text: label
                                                        background: Rectangle { color: highlighted ? "#e9eff3" : "#ffffff" }
                                                        contentItem: Text { text: label; color: "#455661"; font.pixelSize: 9; verticalAlignment: Text.AlignVCenter; elide: Text.ElideRight }
                                                    }
                                                }
                                            }
                                            TextField {
                                                id: secondFilterValue
                                                visible: secondConditionCheck.checked
                                                         && String(secondFilterOperatorCombo.currentValue) !== "is_blank"
                                                         && String(secondFilterOperatorCombo.currentValue) !== "is_not_blank"
                                                Layout.fillWidth: true
                                                placeholderText: "Second condition value"
                                                selectByMouse: true
                                                font.pixelSize: 9
                                                color: "#455661"
                                                background: Rectangle { radius: 3; color: "#ffffff"; border.color: secondFilterValue.activeFocus ? "#718da1" : "#ccd4da" }
                                            }
                                            Button {
                                                Layout.fillWidth: true
                                                text: filterScopeCombo.currentIndex === 0
                                                      ? "Add report filter"
                                                      : (filterScopeCombo.currentIndex === 1
                                                         ? "Add page filter"
                                                         : "Add visual filter")
                                                enabled: {
                                                    if (pageFilterFieldCombo.currentIndex < 0
                                                            || (filterScopeCombo.currentIndex === 2 && mainWindow.studioController.selectedVisual.length === 0))
                                                        return false
                                                    const valueless = ["is_blank", "is_not_blank"]
                                                    const multiValueOperators = ["is_any_of", "is_none_of"]
                                                    const required = ["contains", "does_not_contain", "begins_with", "does_not_begin_with", "ends_with", "does_not_end_with", "greater_than", "greater_than_or_equal", "less_than", "less_than_or_equal"]
                                                    const firstOperator = String(pageFilterOperatorCombo.currentValue)
                                                    if (firstOperator === "top_n")
                                                        return filterScopeCombo.currentIndex === 2
                                                               && topNOrderByCombo.currentIndex >= 0
                                                               && topNCount.value >= 1
                                                    if (firstOperator === "relative_date" || firstOperator === "relative_time")
                                                        return relativeDateDirectionCombo.currentText === "This"
                                                               || relativeDateCount.value >= 1
                                                    if (multiValueOperators.indexOf(firstOperator) >= 0)
                                                        return !secondConditionCheck.checked && mainWindow.selectedReportFilterValues.length > 0
                                                    const firstValue = pageFilterValueCombo.currentIndex >= 0 && pageFilterValueCombo.editText === pageFilterValueCombo.currentText
                                                                      ? String(pageFilterValueCombo.currentValue)
                                                                      : String(pageFilterValueCombo.editText)
                                                    if (required.indexOf(firstOperator) >= 0 && firstValue.trim().length === 0)
                                                        return false
                                                    if (secondConditionCheck.checked) {
                                                        const secondOperator = String(secondFilterOperatorCombo.currentValue)
                                                        if (secondOperator.length === 0)
                                                            return false
                                                        if (required.indexOf(secondOperator) >= 0 && secondFilterValue.text.trim().length === 0)
                                                            return false
                                                        if (valueless.indexOf(secondOperator) >= 0 && secondFilterValue.text.length > 0)
                                                            return false
                                                    }
                                                    return true
                                                }
                                                background: Rectangle { radius: 3; color: parent.enabled ? "#e8f2f0" : "#f7f8f9"; border.color: parent.enabled ? "#c0d9d4" : "#d7dde1" }
                                                contentItem: Text { text: parent.text; color: parent.enabled ? "#17665d" : "#98a1a8"; font.pixelSize: 9; font.weight: Font.DemiBold; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                onClicked: {
                                                    const fields = mainWindow.studioController.pageFilterFields
                                                    const field = fields[pageFilterFieldCombo.currentIndex]
                                                    const operator = String(pageFilterOperatorCombo.currentValue)
                                                    if (operator === "relative_date") {
                                                        const direction = String(relativeDateDirectionCombo.currentText).toLowerCase()
                                                        const count = direction === "this" ? 1 : Number(relativeDateCount.value)
                                                        const unit = String(relativeDateUnitCombo.currentValue)
                                                        const includeToday = relativeDateIncludeToday.checked
                                                        if (filterScopeCombo.currentIndex === 0) {
                                                            mainWindow.studioController.addReportRelativeDateFilter(
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit, includeToday
                                                            )
                                                        } else if (filterScopeCombo.currentIndex === 1) {
                                                            mainWindow.studioController.addPageRelativeDateFilter(
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit, includeToday
                                                            )
                                                        } else {
                                                            mainWindow.studioController.addVisualRelativeDateFilter(
                                                                String(mainWindow.studioController.selectedVisual),
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit, includeToday
                                                            )
                                                        }
                                                        return
                                                    }
                                                    if (operator === "relative_time") {
                                                        const direction = String(relativeDateDirectionCombo.currentText).toLowerCase()
                                                        const count = direction === "this" ? 1 : Number(relativeDateCount.value)
                                                        const unit = String(relativeDateUnitCombo.currentValue)
                                                        if (filterScopeCombo.currentIndex === 0) {
                                                            mainWindow.studioController.addReportRelativeTimeFilter(
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit
                                                            )
                                                        } else if (filterScopeCombo.currentIndex === 1) {
                                                            mainWindow.studioController.addPageRelativeTimeFilter(
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit
                                                            )
                                                        } else {
                                                            mainWindow.studioController.addVisualRelativeTimeFilter(
                                                                String(mainWindow.studioController.selectedVisual),
                                                                String(field.tableId), String(field.column), direction,
                                                                count, unit
                                                            )
                                                        }
                                                        return
                                                    }
                                                    if (operator === "top_n") {
                                                        mainWindow.studioController.addVisualTopNFilter(
                                                            String(mainWindow.studioController.selectedVisual),
                                                            String(field.tableId), String(field.column),
                                                            String(topNDirectionCombo.currentValue), Number(topNCount.value),
                                                            String(topNOrderByCombo.currentValue)
                                                        )
                                                        return
                                                    }
                                                    if (operator === "is_any_of" || operator === "is_none_of") {
                                                        const valuesJson = JSON.stringify(mainWindow.selectedReportFilterValues)
                                                        let added = false
                                                        if (filterScopeCombo.currentIndex === 0) {
                                                            added = mainWindow.studioController.addReportMultiValueFilter(
                                                                String(field.tableId), String(field.column), operator, valuesJson
                                                            )
                                                        } else if (filterScopeCombo.currentIndex === 1) {
                                                            added = mainWindow.studioController.addPageMultiValueFilter(
                                                                String(field.tableId), String(field.column), operator, valuesJson
                                                            )
                                                        } else {
                                                            added = mainWindow.studioController.addVisualMultiValueFilter(
                                                                String(mainWindow.studioController.selectedVisual),
                                                                String(field.tableId), String(field.column), operator, valuesJson
                                                            )
                                                        }
                                                        if (added) mainWindow.selectedReportFilterValues = []
                                                        return
                                                    }
                                                    const value = operator === "is_blank" || operator === "is_not_blank"
                                                                  ? ""
                                                                  : (pageFilterValueCombo.currentIndex >= 0 && pageFilterValueCombo.editText === pageFilterValueCombo.currentText
                                                                     ? String(pageFilterValueCombo.currentValue)
                                                                     : String(pageFilterValueCombo.editText))
                                                    const secondOperator = secondConditionCheck.checked
                                                                          ? String(secondFilterOperatorCombo.currentValue)
                                                                          : ""
                                                    const secondValue = !secondConditionCheck.checked
                                                                        || secondOperator === "is_blank" || secondOperator === "is_not_blank"
                                                                        ? ""
                                                                        : String(secondFilterValue.text)
                                                    const logic = String(filterLogicCombo.currentText).toLowerCase()
                                                    if (filterScopeCombo.currentIndex === 0) {
                                                        mainWindow.studioController.addReportFilterRule(
                                                            String(field.tableId), String(field.column), operator, value,
                                                            secondOperator, secondValue, logic
                                                        )
                                                    } else if (filterScopeCombo.currentIndex === 1) {
                                                        mainWindow.studioController.addPageFilterRule(
                                                            String(field.tableId), String(field.column), operator, value,
                                                            secondOperator, secondValue, logic
                                                        )
                                                    } else {
                                                        mainWindow.studioController.addVisualFilterRule(
                                                            String(mainWindow.studioController.selectedVisual),
                                                            String(field.tableId), String(field.column), operator, value,
                                                            secondOperator, secondValue, logic
                                                        )
                                                    }
                                                }
                                            }
                                            Text {
                                                Layout.fillWidth: true
                                                visible: mainWindow.studioController.filterContextError.length > 0
                                                text: mainWindow.studioController.filterContextError
                                                color: "#9b4a35"
                                                font.pixelSize: 8
                                                wrapMode: Text.Wrap
                                            }
                                        }
                                    }
                                    Item { Layout.fillHeight: true }
                                }
                                ToolButton {
                                    visible: !mainWindow.filtersExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    padding: 0
                                    hoverEnabled: true
                                    focusPolicy: Qt.StrongFocus
                                    Accessible.name: "Expand Filters pane"
                                    Accessible.description: mainWindow.studioController.filterActive
                                                            ? "Open report, page, and visual filters. A filter is currently active."
                                                            : "Open report, page, and visual filter controls."
                                    ToolTip.visible: hovered
                                    ToolTip.text: "Report, page, and visual filters"
                                    background: Rectangle {
                                        color: parent.activeFocus ? "#e5f1f8" : (parent.hovered ? "#eef3f6" : "#f8f9fa")
                                        border.color: parent.activeFocus ? "#0078D4" : "#e0e3e6"
                                    }
                                    contentItem: Item {
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 10; name: "collapseLeft"; color: "#657784"; implicitWidth: 16; implicitHeight: 16 }
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 39; name: "filterRail"; color: "#8A6D1D"; implicitWidth: 16; implicitHeight: 16 }
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 67; text: "Filters"; rotation: -90; color: "#526573"; font.pixelSize: 9 }
                                        Rectangle {
                                            visible: mainWindow.studioController.filterActive
                                            anchors.horizontalCenter: parent.horizontalCenter
                                            anchors.bottom: parent.bottom
                                            anchors.bottomMargin: 7
                                            width: 7
                                            height: 7
                                            radius: 4
                                            color: "#D9A300"
                                        }
                                    }
                                    onClicked: mainWindow.filtersExpanded = true
                                }
                            }
                        }
                    }

                    Item {
                        Layout.preferredWidth: mainWindow.visualizationsVisible ? 172 : 24
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: "#f4f4f4"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: mainWindow.visualizationsVisible
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 16
                                    Layout.leftMargin: 8
                                    Layout.rightMargin: 2
                                    transform: Translate { y: 2 }
                                    Text { Layout.fillWidth: true; text: "Visualizations"; color: "#202020"; font.pixelSize: 14; font.weight: Font.DemiBold }
                                    ToolButton {
                                        padding: 0
                                        implicitWidth: 24
                                        implicitHeight: 16
                                        Accessible.name: "Collapse Visualizations pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Visualizations pane"
                                        onClicked: mainWindow.visualizationsVisible = false
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapsePane"; color: "#657784"; implicitWidth: 16; implicitHeight: 16 }
                                    }
                                }
                                Rectangle { visible: mainWindow.visualizationsVisible; Layout.fillWidth: true; Layout.topMargin: -4; height: 1; color: "#e1e5e8" }
                                ColumnLayout {
                                    visible: mainWindow.visualizationsVisible
                                    Layout.fillWidth: true
                                    Layout.fillHeight: false
                                    Layout.alignment: Qt.AlignTop
                                    Layout.leftMargin: 4
                                    Layout.rightMargin: 6.5
                                    Layout.topMargin: 4
                                    Layout.bottomMargin: 4
                                    spacing: 4
                                    Text {
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 3
                                        text: "Build visual"
                                        color: "#354755"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    Item {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 43
                                        Layout.topMargin: -6
                                        Repeater {
                                            model: [
                                                { label: "Build", icon: "buildVisual", active: true, tabId: "build" },
                                                { label: "Format", icon: "formatTab", active: true, tabId: "format" },
                                                { label: "Analytics", icon: "analyticsTab", active: false, tabId: "analytics" }
                                            ]
                                            delegate: Button {
                                                id: buildVisualTabBtn
                                                required property int index
                                                required property var modelData
                                                width: 40
                                                height: parent.height
                                                x: parent.width * (index === 0 ? 0.116 : (index === 1 ? 0.507 : 0.89)) - width / 2
                                                enabled: Boolean(modelData.active)
                                                hoverEnabled: true
                                                padding: 1
                                                Accessible.name: String(modelData.label) + " visualization pane"
                                                Accessible.description: enabled ? "Build visual is available." : String(modelData.label) + " settings are not available in this release."
                                                ToolTip.visible: hovered && !enabled
                                                ToolTip.text: String(modelData.label) + " settings are not available in this release."
                                                onClicked: {
                                                    if (enabled) {
                                                        mainWindow.activeVisualTab = String(modelData.tabId)
                                                    }
                                                }
                                                background: Item {
                                                    Rectangle {
                                                        anchors.centerIn: parent
                                                        width: 30
                                                        height: 30
                                                        radius: 3
                                                        color: mainWindow.activeVisualTab === modelData.tabId ? "#d7d7d7" : (buildVisualTabBtn.hovered && modelData.active ? "#eaeaea" : "transparent")
                                                    }
                                                    Rectangle {
                                                        visible: mainWindow.activeVisualTab === modelData.tabId
                                                        width: 8
                                                        height: 8
                                                        anchors.horizontalCenter: parent.horizontalCenter
                                                        anchors.bottom: parent.bottom
                                                        anchors.bottomMargin: -4
                                                        rotation: 45
                                                        color: "#d7d7d7"
                                                    }
                                                }
                                                contentItem: Item {
                                                    Icon {
                                                        anchors.centerIn: parent
                                                        name: String(modelData.icon)
                                                        color: modelData.active ? "#0078d4" : "#6f777d"
                                                        useGalleryAtlas: true
                                                        implicitWidth: 24
                                                        implicitHeight: 24
                                                    }
                                                    Icon {
                                                        anchors.right: parent.right
                                                        anchors.bottom: parent.bottom
                                                        anchors.rightMargin: 8
                                                        anchors.bottomMargin: 5
                                                        visible: Boolean(modelData.overlay)
                                                        name: String(modelData.overlay || "")
                                                        color: "#6f777d"
                                                        implicitWidth: 14
                                                        implicitHeight: 14
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Rectangle { Layout.fillWidth: true; Layout.topMargin: 1; height: 1; color: "#e1e5e8" }
                                    Item {
                                        id: visualGallery
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 187

                                        Repeater {
                                            model: [
                                                { type: "bar", name: "Clustered bar chart", icon: "bar", accent: "#107C71", active: true },
                                                { type: "column", name: "Clustered column chart", icon: "column", accent: "#0078D4", active: true },
                                                { type: "stackedBar", name: "Stacked bar chart", icon: "stackedBar" },
                                                { type: "stackedColumn", name: "Stacked column chart", icon: "stackedColumn" },
                                                { type: "bar100", name: "100% stacked bar chart", icon: "bar100" },
                                                { type: "column100", name: "100% stacked column chart", icon: "column100" },
                                                { type: "line", name: "Line chart", icon: "line", accent: "#C65911", active: true },
                                                { type: "area", name: "Area chart", icon: "area", accent: "#0078D4" },
                                                { type: "stackedArea", name: "Stacked area chart", icon: "stackedArea" },
                                                { type: "area100", name: "100% stacked area chart", icon: "area100" },
                                                { type: "lineStackedColumn", name: "Line and stacked column chart", icon: "lineStackedColumn" },
                                                { type: "lineClusteredColumn", name: "Line and clustered column chart", icon: "lineClusteredColumn" },
                                                { type: "ribbon", name: "Ribbon chart", icon: "ribbonChart" },
                                                { type: "waterfall", name: "Waterfall chart", icon: "waterfall", accent: "#0078D4" },
                                                { type: "funnel", name: "Funnel chart", icon: "funnel", accent: "#0078D4" },
                                                { type: "scatter", name: "Scatter chart", icon: "scatter", accent: "#0078D4" },
                                                { type: "pie", name: "Pie chart", icon: "pie", accent: "#0078D4" },
                                                { type: "donut", name: "Donut chart", icon: "donut", accent: "#0078D4" },
                                                { type: "treemap", name: "Treemap", icon: "treemap", accent: "#0078D4" },
                                                { type: "map", name: "Map", icon: "worldMap", accent: "#107C71" },
                                                { type: "filledMap", name: "Filled map", icon: "filledMap" },
                                                { type: "shapeMap", name: "Shape map", icon: "shapeMap" },
                                                { type: "azureMaps", name: "Azure Maps", icon: "azureMaps" },
                                                { type: "gauge", name: "Gauge", icon: "gauge", accent: "#0078D4" },
                                                { type: "card", name: "Card (new)", icon: "newCard" },
                                                { type: "kpi", name: "KPI", icon: "kpi", accent: "#0078D4" },
                                                { type: "slicer", name: "Slicer", icon: "slicer", accent: "#0078D4", active: true },
                                                { type: "table", name: "Table", icon: "table", accent: "#0078D4" },
                                                { type: "matrix", name: "Matrix", icon: "matrix", accent: "#0078D4" },
                                                { type: "rScript", name: "R visual", icon: "rVisual", accent: "#0078D4" },
                                                { type: "pythonScript", name: "Python visual", icon: "pythonVisual", accent: "#0078D4" },
                                                { type: "keyInfluencers", name: "Key influencers", icon: "keyInfluencers" },
                                                { type: "decomposition", name: "Decomposition tree", icon: "decomposition" },
                                                { type: "qa", name: "Q&A visual", icon: "qaVisual" },
                                                { type: "scorecard", name: "Scorecard", icon: "scorecard" },
                                                { type: "paginated", name: "Paginated report", icon: "paginatedReport" },
                                                { type: "visualFilter", name: "Visual filter", icon: "visualFilter" },
                                                { type: "quickVisual", name: "Quick visual", icon: "quickVisual" },
                                                { type: "smartVisual", name: "Smart visual", icon: "smartVisual" },
                                                { type: "image", name: "Image", icon: "image" },
                                                { type: "moreVisuals", name: "More visuals", icon: "galleryMore" },
                                                { type: "removed", name: "", icon: "" }
                                            ]
                                            delegate: Item {
                                                id: visualTypeTile
                                                required property int index
                                                required property var modelData
                                                property bool typeSelected: Boolean(modelData.active) && mainWindow.studioController.selectedChartType === modelData.type
                                                property real columnNudge: [0.5, 0, 0, -0.5, -1, -1.5][index % 6]
                                                property real rowHeight: visualGallery.height / 7 - 0.5
                                                x: (index % 6) * (visualGallery.width / 6) + columnNudge
                                                y: 1.5 + Math.floor(index / 6) * rowHeight
                                                width: visualGallery.width / 6
                                                height: rowHeight
                                                Rectangle {
                                                    anchors.fill: parent
                                                    visible: visualTypeTile.modelData.type === "removed"
                                                    color: "#f4f4f4"
                                                    Accessible.ignored: true
                                                }
                                                HoverHandler {
                                                    id: visualTypeHover
                                                    enabled: visualTypeTile.modelData.type !== "removed"
                                                }
                                                ToolTip.visible: visualTypeHover.hovered
                                                ToolTip.text: Boolean(modelData.active)
                                                        ? (mainWindow.studioController.selectedVisual
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
                                                              + (mainWindow.studioController.selectedVisual
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
                                                            useGalleryAtlas: true
                                                            implicitWidth: 24
                                                            implicitHeight: 24
                                                        }
                                                    }
                                                    onClicked: {
                                                        if (!mainWindow.studioController.selectedVisual)
                                                            mainWindow.runCommand("report.addMonthly")
                                                        mainWindow.runCommand("chart.type." + String(visualTypeTile.modelData.type))
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    Rectangle { Layout.fillWidth: true; height: 1; color: "#e1e5e8" }
                                    Repeater {
                                        model: mainWindow.studioController.activeVisualWells
                                        delegate: ColumnLayout {
                                            required property var modelData
                                            Layout.fillWidth: true
                                            spacing: 1.5
                                            Text {
                                                text: String(modelData.name)
                                                color: "#202020"
                                                font.pixelSize: 11
                                                font.weight: Font.Medium
                                                Layout.leftMargin: 7
                                                Layout.topMargin: 6
                                            }
                                            Rectangle {
                                                Layout.fillWidth: true
                                                Layout.preferredHeight: Math.max(27, modelData.fields.length * 27)
                                                color: "#fafafa"
                                                
                                                Canvas {
                                                    anchors.fill: parent
                                                    onWidthChanged: requestPaint()
                                                    onHeightChanged: requestPaint()
                                                    onPaint: {
                                                        const ctx = getContext("2d")
                                                        ctx.clearRect(0, 0, width, height)
                                                        ctx.strokeStyle = "#bfc3c6"
                                                        ctx.lineWidth = 1
                                                        ctx.setLineDash([3, 3])
                                                        ctx.strokeRect(0.5, 0.5, width - 1, height - 1)
                                                    }
                                                }
                                                
                                                Column {
                                                    anchors.fill: parent
                                                    anchors.margins: 1
                                                    
                                                    // Placeholder
                                                    Item {
                                                        width: parent.width
                                                        height: 25
                                                        visible: modelData.fields.length === 0
                                                        Text {
                                                            anchors.fill: parent
                                                            anchors.leftMargin: 9
                                                            verticalAlignment: Text.AlignVCenter
                                                            text: "Add data fields here"
                                                            color: "#78858d"
                                                            font.pixelSize: 10
                                                        }
                                                    }
                                                    
                                                    // Actual fields
                                                    Repeater {
                                                        model: modelData.fields
                                                        delegate: Rectangle {
                                                            required property var modelData
                                                            width: parent.width
                                                            height: 25
                                                            color: "#ffffff"
                                                            border.color: "#e1e5e8"
                                                            RowLayout {
                                                                anchors.fill: parent
                                                                spacing: 4
                                                                Item { Layout.preferredWidth: 6; Layout.fillHeight: true }
                                                                Text {
                                                                    Layout.fillWidth: true
                                                                    text: String(modelData)
                                                                    color: "#202020"
                                                                    font.pixelSize: 10
                                                                    elide: Text.ElideRight
                                                                }
                                                                ToolButton {
                                                                    text: "×"
                                                                    onClicked: mainWindow.studioController.remove_field_from_well(String(parent.parent.parent.modelData.name), String(modelData))
                                                                    contentItem: Text { text: "×"; color: "#657784"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                                                    background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                                
                                                MouseArea {
                                                    anchors.fill: parent
                                                    onClicked: function(mouse) {
                                                        fieldPickerMenu.wellName = String(modelData.name)
                                                        fieldPickerMenu.popup()
                                                    }
                                                }
                                            }
                                        }
                                    }
                                    
                                    Menu {
                                        id: fieldPickerMenu
                                        property string wellName: ""
                                        Repeater {
                                            model: mainWindow.studioController.filteredFields
                                            MenuItem {
                                                required property var modelData
                                                text: String(modelData)
                                                onTriggered: {
                                                    mainWindow.studioController.add_field_to_well(fieldPickerMenu.wellName, String(modelData))
                                                }
                                            }
                                        }
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        Layout.leftMargin: 7
                                        Layout.topMargin: 6.5
                                        text: "Drill through"
                                        color: "#202020"
                                        font.pixelSize: 11
                                        font.weight: Font.DemiBold
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 24
                                        Layout.leftMargin: 7
                                        Layout.rightMargin: 17
                                        Text { Layout.fillWidth: true; text: "Cross-report"; color: "#303030"; font.pixelSize: 10 }
                                        Item {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 16
                                            Accessible.name: "Cross-report drill-through; unavailable and off"
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 8
                                                color: "#ffffff"
                                                border.color: "#aab0b4"
                                                border.width: 1
                                                Rectangle {
                                                    width: 10
                                                    height: 10
                                                    anchors.left: parent.left
                                                    anchors.leftMargin: 2
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    radius: 5
                                                    color: "#737b80"
                                                }
                                                Text {
                                                    anchors.right: parent.right
                                                    anchors.rightMargin: 3
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    text: "Off"
                                                    color: "#50565a"
                                                    font.pixelSize: 7
                                                    font.weight: Font.DemiBold
                                                }
                                            }
                                        }
                                    }
                                    RowLayout {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 24
                                        Layout.leftMargin: 7
                                        Layout.rightMargin: 17
                                        Text { Layout.fillWidth: true; text: "Keep all filters"; color: "#303030"; font.pixelSize: 10 }
                                        Item {
                                            Layout.preferredWidth: 30
                                            Layout.preferredHeight: 16
                                            Accessible.name: "Keep all filters; fixed on"
                                            Rectangle {
                                                anchors.fill: parent
                                                radius: 9
                                                color: "#107c71"
                                                Rectangle {
                                                    width: 10
                                                    height: 10
                                                    anchors.right: parent.right
                                                    anchors.rightMargin: 2
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    radius: 5
                                                    color: "#ffffff"
                                                }
                                                Text {
                                                    anchors.left: parent.left
                                                    anchors.leftMargin: 4
                                                    anchors.verticalCenter: parent.verticalCenter
                                                    text: "On"
                                                    color: "#ffffff"
                                                    font.pixelSize: 7
                                                    font.weight: Font.DemiBold
                                                }
                                            }
                                        }
                                    }
                                    Rectangle {
                                        Layout.fillWidth: true
                                        Layout.preferredHeight: 23
                                        Layout.topMargin: 0.5
                                        color: "#fafafa"
                                        border.width: 0
                                        Text {
                                            anchors.fill: parent
                                            anchors.leftMargin: 8
                                            anchors.rightMargin: 6
                                            verticalAlignment: Text.AlignVCenter
                                            text: "Add drill-through fields here"
                                            color: "#78858d"
                                            font.pixelSize: 9
                                            elide: Text.ElideRight
                                        }
                                        Canvas {
                                            anchors.fill: parent
                                            onWidthChanged: requestPaint()
                                            onHeightChanged: requestPaint()
                                            onPaint: {
                                                const ctx = getContext("2d")
                                                ctx.clearRect(0, 0, width, height)
                                                ctx.strokeStyle = "#bfc3c6"
                                                ctx.lineWidth = 1
                                                ctx.setLineDash([3, 3])
                                                ctx.strokeRect(0.5, 0.5, width - 1, height - 1)
                                            }
                                        }
                                    }
                                    } // End of Build Visual ColumnLayout

                                    ColumnLayout {
                                        Layout.fillWidth: true
                                        visible: mainWindow.activeVisualTab === "format"
                                        
                                        Rectangle { Layout.fillWidth: true; Layout.topMargin: 1; height: 1; color: "#e1e5e8" }
                                        
                                        Item {
                                            Layout.fillWidth: true
                                            Layout.preferredHeight: 100
                                            Text {
                                                anchors.centerIn: parent
                                                text: "Format visual properties\n(Select visual)"
                                                horizontalAlignment: Text.AlignHCenter
                                                color: "#6e6e6e"
                                                font.pixelSize: 11
                                                visible: !mainWindow.studioController.selectedVisual
                                            }
                                            ColumnLayout {
                                                anchors.fill: parent
                                                visible: Boolean(mainWindow.studioController.selectedVisual)
                                                spacing: 4
                                                
                                                ScrollView {
                                                    Layout.fillWidth: true
                                                    Layout.fillHeight: true
                                                    clip: true
                                                    
                                                    ColumnLayout {
                                                        width: parent.width
                                                        spacing: 2
                                                        
                                                        Repeater {
                                                            model: mainWindow.studioController.activeVisualPropertyGroups
                                                            delegate: ColumnLayout {
                                                                required property var modelData
                                                                Layout.fillWidth: true
                                                                spacing: 0
                                                                
                                                                // Group Header
                                                                Rectangle {
                                                                    Layout.fillWidth: true
                                                                    Layout.preferredHeight: 28
                                                                    color: "#f3f2f1"
                                                                    border.width: 0
                                                                    RowLayout {
                                                                        anchors.fill: parent
                                                                        anchors.leftMargin: 8
                                                                        Text {
                                                                            text: String(modelData.name)
                                                                            font.pixelSize: 11
                                                                            font.weight: Font.DemiBold
                                                                            color: "#323130"
                                                                        }
                                                                    }
                                                                }
                                                                
                                                                // Properties
                                                                Repeater {
                                                                    model: modelData.properties
                                                                    delegate: Item {
                                                                        required property var modelData
                                                                        width: parent.width
                                                                        height: 32
                                                                        
                                                                        Text {
                                                                            anchors.left: parent.left
                                                                            anchors.leftMargin: 12
                                                                            anchors.verticalCenter: parent.verticalCenter
                                                                            text: String(modelData.label)
                                                                            font.pixelSize: 10
                                                                            color: "#605e5c"
                                                                        }
                                                                        
                                                                        TextField {
                                                                            visible: modelData.type === "string" || modelData.type === "number" || modelData.type === "color"
                                                                            anchors.right: parent.right
                                                                            anchors.rightMargin: 8
                                                                            anchors.verticalCenter: parent.verticalCenter
                                                                            width: parent.width / 2
                                                                            height: 24
                                                                            text: String(modelData.value)
                                                                            font.pixelSize: 10
                                                                            onEditingFinished: {
                                                                                let val = text
                                                                                if (modelData.type === "number") val = Number(text)
                                                                                mainWindow.studioController.set_visual_property(String(modelData.key), val)
                                                                            }
                                                                        }
                                                                    }
                                                                }
                                                            }
                                                        }
                                                    }
                                                }
                                            }
                                        }
                                    }
                                // End of Visualizations Main ColumnLayout
                                ToolButton {
                                    visible: !mainWindow.visualizationsVisible
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
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 9; name: "visual"; color: "#107C71"; implicitWidth: 20; implicitHeight: 20 }
                                        Text { anchors.centerIn: parent; text: "Visualizations"; rotation: -90; color: "#526573"; font.pixelSize: 11 }
                                    }
                                    onClicked: mainWindow.visualizationsVisible = true
                                }
                            }
                        }
                    }

                    Item {
                        Layout.preferredWidth: mainWindow.dataPaneExpanded ? 160 : 33
                        Layout.fillHeight: true
                        Rectangle {
                            anchors.fill: parent
                            color: mainWindow.dataPaneExpanded ? "#ffffff" : "#f8f9fa"
                            border.color: "#e0e3e6"
                            ColumnLayout {
                                anchors.fill: parent
                                spacing: 0
                                RowLayout {
                                    visible: mainWindow.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 29
                                    Layout.leftMargin: 7
                                    Icon { name: "data"; color: "#60798b"; implicitWidth: 14; implicitHeight: 14 }
                                    Text { Layout.fillWidth: true; text: "Data"; color: "#354755"; font.pixelSize: 9; font.weight: Font.DemiBold }
                                    ToolButton {
                                        padding: 0
                                        implicitWidth: 22
                                        implicitHeight: 22
                                        onClicked: mainWindow.dataPaneExpanded = false
                                        Accessible.name: "Collapse Data pane"
                                        ToolTip.visible: hovered
                                        ToolTip.text: "Collapse Data pane"
                                        background: Rectangle { color: parent.hovered ? "#f1f4f6" : "transparent" }
                                        contentItem: Icon { name: "collapsePane"; color: "#657784"; implicitWidth: 14; implicitHeight: 14 }
                                    }
                                }
                                TextField {
                                    visible: mainWindow.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 24
                                    Layout.leftMargin: 7
                                    Layout.rightMargin: 7
                                    text: mainWindow.fieldSearchQuery
                                    placeholderText: "Search fields"
                                    enabled: mainWindow.studioController.sourceLoaded
                                    font.pixelSize: 10
                                    color: "#40515e"
                                    onTextChanged: {
                                        if (mainWindow.fieldSearchQuery !== text)
                                            mainWindow.fieldSearchQuery = text
                                        mainWindow.studioController.setFieldQuery(text)
                                    }
                                    Accessible.name: "Search data fields"
                                    background: Rectangle { radius: 3; color: "#ffffff"; border.color: "#cfd7dd" }
                                }
                                Text {
                                    visible: mainWindow.dataPaneExpanded && mainWindow.studioController.sourceLoaded
                                    Layout.fillWidth: true
                                    Layout.preferredHeight: 21
                                    Layout.leftMargin: 9
                                    Layout.rightMargin: 7
                                    text: mainWindow.studioController.rowCount + " rows · " + mainWindow.studioController.columnCount + " fields"
                                    color: "#587488"
                                    font.pixelSize: 8
                                    elide: Text.ElideRight
                                    Accessible.name: text
                                }
                                ListView {
                                    visible: mainWindow.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    model: mainWindow.studioController.filteredFields
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
                                        visible: mainWindow.studioController.filteredFields.length === 0
                                        text: mainWindow.studioController.sourceLoaded ? "No matching fields" : "Import a CSV, Excel, JSON, XML, or Parquet file to browse its fields."
                                        color: "#76838d"
                                        font.pixelSize: 9
                                        wrapMode: Text.Wrap
                                    }
                                    Button {
                                        visible: !mainWindow.studioController.sourceLoaded
                                        anchors.horizontalCenter: parent.horizontalCenter
                                        anchors.top: parent.verticalCenter
                                        anchors.topMargin: 16
                                        text: "Import data"
                                        Accessible.name: "Import data from Data pane"
                                        background: Rectangle { radius: 3; color: parent.hovered ? "#e7f1f8" : "#f4f8fb"; border.color: "#cbdde9" }
                                        contentItem: Text { text: parent.text; color: "#315f7d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                                        onClicked: mainWindow.runCommand("data.importFile")
                                    }
                                }
                                ToolButton {
                                    visible: !mainWindow.dataPaneExpanded
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    padding: 0
                                    hoverEnabled: true
                                    focusPolicy: Qt.StrongFocus
                                    Accessible.name: "Expand Data pane"
                                    Accessible.description: mainWindow.studioController.sourceLoaded
                                                            ? String(mainWindow.studioController.columnCount) + " fields available. Open searchable field list."
                                                            : "No data source loaded. Open the Data pane for import options."
                                    ToolTip.visible: hovered
                                    ToolTip.text: mainWindow.studioController.sourceLoaded
                                                  ? "Data · " + mainWindow.studioController.columnCount + " fields"
                                                  : "Data · no source"
                                    background: Rectangle {
                                        color: parent.activeFocus ? "#e5f1f8" : (parent.hovered ? "#eef3f6" : "#f8f9fa")
                                        border.color: parent.activeFocus ? "#0078D4" : "#e0e3e6"
                                    }
                                    contentItem: Item {
                                        Icon { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 10; name: "collapseLeft"; color: "#657784"; implicitWidth: 16; implicitHeight: 16 }
                                        Text { anchors.horizontalCenter: parent.horizontalCenter; anchors.top: parent.top; anchors.topMargin: 50; text: "Data"; rotation: -90; color: "#526573"; font.pixelSize: 10 }
                                    }
                                    onClicked: mainWindow.dataPaneExpanded = true
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
            Rectangle { Layout.preferredWidth: mainWindow.navigationVisible ? 32 : 0; Layout.fillHeight: true; color: "#f8f9fa"; border.color: "#d6dbe0" }
                                RowLayout {
                                    visible: mainWindow.studioController.currentView === "Report"
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 4
                Repeater {
                    model: mainWindow.studioController.pages
                    delegate: Button {
                        required property int index
                        required property var modelData
                        Layout.preferredWidth: Math.max(90, pageLabel.implicitWidth + 28)
                        Layout.fillHeight: true
                        text: String(modelData.name)
                        onClicked: mainWindow.studioController.setActivePage(index)
                        background: Rectangle {
                            anchors.top: parent.top
                            anchors.bottom: parent.bottom
                            anchors.topMargin: 5
                            anchors.bottomMargin: 4
                            radius: 4
                            color: index === mainWindow.studioController.activePageIndex ? "#e8eff3" : "transparent"
                            border.color: index === mainWindow.studioController.activePageIndex ? "#cedbe3" : "transparent"
                        }
                        contentItem: Item {
                            implicitWidth: pageLabel.implicitWidth
                            implicitHeight: pageLabel.implicitHeight

                            Text {
                                id: pageLabel
                                anchors.fill: parent
                                text: String(modelData.name)
                                horizontalAlignment: Text.AlignHCenter
                                verticalAlignment: Text.AlignVCenter
                                color: modelData.hidden ? "#aab5bd" : "#506372"
                                font.pixelSize: 10
                                font.italic: modelData.hidden
                                visible: !pageEditor.visible
                            }
                            
                            TextField {
                                id: pageEditor
                                anchors.fill: parent
                                anchors.margins: -4
                                visible: false
                                text: String(modelData.name)
                                font.pixelSize: 10
                                background: Rectangle { color: "white"; border.color: "#0078d4" }
                                onEditingFinished: {
                                    visible = false;
                                    mainWindow.studioController.rename_page(String(modelData.id), text);
                                }
                                Keys.onEscapePressed: { visible = false; text = String(modelData.name); }
                            }
                        }

                        MouseArea {
                            anchors.fill: parent
                            acceptedButtons: Qt.RightButton
                            onClicked: function(mouse) {
                                pageMenu.popup()
                            }
                        }

                        Menu {
                            id: pageMenu
                            MenuItem {
                                text: "Rename"
                                onTriggered: {
                                    pageEditor.text = String(modelData.name)
                                    pageEditor.visible = true
                                    pageEditor.forceActiveFocus()
                                    pageEditor.selectAll()
                                }
                            }
                            MenuItem {
                                text: "Duplicate"
                                onTriggered: mainWindow.studioController.duplicate_page(String(modelData.id))
                            }
                            MenuItem {
                                text: "Move Left"
                                visible: index > 0
                                onTriggered: mainWindow.studioController.reorder_page(String(modelData.id), index - 1)
                            }
                            MenuItem {
                                text: "Move Right"
                                visible: index < mainWindow.studioController.pages.length - 1
                                onTriggered: mainWindow.studioController.reorder_page(String(modelData.id), index + 1)
                            }
                            MenuItem {
                                text: modelData.hidden ? "Unhide" : "Hide"
                                onTriggered: mainWindow.studioController.hide_page(String(modelData.id), !modelData.hidden)
                            }
                            MenuSeparator {
                                visible: mainWindow.studioController.pages.length > 1
                            }
                            MenuItem {
                                text: "Delete"
                                visible: mainWindow.studioController.pages.length > 1
                                onTriggered: mainWindow.studioController.delete_page(String(modelData.id))
                            }
                        }
                    }
                }
                ToolButton {
                    text: "+"
                    Accessible.name: "Add report page"
                    background: Rectangle { radius: 3; color: parent.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "+"; color: "#55728a"; font.pixelSize: 15; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: mainWindow.runCommand("report.addPage")
                }
                Item { Layout.fillWidth: true }
                Text { text: mainWindow.studioController.activePageName; color: "#6d7b86"; font.pixelSize: 9; Layout.rightMargin: 10 }
            }
            Item { visible: mainWindow.studioController.currentView !== "Report"; Layout.fillWidth: true }
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
                    text: mainWindow.studioController.statusMessage
                    color: "#687782"
                    font.pixelSize: 9
                    elide: Text.ElideRight
                }
                Text { text: mainWindow.studioController.currentView + " view"; color: "#78858e"; font.pixelSize: 9 }
                Rectangle { width: 1; Layout.fillHeight: true; color: "#d9dee2" }
                ToolButton {
                    id: zoomOutButton
                    visible: mainWindow.studioController.currentView === "Report"
                    text: "−"
                    padding: 0
                    implicitWidth: 20
                    implicitHeight: 18
                    Accessible.name: "Zoom out"
                    background: Rectangle { radius: 3; color: zoomOutButton.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "−"; color: "#526a7b"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: mainWindow.runCommand("view.zoomOut")
                }
                Slider {
                    id: zoomSlider
                    visible: mainWindow.studioController.currentView === "Report"
                    Layout.preferredWidth: 105
                    from: 0.15
                    to: 1.5
                    value: mainWindow.reportZoom
                    onMoved: { mainWindow.fitZoom = false; mainWindow.reportZoom = value }
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
                    visible: mainWindow.studioController.currentView === "Report"
                    text: "+"
                    padding: 0
                    implicitWidth: 20
                    implicitHeight: 18
                    Accessible.name: "Zoom in"
                    background: Rectangle { radius: 3; color: zoomInButton.hovered ? "#edf1f3" : "transparent" }
                    contentItem: Text { text: "+"; color: "#526a7b"; font.pixelSize: 14; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: mainWindow.runCommand("view.zoomIn")
                }
                Button {
                    visible: mainWindow.studioController.currentView === "Report"
                    text: Math.round(mainWindow.reportZoom * 100) + "%"
                    flat: true
                    padding: 2
                    font.pixelSize: 9
                    Accessible.name: "Zoom percentage; activate to fit page"
                    background: Rectangle { color: "transparent" }
                    contentItem: Text { text: parent.text; color: "#62727d"; font.pixelSize: 9; horizontalAlignment: Text.AlignHCenter; verticalAlignment: Text.AlignVCenter }
                    onClicked: mainWindow.runCommand("view.zoomFit")
                }
            }
        }
    }

    function hasAnyKpis() {
        const visuals = mainWindow.studioController.activePageVisuals
        for (let i = 0; i < visuals.length; ++i)
            if (String(visuals[i]).indexOf(" KPI") >= 0) return true
        return false
    }

    function hasAnyCharts() {
        const visuals = mainWindow.studioController.activePageVisuals
        return visuals.indexOf("Monthly revenue") >= 0 || visuals.indexOf("Region revenue") >= 0
    }

    onClosing: function(close) {
        if (!mainWindow.studioController.confirmClose())
            close.accepted = false
    }

    Component.onCompleted: {
        mainWindow.lastWorkspaceView = String(mainWindow.studioController.currentView)
        mainWindow.selectRibbonForView(mainWindow.lastWorkspaceView)
        Qt.callLater(mainWindow.zoomToFit)
    }
}
