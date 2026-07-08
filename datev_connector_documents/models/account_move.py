import logging
import uuid

from odoo import fields, models

_logger = logging.getLogger(__name__)

# Second repository level ("folder"/Belegart) in Belege online per move type.
_FOLDER_BY_MOVE_TYPE = {
    "out_invoice": "Rechnungsausgang",
    "out_refund": "Rechnungsausgang",
    "in_invoice": "Rechnungseingang",
    "in_refund": "Rechnungseingang",
}


class AccountMove(models.Model):
    _inherit = "account.move"

    datev_document_guid = fields.Char(
        string="DATEV Beleg-GUID",
        copy=False,
        readonly=True,
        help="RFC-4122-GUID des Belegbilds in DATEV Unternehmen online. Wird "
             "von Odoo erzeugt und im EXTF-Beleglink (BEDI) referenziert; "
             "ein erneuter Export erzeugt dadurch keine Dubletten.",
    )
    datev_document_uploaded_at = fields.Datetime(
        string="DATEV Belegbild übertragen am",
        copy=False,
        readonly=True,
    )

    def _datev_get_voucher_attachment(self):
        """The document to transfer: the move's main attachment
        (e.g. the received vendor bill PDF or the generated invoice PDF)."""
        self.ensure_one()
        return self.message_main_attachment_id

    def _datev_document_metadata(self):
        """Belege online repository levels — DATEV MUST: as soon as one level
        is used, all three (category/folder/register) must be filled."""
        self.ensure_one()
        return {
            "category": "Odoo",
            "folder": _FOLDER_BY_MOVE_TYPE.get(self.move_type, "Sonstige Belege"),
            "register": (self.date or fields.Date.today()).strftime("%Y/%m"),
            "note": (self.name or "")[:255],
        }

    def _datev_assign_document_guids(self):
        super()._datev_assign_document_guids()
        for move in self:
            company = (move.company_id or self.env.company).sudo()
            if not company.datev_service_documents or move.datev_document_guid:
                continue
            if move._datev_get_voucher_attachment():
                move.datev_document_guid = str(uuid.uuid4())

    def _datev_upload_documents(self, service, client_id):
        """Upload voucher images (before the EXTF file — DATEV order)."""
        super()._datev_upload_documents(service, client_id)
        for move in self:
            company = (move.company_id or self.env.company).sudo()
            if not company.datev_service_documents:
                continue
            attachment = move._datev_get_voucher_attachment()
            if not attachment:
                continue
            if not move.datev_document_guid:
                move.datev_document_guid = str(uuid.uuid4())
            if move.datev_document_uploaded_at:
                # Already transferred; the stable GUID would prevent a
                # duplicate on the DATEV side anyway.
                continue
            service.documents_upload(
                client_id,
                move.datev_document_guid,
                attachment.name or "Beleg.pdf",
                attachment.raw,
                move._datev_document_metadata(),
            )
            move.datev_document_uploaded_at = fields.Datetime.now()
            _logger.info(
                "DATEV Belegbild uploaded: move %s → GUID %s",
                move.name, move.datev_document_guid,
            )
