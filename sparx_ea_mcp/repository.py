"""
Read-only data access functions over the Enterprise Architect repository
schema (t_package, t_object, t_diagram, t_connector, ...).

Every query here is written in ANSI SQL:2008 so it runs unchanged against
any ODBC-reachable DBMS that implements that standard closely enough:

- `OFFSET 0 ROWS FETCH FIRST n ROWS ONLY` instead of vendor row-limiting
  syntax (`TOP`, non-standard `LIMIT`). The `OFFSET 0 ROWS` is not
  optional padding - SQL Server's T-SQL requires OFFSET whenever FETCH is
  used (bare `FETCH FIRST n ROWS ONLY` is a syntax error there, unlike
  PostgreSQL/MySQL 8.0.19+/MariaDB, which all permit it standalone).
  Needs SQL Server 2012+, PostgreSQL 8.4+, Oracle 12c+, MySQL
  8.0.19+/MariaDB 10.2+, Firebird 3.0+.
- Double-quoted identifiers for the handful of genuinely reserved-word
  columns EA's schema uses (`"Default"`, `"VALUE"`, `"NOTES"`). This is
  native on SQL Server (ODBC connections default to QUOTED_IDENTIFIER ON),
  PostgreSQL, Oracle and Firebird; on MySQL/MariaDB, db.py enables it by
  issuing `SET SESSION sql_mode = ANSI_QUOTES` right after connecting.
- `?` parameter placeholders, which is the ODBC standard - every ODBC
  driver accepts this regardless of the target DBMS's native paramstyle.
- Every output column is given an explicit `AS "CanonicalName"` alias.
  This isn't optional decoration: PostgreSQL's ODBC driver folds
  unquoted/unaliased column names to lowercase in the result set (e.g.
  `Object_Type` comes back as `object_type`), while other backends
  preserve the case as written. Quoting the alias pins the exact
  dict-key casing every tool returns, regardless of backend.

Table reference (canonical names/columns, from Sparx's SQL Server schema
script - other backends' official schema scripts use the same names):

  t_package          Package_ID, Name, Parent_ID, Notes, ea_guid, ...
  t_object           Object_ID, Object_Type, Name, Alias, Package_ID,
                     Stereotype, Note, ea_guid, Classifier, ...
  t_diagram          Diagram_ID, Package_ID, Diagram_Type, Name, Notes,
                     ea_guid, ...
  t_diagramobjects   Diagram_ID, Object_ID, RectTop/Left/Right/Bottom, ...
  t_connector        Connector_ID, Name, Connector_Type, SubType,
                     Start_Object_ID, End_Object_ID, SourceRole, DestRole,
                     SourceCard, DestCard, DiagramID, ea_guid, ...
  t_attribute        Object_ID, Name, Type, Scope, Notes, "Default", ...
  t_operation        OperationID, Object_ID, Name, Type, Scope, Notes, ...
  t_operationparams  OperationID, Name, Type, "Default", Kind, Pos, ...
  t_objectproperties Object_ID, Property, "Value", Notes  (classic tagged values)
  t_taggedvalue      ElementID(guid), BaseClass, TagValue, Notes  (newer tagged values)
  t_attributetag / t_operationtag / t_connectortag  ElementID(int FK), Property, "VALUE", "NOTES"
  t_document         DocID, DocName, ElementID(guid), ElementType, StrContent, ...

A note on identifier casing in the *source* names (not the output
aliases): this module references the tables/columns above unquoted,
relying on each DBMS's own case-folding of unquoted identifiers to match
however its own official EA schema script created them - this is what the
supplied SQL Server script does, and is the expected convention. Oracle
and Firebird fold unquoted identifiers to UPPERCASE by default; if a
schema was created there with explicitly quoted mixed-case names instead,
adjust the source names below to match. scripts/smoke_test.py will
surface a clear driver error if any name here doesn't match what's
actually in your database.
"""

from __future__ import annotations

from typing import Optional

from . import db
from .config import get_config


def _limit(n: Optional[int]) -> int:
    cfg = get_config()
    if n is None:
        return cfg.row_limit
    return max(1, min(n, cfg.row_limit))


