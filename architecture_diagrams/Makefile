.PHONY: all clean distclean

TARGET = architecture.pdf
PNG_TARGET = architecture.png
SOURCE = architecture.tex

all: $(TARGET) $(PNG_TARGET)

$(TARGET): $(SOURCE)
	latexmk $(SOURCE)

$(PNG_TARGET): $(TARGET)
	@if command -v pdftocairo > /dev/null; then \
		pdftocairo -png -singlefile $(TARGET) architecture; \
	elif command -v pdftoppm > /dev/null; then \
		pdftoppm -png -singlefile $(TARGET) architecture; \
	elif command -v convert > /dev/null; then \
		convert -density 300 $(TARGET) $(PNG_TARGET); \
	else \
		echo "Warning: No PDF to PNG converter found (pdftocairo, pdftoppm, or convert)"; \
	fi

clean:
	latexmk -c
	rm -f $(PNG_TARGET)

distclean:
	latexmk -C
	rm -f $(PNG_TARGET)
