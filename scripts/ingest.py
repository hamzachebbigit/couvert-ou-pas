"""Ingestion d'un contrat : PDF → clauses.json, table_rows.json.

    python scripts/ingest.py axa_optihome_2025
    python scripts/ingest.py --all

Le PDF doit être dans data/sources/ (scripts/fetch_sources.py). Docling lit
les tableaux une fois et son résultat est gardé dans data/parsed/<id>/docling.json,
qui n'est pas versionné. Les fichiers versionnés sont clauses.json et
table_rows.json, ce qui permet à l'application de tourner depuis un clone sans
relire les PDF.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.pipeline.parse import parse_contract  # noqa: E402


def run_docling(pdf: Path, target: Path) -> None:
    """Convertit le PDF avec Docling et enregistre le document au format JSON."""
    from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # Les trois contrats ont une couche texte : pas d'OCR. Le moteur pdfium lit les trois
    # sans incident, le moteur par défaut s'arrêtait net sur l'un d'eux.
    options = PdfPipelineOptions(do_ocr=False, do_table_structure=True)
    converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options, backend=PyPdfiumDocumentBackend)})
    result = converter.convert(str(pdf))
    target.write_text(json.dumps(result.document.export_to_dict(), ensure_ascii=False), encoding="utf-8")


def ingest(contract_id: str, with_docling: bool) -> None:
    pdf = ROOT / "data" / "sources" / f"{contract_id}.pdf"
    if not pdf.exists():
        raise SystemExit(f"PDF absent : {pdf}. Lancez scripts/fetch_sources.py d'abord.")
    out = ROOT / "data" / "parsed" / contract_id
    out.mkdir(parents=True, exist_ok=True)
    docling_json = out / "docling.json"
    if with_docling and not docling_json.exists():
        print(f"Docling sur {contract_id} (quelques minutes)…")
        run_docling(pdf, docling_json)
    clauses, rows = parse_contract(contract_id, pdf, docling_json if docling_json.exists() else None)
    (out / "clauses.json").write_text(
        json.dumps([c.model_dump() for c in clauses], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (out / "table_rows.json").write_text(
        json.dumps([r.model_dump() for r in rows], ensure_ascii=False, indent=1), encoding="utf-8"
    )
    with_text = sum(1 for c in clauses if c.text)
    print(f"{contract_id} : {len(clauses)} clauses ({with_text} avec texte), {len(rows)} rangées de tableau")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("contract_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--no-docling", action="store_true", help="ne pas lancer Docling si docling.json manque")
    args = parser.parse_args()
    sources = json.loads((ROOT / "data" / "sources.json").read_text(encoding="utf-8"))["contracts"]
    ids = [c["id"] for c in sources] if args.all else [args.contract_id]
    if not ids or ids == [None]:
        parser.error("indiquez un identifiant de contrat ou --all")
    for contract_id in ids:
        ingest(contract_id, with_docling=not args.no_docling)


if __name__ == "__main__":
    main()
