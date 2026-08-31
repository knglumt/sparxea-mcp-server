"""
Best-effort schematic SVG rendering of a diagram, built purely from the
layout coordinates stored in the repository (t_diagramobjects rectangles
and element/connector positions).

This is NOT a reproduction of Enterprise Architect's own renderer - no
fonts, colors, notation-specific shapes (actors, use-case ellipses,
lifelines, ...) or styling are read from EA's style engine. It exists
because the official EA MCP Server's `get_diagram_image` calls the live
EA.exe rendering engine, which is unavailable when reading straight from
the database. This gives an LLM (or a person) a rough box-and-line layout
to orient with; always cross-check details against get_diagrams_information.
"""

from __future__ import annotations

from html import escape

_PADDING = 20


def render_diagram_svg(diagram: dict) -> str:
    elements = diagram.get("elements", [])
    connectors = diagram.get("connectors", [])

    if not elements:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="120">'
            '<text x="20" y="60" font-family="sans-serif" font-size="14">'
            "No laid-out elements found for this diagram.</text></svg>"
        )

    # EA stores rectangles with somewhat arbitrary origin/scale; normalize
    # so everything fits in a positive, top-left-origin coordinate space.
    lefts = [min(e["RectLeft"], e["RectRight"]) for e in elements]
    tops = [min(e["RectTop"], e["RectBottom"]) for e in elements]
    min_x, min_y = min(lefts), min(tops)

    def nx(v):
        return v - min_x + _PADDING

    def ny(v):
        return v - min_y + _PADDING

    boxes_by_id = {}
    max_x = max_y = 0
    svg_parts = []

    for el in elements:
        x1, x2 = sorted((nx(el["RectLeft"]), nx(el["RectRight"])))
        y1, y2 = sorted((ny(el["RectTop"]), ny(el["RectBottom"])))
        width, height = max(x2 - x1, 40), max(y2 - y1, 30)
        max_x, max_y = max(max_x, x2), max(max_y, y2)
        boxes_by_id[el["Object_ID"]] = (x1, y1, width, height)

        name = escape(str(el.get("Name") or "(unnamed)"))
        stereotype = el.get("Stereotype")
        obj_type = escape(str(el.get("Object_Type") or ""))

        svg_parts.append(
            f'<rect x="{x1:.0f}" y="{y1:.0f}" width="{width:.0f}" height="{height:.0f}" '
            f'fill="var(--ea-fill, #eef3fb)" stroke="var(--ea-stroke, #33475b)" rx="2"/>'
        )
        text_y = y1 + 16
        if stereotype:
            svg_parts.append(
                f'<text x="{x1 + 6:.0f}" y="{text_y:.0f}" font-family="sans-serif" '
                f'font-size="10" fill="#5b6b7c">&#171;{escape(str(stereotype))}&#187;</text>'
            )
            text_y += 14
        svg_parts.append(
            f'<text x="{x1 + 6:.0f}" y="{text_y:.0f}" font-family="sans-serif" '
            f'font-size="12" font-weight="bold" fill="#1b2733">{name}</text>'
        )
        svg_parts.append(
            f'<text x="{x1 + 6:.0f}" y="{y2 - 6:.0f}" font-family="sans-serif" '
            f'font-size="9" fill="#7a8a99">{obj_type}</text>'
        )

    line_parts = []
    for c in connectors:
        start = boxes_by_id.get(c.get("Start_Object_ID"))
        end = boxes_by_id.get(c.get("End_Object_ID"))
        if not start or not end:
            continue
        sx, sy = start[0] + start[2] / 2, start[1] + start[3] / 2
        ex, ey = end[0] + end[2] / 2, end[1] + end[3] / 2
        label = escape(str(c.get("Name") or c.get("Connector_Type") or ""))
        mx, my = (sx + ex) / 2, (sy + ey) / 2
        line_parts.append(
            f'<line x1="{sx:.0f}" y1="{sy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" '
            f'stroke="#8a97a5" stroke-width="1.2" marker-end="url(#arrow)"/>'
        )
        if label:
            line_parts.append(
                f'<text x="{mx:.0f}" y="{my:.0f}" font-family="sans-serif" '
                f'font-size="9" fill="#5b6b7c">{label}</text>'
            )

    width = max_x + _PADDING
    height = max_y + _PADDING
    title = escape(str(diagram.get("Name") or ""))

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height:.0f}" '
        f'width="{width:.0f}" height="{height:.0f}">'
        "<defs><marker id=\"arrow\" markerWidth=\"8\" markerHeight=\"8\" refX=\"7\" refY=\"4\" "
        "orient=\"auto\"><path d=\"M0,0 L8,4 L0,8 z\" fill=\"#8a97a5\"/></marker></defs>"
        f'<rect x="0" y="0" width="{width:.0f}" height="{height:.0f}" fill="#ffffff"/>'
        f'<text x="8" y="14" font-family="sans-serif" font-size="11" fill="#9aa7b3">{title}'
        " (schematic reconstruction, not EA's own rendering)</text>"
        + "".join(line_parts)
        + "".join(svg_parts)
        + "</svg>"
    )
