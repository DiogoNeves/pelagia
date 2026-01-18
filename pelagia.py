#!/usr/bin/env python3
import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Tuple

MERMAID_FENCE_RE = re.compile(r"^```mermaid\s*$", re.IGNORECASE)
FENCE_END_RE = re.compile(r"^```\s*$")
MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
ATX_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def die(msg: str, code: int = 2) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(code)


def which_or_die(cmd: str, install_hint: str) -> None:
    if shutil.which(cmd) is None:
        die(f"missing `{cmd}` in PATH. Install: {install_hint}")


def slugify(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"<[^>]+>", "", s)
    s = re.sub(r"[`*_~]", "", s)
    s = re.sub(r"[^a-z0-9\s\-]", "", s)
    s = re.sub(r"[\s\-]+", "-", s).strip("-")
    return s or "section"


def is_markdown(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in {".md", ".markdown"}


def safe_file_slug(root: Path, md_path: Path) -> str:
    rel = md_path.resolve().relative_to(root.resolve()).as_posix()
    base = slugify(rel.replace("/", " "))
    h = hashlib.sha1(rel.encode("utf-8")).hexdigest()[:8]
    return f"{base}-{h}"


def split_link_target(target: str) -> Tuple[str, str]:
    if "#" in target:
        a, b = target.split("#", 1)
        return a, b
    return target, ""


def looks_like_url(s: str) -> bool:
    return bool(re.match(r"^[a-zA-Z][a-zA-Z0-9+\-.]*://", s)) or s.startswith(
        "mailto:"
    )


def render_mermaid_blocks(
    md_text: str,
    diagrams_dir: Path,
    diagram_key_prefix: str,
    width: int,
    height: int,
    flow_direction: str | None,
) -> str:
    out_lines: List[str] = []
    lines = md_text.splitlines()
    i = 0
    mermaid_idx = 0

    while i < len(lines):
        line = lines[i]
        if MERMAID_FENCE_RE.match(line):
            i += 1
            block: List[str] = []
            while i < len(lines) and not FENCE_END_RE.match(lines[i]):
                block.append(lines[i])
                i += 1
            if i >= len(lines):
                die("unterminated ```mermaid block")
            i += 1

            mermaid_src = "\n".join(block).strip() + "\n"
            if flow_direction:
                mermaid_src = re.sub(
                    r"^(flowchart|graph)\s+[A-Z]{2}\b",
                    rf"\1 {flow_direction}",
                    mermaid_src,
                    flags=re.MULTILINE,
                )
            # Fix common mermaid syntax issues:
            # 1. Replace \n in node labels with space (Mermaid doesn't support line breaks)
            mermaid_src = re.sub(
                r"\\n\s*\(", r" (", mermaid_src
            )  # \n( -> space(
            mermaid_src = re.sub(r"\\n", " ", mermaid_src)  # other \n -> space

            # 2. Quote edge labels containing parentheses: -->|text (parens)| -> -->|"text (parens)"|
            def quote_edge_label(match):
                arrow = match.group(1)  # -->, --, etc.
                label = match.group(2)  # content between |
                if label.startswith('"') or not ("(" in label or ")" in label):
                    return match.group(0)
                return f'{arrow}|"{label}"|'

            mermaid_src = re.sub(
                r"(--+[->]?)\|([^|]+)\|", quote_edge_label, mermaid_src
            )

            # 3. Quote node labels containing parentheses: ID[text (parens)] -> ID["text (parens)"]
            def quote_node_label(match):
                prefix = match.group(1)  # ID or empty
                label = match.group(2)  # content inside []
                # Skip if already quoted
                if label.startswith('"'):
                    return match.group(0)
                # Quote if contains parentheses
                if "(" in label or ")" in label:
                    return f'{prefix}["{label}"]'
                return match.group(0)

            # Match: optional ID followed by [content]
            mermaid_src = re.sub(
                r"(\w+)?\[([^\]]+)\]", quote_node_label, mermaid_src
            )
            mermaid_hash = hashlib.sha1(
                mermaid_src.encode("utf-8")
            ).hexdigest()[:12]
            out_png = (
                diagrams_dir
                / f"mermaid-{diagram_key_prefix}-{mermaid_idx}-{mermaid_hash}.png"
            )
            in_mmd = (
                diagrams_dir
                / f"mermaid-{diagram_key_prefix}-{mermaid_idx}-{mermaid_hash}.mmd"
            )
            in_mmd.write_text(mermaid_src, encoding="utf-8")

            cmd = [
                "mmdc",
                "-i",
                str(in_mmd),
                "-o",
                str(out_png),
                "-w",
                str(width),
                "-H",
                str(height),
                "-b",
                "transparent",
            ]
            try:
                subprocess.run(
                    cmd,
                    check=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                print(
                    f"Warning: mermaid diagram {mermaid_idx} failed to render, skipping.\n"
                    f"Error: {e.stderr[:200]}",
                    file=sys.stderr,
                )
                # Insert a placeholder instead of failing
                out_lines.append(
                    "*[Mermaid diagram could not be rendered - check syntax]*"
                )
                mermaid_idx += 1
                continue

            out_lines.append(f"![]({out_png.as_posix()})")
            mermaid_idx += 1
            continue

        out_lines.append(line)
        i += 1

    return "\n".join(out_lines) + "\n"


def add_ids_and_rewrite_links(
    md_text: str,
    file_slug: str,
    file_slug_by_md_rel: Dict[str, str],
    folder_root: Path,
    current_file: Path,
) -> str:
    heading_counts: Dict[str, int] = {}

    def make_unique_id(base: str) -> str:
        n = heading_counts.get(base, 0) + 1
        heading_counts[base] = n
        return base if n == 1 else f"{base}-{n}"

    def rewrite_heading_line(line: str) -> str:
        m = ATX_HEADING_RE.match(line)
        if not m:
            return line
        hashes, title = m.group(1), m.group(2)
        if "{#" in title:
            return line
        clean_title = title.strip()
        base = f"{file_slug}-{slugify(clean_title)}"
        hid = make_unique_id(base)
        return f"{hashes} {clean_title} {{#{hid}}}"

    def rewrite_links(text: str) -> str:
        def repl(match: re.Match) -> str:
            label = match.group(1)
            target = match.group(2).strip()

            if looks_like_url(target):
                return match.group(0)

            path_part, frag = split_link_target(target)
            path_part = path_part.strip()

            # Skip empty paths or pure anchors
            if path_part == "" or path_part.startswith("#"):
                return match.group(0)

            # Only process markdown file links
            if not path_part.lower().endswith((".md", ".markdown")):
                return match.group(0)

            # Normalize path separators
            path_part_normalized = path_part.replace("\\", "/")

            # Try multiple strategies to find the matching file:
            # 1. Direct match (path is already relative to folder root)
            linked_slug = file_slug_by_md_rel.get(path_part_normalized)

            # 2. Try resolving relative to current file
            if not linked_slug and not Path(path_part).is_absolute():
                try:
                    resolved = (current_file.parent / path_part).resolve()
                    # Check if resolved path is within folder_root
                    try:
                        resolved_rel = resolved.relative_to(
                            folder_root.resolve()
                        ).as_posix()
                        linked_slug = file_slug_by_md_rel.get(resolved_rel)
                    except ValueError:
                        # Resolved path is outside folder_root, skip
                        pass
                except Exception:
                    pass

            # 3. Try with folder name prefix removed (handle cases like "thinking/file.md")
            if not linked_slug:
                # Remove leading folder name if it matches the folder name
                folder_name = folder_root.name
                if path_part_normalized.startswith(f"{folder_name}/"):
                    without_prefix = path_part_normalized[
                        len(folder_name) + 1 :
                    ]
                    linked_slug = file_slug_by_md_rel.get(without_prefix)

            # 4. Try just the filename if path has slashes
            if not linked_slug and "/" in path_part_normalized:
                filename = Path(path_part_normalized).name
                # Check if there's exactly one file with this name
                matching_files = [
                    rel
                    for rel in file_slug_by_md_rel.keys()
                    if Path(rel).name == filename
                ]
                if len(matching_files) == 1:
                    linked_slug = file_slug_by_md_rel.get(matching_files[0])

            # Convert to internal PDF link if we found a match
            if linked_slug:
                if frag:
                    frag_id = slugify(frag)
                    return f"[{label}](#{linked_slug}-{frag_id})"
                return f"[{label}](#{linked_slug})"

            # No match found, return original link
            return match.group(0)

        return MD_LINK_RE.sub(repl, text)

    lines = md_text.splitlines()
    out: List[str] = []
    out.append(f"[]{{#{file_slug}}}")
    out.append("")

    for line in lines:
        out.append(rewrite_heading_line(line))

    rewritten = "\n".join(out) + "\n"
    rewritten = rewrite_links(rewritten)
    return rewritten


def find_all_markdowns(folder: Path) -> List[Path]:
    files = [p for p in folder.rglob("*") if is_markdown(p)]
    return sorted(files, key=lambda p: p.as_posix().lower())


def rotate_start(files: List[Path], start: Path) -> List[Path]:
    start_res = start.resolve()
    for i, p in enumerate(files):
        if p.resolve() == start_res:
            return files[i:] + files[:i]
    die(f"start file not found in folder scan: {start}")
    return files


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a folder of Markdown files into one PDF (TOC, Mermaid, images, internal links)."
    )
    parser.add_argument("folder", help="Folder containing markdown files")
    parser.add_argument(
        "--start",
        required=True,
        help="Markdown file to start from (relative to folder, or absolute)",
    )
    parser.add_argument("--out", required=True, help="Output PDF path")
    parser.add_argument("--title", default="", help="Optional PDF title")
    parser.add_argument(
        "--mermaid-scale",
        type=float,
        default=1.0,
        help="Scale factor for Mermaid diagrams (default: 1.0)",
    )
    parser.add_argument(
        "--mermaid-width",
        type=int,
        default=800,
        help="Base Mermaid width in pixels (default: 800)",
    )
    parser.add_argument(
        "--mermaid-height",
        type=int,
        default=600,
        help="Base Mermaid height in pixels (default: 600)",
    )
    parser.add_argument(
        "--mermaid-flow-direction",
        choices=["TB", "TD", "BT", "RL", "LR"],
        default=None,
        help="Override Mermaid flowchart direction (e.g. LR for horizontal)",
    )
    args = parser.parse_args()

    which_or_die("pandoc", "brew install pandoc")
    which_or_die("tectonic", "brew install tectonic")
    which_or_die("mmdc", "npm i -g @mermaid-js/mermaid-cli")

    folder = Path(args.folder).expanduser().resolve()
    if not folder.is_dir():
        die(f"folder does not exist: {folder}")

    start_path = Path(args.start).expanduser()
    if not start_path.is_absolute():
        start_path = folder / start_path
    if not is_markdown(start_path):
        die(f"--start must be a markdown file: {start_path}")

    out_pdf = Path(args.out).expanduser().resolve()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)

    md_files = find_all_markdowns(folder)
    if not md_files:
        die(f"no markdown files found under: {folder}")

    md_files = rotate_start(md_files, start_path)

    file_slug_by_md_rel: Dict[str, str] = {}
    for p in md_files:
        rel = p.resolve().relative_to(folder).as_posix()
        file_slug_by_md_rel[rel] = safe_file_slug(folder, p)

    with tempfile.TemporaryDirectory(prefix="mdfolder2pdf-") as tmp:
        tmpdir = Path(tmp)
        diagrams_dir = tmpdir / "diagrams"
        diagrams_dir.mkdir(parents=True, exist_ok=True)

        combined_md = tmpdir / "combined.md"
        parts: List[str] = []

        for idx, md_path in enumerate(md_files):
            rel = md_path.resolve().relative_to(folder).as_posix()
            file_slug = file_slug_by_md_rel[rel]

            text = md_path.read_text(encoding="utf-8", errors="replace")
            scaled_width = max(1, int(args.mermaid_width * args.mermaid_scale))
            scaled_height = max(
                1, int(args.mermaid_height * args.mermaid_scale)
            )
            text = render_mermaid_blocks(
                text,
                diagrams_dir,
                diagram_key_prefix=file_slug,
                width=scaled_width,
                height=scaled_height,
                flow_direction=args.mermaid_flow_direction,
            )
            text = add_ids_and_rewrite_links(
                text,
                file_slug,
                file_slug_by_md_rel,
                folder,
                md_path,
            )

            if idx > 0:
                parts.append("\n```{=latex}\n\\newpage\n```\n")
            parts.append(text)

        combined_md.write_text("\n".join(parts), encoding="utf-8")

        resource_path = f"{folder.as_posix()}:{diagrams_dir.as_posix()}"

        header_tex = tmpdir / "header.tex"
        header_tex.write_text(
            "\\let\\oldtableofcontents\\tableofcontents\n"
            "\\renewcommand{\\tableofcontents}{%\n"
            "  \\oldtableofcontents\n"
            "  \\newpage\n"
            "}\n",
            encoding="utf-8",
        )

        cmd = [
            "pandoc",
            str(combined_md),
            "--pdf-engine=tectonic",
            f"--resource-path={resource_path}",
            "--toc",
            "--toc-depth=3",
            f"--include-in-header={header_tex}",
            "-V",
            "colorlinks=true",
            "-V",
            "linkcolor=blue",
            "-V",
            "urlcolor=blue",
            "-o",
            str(out_pdf),
        ]
        if args.title:
            cmd += ["-V", f"title={args.title}"]

        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            die(f"pandoc failed with exit code {e.returncode}")

    print(f"wrote: {out_pdf}")


if __name__ == "__main__":
    main()
