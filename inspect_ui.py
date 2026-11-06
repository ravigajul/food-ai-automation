#!/usr/bin/env python3
"""
UI Element Inspector — dumps the current Android screen's element tree via adb.

Usage:
  python inspect_ui.py                         # print all elements
  python inspect_ui.py --filter ASAP           # show elements whose text/desc contains keyword
  python inspect_ui.py --filter ASAP --class ImageView  # narrow by class
  python inspect_ui.py --clickable             # only clickable elements
  python inspect_ui.py --xml                   # print raw XML instead of table
  python inspect_ui.py --out /tmp/ui.xml       # also save raw XML to a file

Columns:  CLASS | CLICKABLE | TEXT | CONTENT-DESC | BOUNDS
"""

import argparse
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

DEVICE_XML = "/sdcard/ui_dump.xml"
LOCAL_XML  = "/tmp/ui_dump.xml"


def _adb(*args) -> subprocess.CompletedProcess:
    return subprocess.run(["adb", *args], capture_output=True, text=True)


def dump_ui() -> str:
    """Trigger uiautomator dump and return the XML string."""
    r = _adb("shell", "uiautomator", "dump", DEVICE_XML)
    if r.returncode != 0:
        print(f"adb dump failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    r = _adb("pull", DEVICE_XML, LOCAL_XML)
    if r.returncode != 0:
        print(f"adb pull failed: {r.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    return Path(LOCAL_XML).read_text(encoding="utf-8")


def _short_class(cls: str) -> str:
    """android.widget.ImageView → ImageView"""
    return cls.rsplit(".", 1)[-1] if "." in cls else cls


def _bounds(node) -> str:
    return node.get("bounds", "")


def parse_elements(xml_str: str) -> list[dict]:
    root = ET.fromstring(xml_str)
    elements = []
    for node in root.iter("node"):
        elements.append({
            "class":       node.get("class", ""),
            "text":        node.get("text", ""),
            "desc":        node.get("content-desc", ""),
            "clickable":   node.get("clickable", "false"),
            "bounds":      node.get("bounds", ""),
        })
    return elements


def apply_filters(elements: list[dict], keyword: str, cls_filter: str, clickable_only: bool) -> list[dict]:
    out = elements
    if clickable_only:
        out = [e for e in out if e["clickable"] == "true"]
    if cls_filter:
        out = [e for e in out if cls_filter.lower() in e["class"].lower()]
    if keyword:
        kw = keyword.lower()
        out = [e for e in out if kw in e["text"].lower() or kw in e["desc"].lower()]
    return out


def print_table(elements: list[dict]) -> None:
    if not elements:
        print("  (no elements matched)")
        return

    # Column widths
    CLS_W  = 22
    TEXT_W = 30
    DESC_W = 50

    header = (f"{'CLASS':<{CLS_W}}  {'CL':2}  {'TEXT':<{TEXT_W}}  {'CONTENT-DESC':<{DESC_W}}  BOUNDS")
    print(header)
    print("-" * len(header))

    for e in elements:
        cls  = _short_class(e["class"])[:CLS_W]
        cl   = "Y" if e["clickable"] == "true" else "."
        text = e["text"][:TEXT_W]
        desc = e["desc"][:DESC_W]
        print(f"{cls:<{CLS_W}}  {cl:2}  {text:<{TEXT_W}}  {desc:<{DESC_W}}  {e['bounds']}")


def main():
    ap = argparse.ArgumentParser(description="Dump current Android screen elements via adb")
    ap.add_argument("--filter",    metavar="KW",  help="Filter by text/content-desc containing KW")
    ap.add_argument("--class",     metavar="CLS", dest="cls", help="Filter by class name (e.g. ImageView)")
    ap.add_argument("--clickable", action="store_true", help="Show only clickable elements")
    ap.add_argument("--xml",       action="store_true", help="Print raw XML instead of table")
    ap.add_argument("--out",       metavar="PATH", help="Save raw XML to a file")
    args = ap.parse_args()

    print("  Dumping UI from device...", end=" ", flush=True)
    xml_str = dump_ui()
    print("done")

    if args.out:
        Path(args.out).write_text(xml_str, encoding="utf-8")
        print(f"  Saved XML → {args.out}")

    if args.xml:
        print(xml_str)
        return

    elements = parse_elements(xml_str)
    filtered = apply_filters(elements, args.filter, args.cls, args.clickable)

    total = len(elements)
    shown = len(filtered)
    label_parts = []
    if args.clickable:
        label_parts.append("clickable")
    if args.cls:
        label_parts.append(f"class={args.cls}")
    if args.filter:
        label_parts.append(f"filter='{args.filter}'")
    label = f"  [{shown}/{total} elements" + (f" — {', '.join(label_parts)}" if label_parts else "") + "]"
    print(label)
    print()
    print_table(filtered)


if __name__ == "__main__":
    main()