def _name_clause(column: str, name: str, exact: bool, params: list) -> str:
    if exact:
        params.append(name)
        return f"{column} = ?"
    # LIKE's case-sensitivity is backend/collation-dependent (case-sensitive
    # on PostgreSQL by default, case-insensitive on SQL Server/MySQL by
    # default) - LOWER() on both sides is plain ANSI SQL and makes
    # substring search behave the same everywhere.
    params.append(f"%{name.lower()}%")
    return f"LOWER({column}) LIKE ?"


# --------------------------------------------------------------------------
# Model overview
# --------------------------------------------------------------------------

def get_model_overview() -> dict:
    """High-level stats about the connected repository."""
    counts = {
        "packages": db.run_query_one('SELECT COUNT(*) AS "n" FROM t_package')["n"],
        "elements": db.run_query_one(
            'SELECT COUNT(*) AS "n" FROM t_object WHERE Object_Type <> \'Package\''
        )["n"],
        "diagrams": db.run_query_one('SELECT COUNT(*) AS "n" FROM t_diagram')["n"],
        "connectors": db.run_query_one('SELECT COUNT(*) AS "n" FROM t_connector')["n"],
    }
    top_element_types = db.run_query(
        """
        SELECT Object_Type AS "Object_Type", COUNT(*) AS "Count"
        FROM t_object
        WHERE Object_Type <> 'Package'
        GROUP BY Object_Type
        ORDER BY "Count" DESC
        OFFSET 0 ROWS FETCH FIRST 15 ROWS ONLY
        """
    )
    diagram_types = db.run_query(
        """
        SELECT Diagram_Type AS "Diagram_Type", COUNT(*) AS "Count"
        FROM t_diagram
        GROUP BY Diagram_Type
        ORDER BY "Count" DESC
        OFFSET 0 ROWS FETCH FIRST 15 ROWS ONLY
        """
    )
    return {
        "counts": counts,
        "top_element_types": top_element_types,
        "diagram_types": diagram_types,
    }


# --------------------------------------------------------------------------
# Packages
# --------------------------------------------------------------------------

def get_root_packages() -> list[dict]:
    """
    Top-level packages as they appear in the EA Browser window.

    EA repositories have one invisible "Model" package with Parent_ID = 0;
    everything the user actually sees at the top of the Browser tree is a
    direct child of that package. This mirrors that structure instead of
    returning the invisible root itself.
    """
    invisible_root = db.run_query_one(
        """
        SELECT Package_ID AS "Package_ID"
        FROM t_package
        WHERE Parent_ID = 0 OR Parent_ID IS NULL
        ORDER BY Package_ID
        OFFSET 0 ROWS FETCH FIRST 1 ROWS ONLY
        """
    )
    if not invisible_root:
        return []
    root_id = invisible_root["Package_ID"]
    return db.run_query(
        """
        SELECT
            p.Package_ID AS "Package_ID", p.Name AS "Name",
            p.ea_guid AS "ea_guid", p.Notes AS "Notes",
            p.CreatedDate AS "CreatedDate", p.ModifiedDate AS "ModifiedDate",
            (SELECT COUNT(*) FROM t_package c WHERE c.Parent_ID = p.Package_ID) AS "SubpackageCount",
            (SELECT COUNT(*) FROM t_object o WHERE o.Package_ID = p.Package_ID AND o.Object_Type <> 'Package') AS "ElementCount",
            (SELECT COUNT(*) FROM t_diagram d WHERE d.Package_ID = p.Package_ID) AS "DiagramCount"
        FROM t_package p
        WHERE p.Parent_ID = ?
        ORDER BY p.Name
        """,
        (root_id,),
    )


