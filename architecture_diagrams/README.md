# Architecture Diagram Source

This directory contains the TikZ source code for the `llm-cli` architecture diagram.

## Files
- `architecture.tex`: The main TikZ source file.

## How to Compile
To generate a PDF from the `.tex` file, you can use `pdflatex`:

```bash
pdflatex architecture.tex
```

Or using `latexmk`:

```bash
latexmk -pdf architecture.tex
```