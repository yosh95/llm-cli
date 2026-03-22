# Makefile for Security Framework Research Paper
# Requires: TeX Live (pdflatex, latexmk)

LATEXMK = latexmk
LATEXMK_FLAGS = -pdf -interaction=nonstopmode -halt-on-error -cd

# Directories
PAPER_DIR = comprehensive_framework

# Source Files
PAPER_SRC = $(PAPER_DIR)/paper.tex
PAPER_DIAG = $(PAPER_DIR)/unified_architecture.tex $(PAPER_DIR)/detailed_architecture.tex

# Output Files
PAPER_PDF = $(PAPER_DIR)/paper.pdf

.PHONY: all clean help

all: $(PAPER_PDF) ## Compile the research paper

$(PAPER_PDF): $(PAPER_SRC) $(PAPER_DIAG)
	$(LATEXMK) $(LATEXMK_FLAGS) $(PAPER_SRC)

clean: ## Remove auxiliary files
	$(LATEXMK) -c -cd $(PAPER_SRC)

help: ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
