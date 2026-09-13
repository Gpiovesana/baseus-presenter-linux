#!/usr/bin/env python3
"""Extract tr() messages into Qt Linguist catalogs; optionally compile with lrelease."""
import argparse
import ast
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", action="store_true")
    parser.add_argument("--lrelease", default="lrelease")
    args = parser.parse_args()
    sources = set()
    for path in (ROOT / "app").glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "tr" and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                sources.add(node.args[0].value)
    for language in ("pt", "en"):
        path = ROOT / "app/translations" / f"baseus_{language}.ts"
        tree = ET.parse(path)
        context = tree.getroot().find("context")
        existing = {message.findtext("source") for message in context.findall("message")}
        for source in sorted(sources - existing):
            message = ET.SubElement(context, "message")
            ET.SubElement(message, "source").text = source
            translated = ET.SubElement(message, "translation")
            if language == "pt":
                translated.text = source
            else:
                translated.set("type", "unfinished")
        ET.indent(tree)
        tree.write(path, encoding="utf-8", xml_declaration=True)
        if args.compile:
            executable = shutil.which(args.lrelease)
            if not executable:
                parser.error("lrelease was not found; install qttools5-dev-tools or pass --lrelease PATH")
            subprocess.run([executable, str(path)], check=True)


if __name__ == "__main__":
    main()
