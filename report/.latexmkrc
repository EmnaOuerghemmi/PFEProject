# Compilation reproductible du rapport PIQBIT.
#   latexmk -pdf main.tex
#
# Moteur et processeur bibliographique à réconcilier avec le gabarit officiel
# (M-03, M-07) : si celui-ci impose une autre chaîne, elle prime.
$pdf_mode = 1;              # pdflatex
$bibtex_use = 2;
$biber = 'biber %O %S';
$clean_ext = 'bbl bcf run.xml synctex.gz fdb_latexmk fls lof lot mtc* out';
