"""Pretty-print / canonicalize structured text formats."""

import json
import xml.dom.minidom


def pretty_json(text: str) -> str:
    """Canonical pretty form: sorted keys, 2-space indent."""
    return json.dumps(json.loads(text), indent=2, sort_keys=True, ensure_ascii=False)


def pretty_xml(text: str) -> str:
    """Pretty form with normalized whitespace, 2-space indent."""
    dom = xml.dom.minidom.parseString(text)
    _strip_whitespace_nodes(dom)
    pretty = dom.toprettyxml(indent="  ")
    # toprettyxml emits a declaration line and occasional blank lines; keep it tidy
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join(lines)


def _strip_whitespace_nodes(node) -> None:
    """Remove whitespace-only text nodes so re-indenting is stable."""
    for child in list(node.childNodes):
        if child.nodeType == child.TEXT_NODE and not child.data.strip():
            node.removeChild(child)
        elif child.hasChildNodes():
            _strip_whitespace_nodes(child)


PRETTY_FORMATTERS = {
    ".json": pretty_json,
    ".xml": pretty_xml,
}
