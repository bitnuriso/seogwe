#!/data/data/com.termux/files/usr/bin/bash
set -e

pkg update
pkg install -y python
python -m pip install --upgrade pip
python -m pip install flask pymupdf

termux-setup-storage || true
mkdir -p "$HOME/storage/shared/PDFCrop/in"
mkdir -p "$HOME/storage/shared/PDFCrop/out"

echo
echo "설치 완료."
echo "PDF 입력 폴더: $HOME/storage/shared/PDFCrop/in"
echo "결과 폴더:     $HOME/storage/shared/PDFCrop/out"
echo "실행: python app.py"
