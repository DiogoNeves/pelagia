# Pelagia

**Pelagia** (from Greek *pelagos*, meaning "sea") — A tool that gathers multiple Markdown files into a single PDF document, like streams flowing into the ocean.

This project provides a simple script that converts a folder of Markdown files into a **single PDF** with:
- Mermaid diagrams rendered
- Images embedded
- A Table of Contents (levels 1-3)
- Internal links between files preserved as PDF links
- A page break between each file

It works on macOS and is designed to be easy to run from anywhere later (e.g., add to your `PATH`).

## Step-by-step setup (macOS)

1) Install dependencies (one-time):
```
brew install pandoc tectonic node
npm i -g @mermaid-js/mermaid-cli
```

2) Make the script executable:
```
chmod +x pelagia.py
```

3) Run it:
```
./pelagia.py /path/to/folder --start README.md --out /path/to/output.pdf
```

Optional title:
```
./pelagia.py /path/to/folder --start README.md --out /path/to/output.pdf --title "My Docs"
```

Smaller diagrams or horizontal flow:
```
./pelagia.py /path/to/folder --start README.md --out /path/to/output.pdf \
  --mermaid-scale 0.8 --mermaid-flow-direction LR
```

You can also control diagram size directly:
```
./pelagia.py /path/to/folder --start README.md --out /path/to/output.pdf \
  --mermaid-width 640 --mermaid-height 480
```

## How it works

- All Markdown files under the target folder are collected.
- The list is rotated so `--start` comes first.
- Each file is inserted with a page break in between.
- Mermaid blocks (` ```mermaid `) are rendered via `mmdc` into PNGs.
- File-to-file links like `[text](other.md)` become internal PDF links.
- TOC is generated with depth 3, followed by a page break.

## Notes / assumptions

- Headings should use ATX syntax (`#`, `##`, `###`).
- Links to other files should be relative (e.g. `other.md` or `sub/other.md`).
- If a linked file is not in the folder, the link is left unchanged.

## Troubleshooting

- If Mermaid rendering fails, verify `mmdc` is on your PATH:
```
which mmdc
```
- If PDF generation fails, verify Pandoc and Tectonic:
```
which pandoc
which tectonic
```
