import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


def _build_demo_pdf(title: str) -> bytes:
    """Build a small but structurally valid single-page PDF (correct xref
    offsets) showing the document reference — good enough for the DATEV
    Belegbilderservice demo uploads."""
    text = title.replace("(", "").replace(")", "").replace("\\", "")
    stream = f"BT /F1 24 Tf 72 770 Td ({text}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[3 0 R]/Count 1>>",
        b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]" b"/Resources<</Font<</F1 5 0 R>>>>/Contents 4 0 R>>",
        b"<</Length %d>>stream\n%s\nendstream" % (len(stream) + 1, stream),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for index, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj" % index + body + b"endobj\n"
    xref_pos = len(out)
    out += b"xref\n0 %d\n" % (len(objects) + 1)
    out += b"0000000000 65535 f \n"
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref_pos)
    return bytes(out)


class ResCompany(models.Model):
    _inherit = "res.company"

    datev_service_documents = fields.Boolean(
        string="DATEV Belegbilderservice",
        help="Überträgt Belegbilder (z. B. Rechnungs-PDFs) vor dem "
        "Buchungsstapel nach DATEV Unternehmen online und verknüpft sie "
        "über den Beleglink (BEDI-GUID). Fragt die Scopes "
        "accounting:documents und accounting:clients:read an. Der "
        "Belegbilderservice muss beim Steuerberater/DATEV bestellt und "
        "aktiviert sein: http://go.datev.de/datenservices-einrichten",
    )

    def datev_get_additional_scopes(self):
        scopes = super().datev_get_additional_scopes()
        if self.datev_service_documents:
            # Wire names per the accounting-documents OpenAPI securitySchemes:
            # unlike extf-files/accounting-clients these have NO 'datev:'
            # prefix. accounting:clients:read is required by the API's own
            # GET /clients/{client-id} authorization check.
            scopes += ["accounting:documents", "accounting:clients:read"]
        return scopes

    # ------------------------------------------------------------------
    # Demo data (called via <function> from demo/datev_documents_demo.xml)
    # ------------------------------------------------------------------

    @api.model
    def _datev_load_documents_demo(self):
        """Attach a demo voucher PDF to every accounting demo document of the
        sandbox company 455148-1 (builds on _datev_load_accounting_demo).
        Idempotent: moves that already carry a main attachment are skipped."""
        company = self.env.ref("datev_connector.company_datev_sandbox_1", raise_if_not_found=False)
        if not company:
            return
        company.datev_service_documents = True
        moves = (
            self.env["account.move"]
            .sudo()
            .search(
                [
                    ("company_id", "=", company.id),
                    ("ref", "=like", "DEMO-DATEV-%"),
                ]
            )
        )
        attached = 0
        for move in moves:
            if move.message_main_attachment_id:
                continue
            attachment = (
                self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": f"{move.ref}.pdf",
                        "raw": _build_demo_pdf(f"Demo-Beleg {move.ref}"),
                        "mimetype": "application/pdf",
                        "res_model": "account.move",
                        "res_id": move.id,
                        "company_id": company.id,
                    }
                )
            )
            move.message_main_attachment_id = attachment
            attached += 1
        if attached:
            _logger.info("DATEV demo: %d voucher PDFs attached to demo documents.", attached)