def find_packages_by_name(name: str, exact_match: bool = False, limit: int = 50) -> list[dict]:
    """Search packages by name (substring match by default)."""
    params: list = []
    clause = _name_clause("p.Name", name, exact_match, params)
    lim = _limit(limit)
    return db.run_query(
        f"""
        SELECT
            p.Package_ID AS "Package_ID", p.Name AS "Name", p.Parent_ID AS "Parent_ID",
            p.ea_guid AS "ea_guid", p.Notes AS "Notes",
            parent.Name AS "ParentPackageName"
        FROM t_package p
        LEFT JOIN t_package parent ON parent.Package_ID = p.Parent_ID
        WHERE {clause}
        ORDER BY p.Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        params + [lim],
    )


def get_package_contents(package_id: int) -> dict:
    """
    A package's own metadata plus its direct subpackages, elements and
    diagrams (one level deep - call again with a subpackage's ID to descend
    further, the same way the EA Browser tree expands).
    """
    pkg = db.run_query_one(
        """
        SELECT Package_ID AS "Package_ID", Name AS "Name", Parent_ID AS "Parent_ID",
               ea_guid AS "ea_guid", Notes AS "Notes",
               CreatedDate AS "CreatedDate", ModifiedDate AS "ModifiedDate", Version AS "Version"
        FROM t_package
        WHERE Package_ID = ?
        """,
        (package_id,),
    )
    if not pkg:
        return {"error": f"No package found with Package_ID={package_id}"}

    pkg["subpackages"] = db.run_query(
        'SELECT Package_ID AS "Package_ID", Name AS "Name", ea_guid AS "ea_guid" '
        "FROM t_package WHERE Parent_ID = ? ORDER BY Name",
        (package_id,),
    )
    pkg["elements"] = db.run_query(
        """
        SELECT Object_ID AS "Object_ID", Name AS "Name", Object_Type AS "Object_Type",
               Stereotype AS "Stereotype", Alias AS "Alias", ea_guid AS "ea_guid"
        FROM t_object
        WHERE Package_ID = ? AND Object_Type <> 'Package'
        ORDER BY Name
        """,
        (package_id,),
    )
    pkg["diagrams"] = db.run_query(
        'SELECT Diagram_ID AS "Diagram_ID", Name AS "Name", Diagram_Type AS "Diagram_Type", '
        'ea_guid AS "ea_guid" FROM t_diagram WHERE Package_ID = ? ORDER BY Name',
        (package_id,),
    )
    return pkg


# --------------------------------------------------------------------------
# Elements
# --------------------------------------------------------------------------

def find_elements_by_name(
    name: str,
    exact_match: bool = False,
    object_type: Optional[str] = None,
    limit: int = 50,
) -> list[dict]:
    """Search elements (classes, interfaces, actors, use cases, ...) by name."""
    params: list = []
    clause = _name_clause("o.Name", name, exact_match, params)
    extra = ""
    if object_type:
        extra = " AND o.Object_Type = ?"
        params.append(object_type)
    lim = _limit(limit)
    return db.run_query(
        f"""
        SELECT
            o.Object_ID AS "Object_ID", o.Name AS "Name", o.Object_Type AS "Object_Type",
            o.Stereotype AS "Stereotype", o.Alias AS "Alias",
            o.ea_guid AS "ea_guid", o.Package_ID AS "Package_ID",
            pkg.Name AS "PackageName"
        FROM t_object o
        LEFT JOIN t_package pkg ON pkg.Package_ID = o.Package_ID
        WHERE {clause} AND o.Object_Type <> 'Package'{extra}
        ORDER BY o.Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        params + [lim],
    )


