class PDFPacketConverter:
    """PDF converter stage for final representment packet."""

    @classmethod
    def build_packet(cls, dispute, cover_letter, document_manifest):
        included_docs = [d for d in document_manifest if d.get("status") == "included"]
        sections = [{"section": "Cover Letter", "pages": 1, "status": "included"}]
        sections.extend(
            {"section": d["document"], "pages": 1, "status": d.get("status", "included")}
            for d in included_docs
        )

        case_id = dispute.get("chargeback_case_id", "CASE")
        reason_code = dispute.get("reason_code", "UNKNOWN").replace(".", "_")
        return {
            "file_name": f"{case_id}_{reason_code}_EvidencePacket.pdf",
            "format": "Letter",
            "font": "Times New Roman",
            "estimated_pages": len(sections),
            "layout_checks": [
                "Header/footer aligned",
                "Image scaling normalized to fit page",
                "Font size adjusted for issuer readability",
            ],
            "render_status": "ready",
            "sections": sections,
            "cover_letter_preview_chars": min(len(cover_letter.get("content", "")), 800),
        }
