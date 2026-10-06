"""Presentation-only inventory for the Get Data picker."""

from __future__ import annotations

import re


SOURCE_CATEGORIES = (
    "All",
    "File",
    "Database",
    "Power BI",
    "Microsoft",
    "Online Services",
    "Other",
)

_CATEGORY_NAMES = {
    "File": (
        "Excel Workbook", "Text/CSV", "XML", "JSON", "Folder", "PDF", "Parquet",
    ),
    "Database": (
        "Oracle database", "IBM Db2 database", "IBM Informix database (Beta)",
        "IBM Netezza", "MySQL database", "PostgreSQL database", "Sybase database",
        "Teradata database", "SAP HANA database", "SAP Business Warehouse Application Server",
        "SAP Business Warehouse Message Server", "Amazon Redshift", "Impala",
        "Google BigQuery", "Vertica",
        "Snowflake", "Essbase", "AtScale Models", "Actian (Beta)", "Amazon Athena",
        "BI Connector", "Data Virtuality LDW", "Exact Online Premium (Beta)",
        "Jethro (Beta)", "Kyligence", "Linkar PICK Style / MultiValue Databases (Beta)",
        "MariaDB", "MarkLogic", "MongoDB Atlas SQL", "TIBCO® Data Virtualization",
        "AtScale cubes", "Denodo", "Dremio Software", "Dremio Cloud", "Exasol",
        "ClickHouse (beta)", "InterSystems Health Insight",
        "KX kdb Insights Enterprise (beta)", "Kyvos ODBC (beta)",
    ),
    "Power BI": ("Power BI semantic models",),
    "Microsoft": ("OneLake catalog", "SQL Server", "Dataverse"),
    "Online Services": (
        "Planview OKR (beta)",
        "Planview ProjectPlace", "Quickbase", "SoftOne BI (Beta)", "Planview IdeaPlace",
        "TeamDesk (beta)", "Webtrends Analytics (Beta)", "Witivio (Beta)",
        "Zoho Creator", "Automation Anywhere", "CData Connect Cloud",
        "Databricks", "Funnel", "LEAP (Beta)", "Product Insights (Beta)",
        "Profisee", "Samsara (Beta)", "Supermetrics (beta)", "Zendesk (Beta)",
        "BuildingConnected & TradeTapp (beta)",
        "Smartsheet (Beta)",
    ),
    "Other": (
        "Web", "OData Feed", "Hadoop File (HDFS)", "Spark", "Hive LLAP",
        "R script", "Python script", "ODBC", "OLE DB",
        "Acterys : Model Automation & Planning (Beta)",
        "Amazon OpenSearch Service (Beta)", "Anaplan", "Solver",
        "Bloomberg Data and Analytics", "Celonis EMS", "Cherwell (Beta)",
        "CloudBluePSA (Beta)", "Cognite Data Fusion", "EQuIS", "FactSet RMS (Beta)",
        "inwink (Beta)", "Kognitwin", "MicroStrategy for Power BI", "OneStream (Beta)",
        "OpenSearch Project (Beta)", "Paxata", "QubolePresto (Beta)", "Roamler (Beta)",
        "SIS-CC SDMX (Beta)", "Shortcuts Business Insights (Beta)",
        "Starburst Enterprise", "SumTotal", "SurveyMonkey", "Tenforce (Smart)List",
        "Usercube (Beta)", "Vena", "Vessel Insight", "Wrike (Beta)",
        "Zucchetti HR Infinity (Beta)", "BitSight Security Ratings", "BQE CORE",
        "Wolters Kluwer CCH Tagetik", "Delta Sharing", "Eduframe (Beta)", "FHIR",
        "Google Sheets", "InformationGrid", "Jamf Pro (Beta)",
        "SingleStore Direct Query Connector", "Siteimprove", "SolarWinds Service Desk",
        "Windsor (beta)", "Blank Query",
    ),
}


def _icon_for(category: str, name: str) -> str:
    normalized = name.casefold()
    if name == "Excel Workbook":
        return "excel"
    if name == "Text/CSV":
        return "csv"
    if name == "XML":
        return "xml"
    if name == "JSON":
        return "json"
    if name == "PDF":
        return "pdf"
    if name == "Parquet":
        return "parquet"
    if name == "OneLake catalog":
        return "databaseLink"
    if name == "SQL Server":
        return "database"
    if name == "Dataverse":
        return "table"
    if "folder" in normalized:
        return "folder"
    if "semantic model" in normalized:
        return "semanticModel"
    if category == "File":
        return "file"
    if category == "Database":
        return "database"
    if category == "Power BI":
        return "databaseMultiple"
    if category == "Online Services":
        return "table"
    return "plug"


def _entry(category: str, name: str) -> dict[str, object]:
    category_key = re.sub(r"[^a-z0-9]+", "_", category.casefold()).strip("_")
    name_key = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
    status = "Preview" if "preview" in name.casefold() else (
        "Beta" if "beta" in name.casefold() else ""
    )
    implemented = category == "File" and name in {"Text/CSV", "Excel Workbook"}
    return {
        "id": f"{category_key}_{name_key}",
        "name": name,
        "category": category,
        "iconName": _icon_for(category, name),
        "previewStatus": status,
        "implemented": implemented,
        "unavailableReason": "" if implemented else (
            "This connector is listed for UI discovery; connection support is not implemented."
        ),
    }


DATA_SOURCE_CATALOG = tuple(
    _entry(category, name)
    for category, names in _CATEGORY_NAMES.items()
    for name in names
)

DATA_SOURCE_COUNTS = {
    category: len(names) for category, names in _CATEGORY_NAMES.items()
}
DATA_SOURCE_COUNT = len(DATA_SOURCE_CATALOG)