def get_elements_information(object_id: int) -> dict:
    """
    Full detail for one element: core properties, attributes, operations
    (with parameters), tagged values, and a short summary of connectors.
    Use get_connectors_information / find_element_in_diagrams for the full
    connector and diagram lists.
    """
    obj = db.run_query_one(
        """
        SELECT o.Object_ID AS "Object_ID", o.Name AS "Name", o.Object_Type AS "Object_Type",
               o.Stereotype AS "Stereotype", o.Alias AS "Alias", o.Author AS "Author",
               o.Version AS "Version", o.Note AS "Note", o.Status AS "Status",
               o.Complexity AS "Complexity", o.Phase AS "Phase", o.ea_guid AS "ea_guid",
               o.Package_ID AS "Package_ID", o.ParentID AS "ParentID",
               o.Classifier AS "Classifier", o.Visibility AS "Visibility",
               o.CreatedDate AS "CreatedDate", o.ModifiedDate AS "ModifiedDate",
               pkg.Name AS "PackageName"
        FROM t_object o
        LEFT JOIN t_package pkg ON pkg.Package_ID = o.Package_ID
        WHERE o.Object_ID = ?
        """,
        (object_id,),
    )
    if not obj:
        return {"error": f"No element found with Object_ID={object_id}"}

    obj["attributes"] = db.run_query(
        """
        SELECT ID AS "ID", Name AS "Name", Type AS "Type", Scope AS "Scope",
               Notes AS "Notes", "Default" AS "Default",
               LowerBound AS "LowerBound", UpperBound AS "UpperBound",
               Stereotype AS "Stereotype", Container AS "Container"
        FROM t_attribute
        WHERE Object_ID = ?
        ORDER BY Pos
        """,
        (object_id,),
    )
    for attr in obj["attributes"]:
        attr["tagged_values"] = db.run_query(
            'SELECT Property AS "Property", "VALUE" AS "Value", "NOTES" AS "Notes" '
            "FROM t_attributetag WHERE ElementID = ? ORDER BY Property",
            (attr["ID"],),
        )

    operations = db.run_query(
        """
        SELECT OperationID AS "OperationID", Name AS "Name", Type AS "Type",
               Scope AS "Scope", Notes AS "Notes", Stereotype AS "Stereotype",
               Abstract AS "Abstract", IsStatic AS "IsStatic"
        FROM t_operation
        WHERE Object_ID = ?
        ORDER BY Pos
        """,
        (object_id,),
    )
    for op in operations:
        op["parameters"] = db.run_query(
            """
            SELECT Name AS "Name", Type AS "Type", "Default" AS "Default", Kind AS "Kind"
            FROM t_operationparams
            WHERE OperationID = ?
            ORDER BY Pos
            """,
            (op["OperationID"],),
        )
        op["tagged_values"] = db.run_query(
            'SELECT Property AS "Property", "VALUE" AS "Value", "NOTES" AS "Notes" '
            "FROM t_operationtag WHERE ElementID = ? ORDER BY Property",
            (op["OperationID"],),
        )
    obj["operations"] = operations

    # Tagged values live in one of two places depending on EA version /
    # notation: the classic per-element table (int FK) or the newer
    # generic table (keyed by ea_guid + BaseClass). Merge both.
    classic_tags = db.run_query(
        'SELECT Property AS "Property", "Value" AS "Value", Notes AS "Notes" '
        "FROM t_objectproperties WHERE Object_ID = ? ORDER BY Property",
        (object_id,),
    )
    guid = obj.get("ea_guid")
    modern_tags = []
    if guid:
        modern_tags = db.run_query(
            """
            SELECT PropertyID AS "PropertyID", TagValue AS "Value", Notes AS "Notes"
            FROM t_taggedvalue
            WHERE ElementID = ? AND BaseClass = 'Element'
            """,
            (guid,),
        )
    obj["tagged_values"] = classic_tags + modern_tags

    obj["connector_count"] = db.run_query_one(
        'SELECT COUNT(*) AS "n" FROM t_connector WHERE Start_Object_ID = ? OR End_Object_ID = ?',
        (object_id, object_id),
    )["n"]
    obj["diagram_usage_count"] = db.run_query_one(
        'SELECT COUNT(*) AS "n" FROM t_diagramobjects WHERE Object_ID = ?',
        (object_id,),
    )["n"]

    return obj


def find_element_in_diagrams(object_id: int) -> list[dict]:
    """All diagrams that display a given element, with its position on each."""
    return db.run_query(
        """
        SELECT
            d.Diagram_ID AS "Diagram_ID", d.Name AS "DiagramName", d.Diagram_Type AS "Diagram_Type",
            pkg.Name AS "PackageName",
            dobj.RectLeft AS "RectLeft", dobj.RectTop AS "RectTop",
            dobj.RectRight AS "RectRight", dobj.RectBottom AS "RectBottom"
        FROM t_diagramobjects dobj
        JOIN t_diagram d ON d.Diagram_ID = dobj.Diagram_ID
        LEFT JOIN t_package pkg ON pkg.Package_ID = d.Package_ID
        WHERE dobj.Object_ID = ?
        ORDER BY d.Name
        """,
        (object_id,),
    )


