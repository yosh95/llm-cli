# Makefile for Security Trilogy Technical Reports
# Requires: TeX Live (pdflatex, latexmk)

LATEXMK = latexmk
LATEXMK_FLAGS = -pdf -interaction=nonstopmode -halt-on-error -cd

# Phases
PHASE1_DIR = guardrail
PHASE2_DIR = zero_trust
PHASE3_DIR = pqc

# Source Files
PHASE1_SRC = $(PHASE1_DIR)/trilogy_phase1_structural_guardrails.tex
PHASE2_SRC = $(PHASE2_DIR)/trilogy_phase2_behavioral_zero_trust.tex
PHASE3_SRC = $(PHASE3_DIR)/trilogy_phase3_temporal_pqc.tex

# Diagrams (Dependencies)
PHASE1_DIAG = $(PHASE1_DIR)/trilogy_phase1_architecture.tex
PHASE2_DIAG = $(PHASE2_DIR)/trilogy_phase2_architecture.tex
PHASE3_DIAG = $(PHASE3_DIR)/trilogy_phase3_architecture.tex

# Output Files
PHASE1_PDF = $(PHASE1_DIR)/trilogy_phase1_structural_guardrails.pdf
PHASE2_PDF = $(PHASE2_DIR)/trilogy_phase2_behavioral_zero_trust.pdf
PHASE3_PDF = $(PHASE3_DIR)/trilogy_phase3_temporal_pqc.pdf

ALL_PDFS = $(PHASE1_PDF) $(PHASE2_PDF) $(PHASE3_PDF)

.PHONY: all phase1 phase2 phase3 clean help

all: $(ALL_PDFS) ## Compile all phases of the Security Trilogy

phase1: $(PHASE1_PDF) ## Compile Phase 1: Structural Guardrails

phase2: $(PHASE2_PDF) ## Compile Phase 2: Behavioral Zero Trust

phase3: $(PHASE3_PDF) ## Compile Phase 3: Temporal PQC

$(PHASE1_PDF): $(PHASE1_SRC) $(PHASE1_DIAG)
	$(LATEXMK) $(LATEXMK_FLAGS) $(PHASE1_SRC)

$(PHASE2_PDF): $(PHASE2_SRC) $(PHASE2_DIAG)
	$(LATEXMK) $(LATEXMK_FLAGS) $(PHASE2_SRC)

$(PHASE3_PDF): $(PHASE3_SRC) $(PHASE3_DIAG)
	$(LATEXMK) $(LATEXMK_FLAGS) $(PHASE3_SRC)

clean: ## Remove auxiliary and output files
	$(LATEXMK) -C -cd $(PHASE1_SRC)
	$(LATEXMK) -C -cd $(PHASE2_SRC)
	$(LATEXMK) -C -cd $(PHASE3_SRC)
	rm -f $(PHASE1_DIR)/*.pdf $(PHASE2_DIR)/*.pdf $(PHASE3_DIR)/*.pdf

help: ## Show this help message
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
