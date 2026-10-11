"""DOCX -> PDF. Tries LibreOffice first, then Microsoft Word (Windows), else gives up quietly."""
import os, shutil, subprocess, sys
from pathlib import Path

SOFFICE = [shutil.which("soffice"), shutil.which("libreoffice"),
           r"C:\Program Files\LibreOffice\program\soffice.exe",
           r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"]


def to_pdf(docx_path):
    docx_path = Path(docx_path)
    out = docx_path.with_suffix(".pdf")
    for exe in SOFFICE:
        if exe and Path(exe).exists():
            try:
                subprocess.run([exe, "--headless", "--convert-to", "pdf", "--outdir", str(docx_path.parent),
                                str(docx_path)], check=True, timeout=120,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                if out.exists():
                    return str(out)
            except Exception:
                pass
    if sys.platform == "win32":
        ps = (
            "$w = New-Object -ComObject Word.Application; $w.Visible = $false; "
            f"$d = $w.Documents.Open('{docx_path}'); $d.SaveAs([ref] '{out}', [ref] 17); "
            "$d.Close(); $w.Quit()")
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True, timeout=180,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if out.exists():
                return str(out)
        except Exception:
            pass
    return None


def available():
    if any(e and Path(e).exists() for e in SOFFICE):
        return "LibreOffice"
    if sys.platform == "win32":
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "[bool](Get-ItemProperty 'HKLM:\\SOFTWARE\\Classes\\Word.Application' -ErrorAction SilentlyContinue)"],
                               capture_output=True, text=True, timeout=20)
            if "True" in r.stdout:
                return "Microsoft Word"
        except Exception:
            pass
    return None