def export_element_linked_documents(object_id: int) -> list[dict]:
    """
    Linked/embedded documents for an element (t_document), e.g. text
    inserted via EA's "Linked Document" feature. Binary attachments are
    reported by size only; text content is returned as-is.
    """
    guid = db.run_query_one(
        'SELECT ea_guid AS "ea_guid" FROM t_object WHERE Object_ID = ?', (object_id,)
    )
    if not guid or not guid.get("ea_guid"):
        return []
    return db.run_query(
        """
        SELECT DocID AS "DocID", DocName AS "DocName", DocType AS "DocType",
               Author AS "Author", Version AS "Version", IsActive AS "IsActive",
               DocDate AS "DocDate", StrContent AS "StrContent"
        FROM t_document
        WHERE ElementID = ?
        ORDER BY Sequence
        """,
        (guid["ea_guid"],),
    )


# --------------------------------------------------------------------------
# Connectors
# --------------------------------------------------------------------------

def get_connectors_information(object_id: int) -> list[dict]:
    """All connectors (relationships) attached to an element, either end."""
    rows = db.run_query(
        """
        SELECT
            c.Connector_ID AS "Connector_ID", c.Name AS "Name",
            c.Connector_Type AS "Connector_Type", c.SubType AS "SubType",
            c.Direction AS "Direction", c.Notes AS "Notes", c.Stereotype AS "Stereotype",
            c.Start_Object_ID AS "Start_Object_ID",
            src.Name AS "SourceName", src.Object_Type AS "SourceType",
            c.End_Object_ID AS "End_Object_ID",
            dst.Name AS "DestName", dst.Object_Type AS "DestType",
            c.SourceRole AS "SourceRole", c.SourceCard AS "SourceCard",
            c.DestRole AS "DestRole", c.DestCard AS "DestCard", c.ea_guid AS "ea_guid"
        FROM t_connector c
        LEFT JOIN t_object src ON src.Object_ID = c.Start_Object_ID
        LEFT JOIN t_object dst ON dst.Object_ID = c.End_Object_ID
        WHERE c.Start_Object_ID = ? OR c.End_Object_ID = ?
        ORDER BY c.Connector_Type, c.Name
        """,
        (object_id, object_id),
    )
    for row in rows:
        row["direction_relative_to_element"] = (
            "outgoing" if row["Start_Object_ID"] == object_id else "incoming"
        )
        row["tagged_values"] = db.run_query(
            'SELECT Property AS "Property", "VALUE" AS "Value", "NOTES" AS "Notes" '
            "FROM t_connectortag WHERE ElementID = ? ORDER BY Property",
            (row["Connector_ID"],),
        )
    return rows


# --------------------------------------------------------------------------
# Diagrams
# --------------------------------------------------------------------------

def find_diagrams_by_name(name: str, exact_match: bool = False, limit: int = 50) -> list[dict]:
    """Search diagrams by name."""
    params: list = []
    clause = _name_clause("d.Name", name, exact_match, params)
    lim = _limit(limit)
    return db.run_query(
        f"""
        SELECT
            d.Diagram_ID AS "Diagram_ID", d.Name AS "Name", d.Diagram_Type AS "Diagram_Type",
            d.ea_guid AS "ea_guid", pkg.Name AS "PackageName", d.Package_ID AS "Package_ID"
        FROM t_diagram d
        LEFT JOIN t_package pkg ON pkg.Package_ID = d.Package_ID
        WHERE {clause}
        ORDER BY d.Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        params + [lim],
    )


def get_diagrams_information(diagram_id: int) -> dict:
    """
    Diagram metadata plus every element placed on it and every connector
    drawn between those elements on this diagram.
    """
    diagram = db.run_query_one(
        """
        SELECT
            d.Diagram_ID AS "Diagram_ID", d.Name AS "Name", d.Diagram_Type AS "Diagram_Type",
            d.Notes AS "Notes", d.Author AS "Author", d.Version AS "Version",
            d.ea_guid AS "ea_guid", d.Package_ID AS "Package_ID", pkg.Name AS "PackageName",
            d.CreatedDate AS "CreatedDate", d.ModifiedDate AS "ModifiedDate",
            d.Orientation AS "Orientation", d.Stereotype AS "Stereotype"
        FROM t_diagram d
        LEFT JOIN t_package pkg ON pkg.Package_ID = d.Package_ID
        WHERE d.Diagram_ID = ?
        """,
        (diagram_id,),
    )
    if not diagram:
        return {"error": f"No diagram found with Diagram_ID={diagram_id}"}

    elements = db.run_query(
        """
        SELECT
            o.Object_ID AS "Object_ID", o.Name AS "Name", o.Object_Type AS "Object_Type",
            o.Stereotype AS "Stereotype", o.ea_guid AS "ea_guid",
            dobj.RectLeft AS "RectLeft", dobj.RectTop AS "RectTop",
            dobj.RectRight AS "RectRight", dobj.RectBottom AS "RectBottom",
            dobj.Sequence AS "Sequence"
        FROM t_diagramobjects dobj
        JOIN t_object o ON o.Object_ID = dobj.Object_ID
        WHERE dobj.Diagram_ID = ?
        ORDER BY dobj.Sequence
        """,
        (diagram_id,),
    )
    diagram["elements"] = elements

    element_ids = [e["Object_ID"] for e in elements]
    if element_ids:
        placeholders = ",".join("?" for _ in element_ids)
        connectors = db.run_query(
            f"""
            SELECT
                c.Connector_ID AS "Connector_ID", c.Name AS "Name",
                c.Connector_Type AS "Connector_Type", c.SubType AS "SubType",
                c.Start_Object_ID AS "Start_Object_ID", src.Name AS "SourceName",
                c.End_Object_ID AS "End_Object_ID", dst.Name AS "DestName",
                c.SourceRole AS "SourceRole", c.SourceCard AS "SourceCard",
                c.DestRole AS "DestRole", c.DestCard AS "DestCard",
                c.ea_guid AS "ea_guid"
            FROM t_connector c
            JOIN t_object src ON src.Object_ID = c.Start_Object_ID
            JOIN t_object dst ON dst.Object_ID = c.End_Object_ID
            WHERE c.Start_Object_ID IN ({placeholders})
              AND c.End_Object_ID IN ({placeholders})
            ORDER BY c.Connector_Type, c.Name
            """,
            element_ids + element_ids,
        )
    else:
        connectors = []
    diagram["connectors"] = connectors

    return diagram


# --------------------------------------------------------------------------
# Cross-cutting search
# --------------------------------------------------------------------------

def search_model(text: str, limit: int = 25) -> dict:
    """
    Free-text search across package names, element names/notes and diagram
    names in one call - a fast way to orient before drilling in with the
    more specific tools above.
    """
    lim = _limit(limit)
    like = f"%{text.lower()}%"
    packages = db.run_query(
        """
        SELECT Package_ID AS "Package_ID", Name AS "Name" FROM t_package WHERE LOWER(Name) LIKE ?
        ORDER BY Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        (like, lim),
    )
    elements = db.run_query(
        """
        SELECT Object_ID AS "Object_ID", Name AS "Name", Object_Type AS "Object_Type",
               Stereotype AS "Stereotype"
        FROM t_object
        WHERE Object_Type <> 'Package' AND (LOWER(Name) LIKE ? OR LOWER(Note) LIKE ?)
        ORDER BY Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        (like, like, lim),
    )
    diagrams = db.run_query(
        """
        SELECT Diagram_ID AS "Diagram_ID", Name AS "Name", Diagram_Type AS "Diagram_Type"
        FROM t_diagram WHERE LOWER(Name) LIKE ?
        ORDER BY Name
        OFFSET 0 ROWS FETCH FIRST ? ROWS ONLY
        """,
        (like, lim),
    )
    return {"packages": packages, "elements": elements, "diagrams": diagrams}
