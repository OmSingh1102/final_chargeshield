"""The evidence-requirements matrix: which dispute type needs which information.

Transcribed 2026-09-01 from the management workbook "Dummy data (3).xlsx" —
Sheet3 (the matrix) and Sheet4 (the database legend). This module is the audit
trail for where the Evidence Requirements page gets every cell: if the workbook
is revised, re-dump it and update here; nothing else in the app carries a copy.

How the sheet was read, because none of it is written down in the workbook:

- A red fill (FF0000) in the Required-information column marks PRIMARY
  evidence; unfilled rows are secondary. The red is only ever applied in the
  main column, so an item repeated in a variant column inherits its flag.
- Columns H-K are TRUE where Database I-IV can supply the item; L/M are the
  System/Manual fetch flags. A row with neither flag is carried as method
  None and rendered as an em dash — four rows are like that in the workbook,
  and defaulting them would be inventing an answer.
- "Goods not received" has five scenario columns (delivered / in transit /
  lost in transit / awaiting collection / return to sender) whose header row
  sits one band above it in the sheet. Items list which variants they apply
  to; `variants_for` omitted means all five.
- The flags are transcribed AS THE SHEET HAS THEM, even where they disagree
  with the legend (Goods-not-received sources Order information from
  Database III though the legend files it under I; Proof of delivery is
  System there but Manual in sections 3 and 4). This page shows the
  manager's sheet, not our corrections of it.
- Sheet4's typos are cleaned in display text only ("IP informaiton",
  "Order detailed descritpion", and a duplicated "Refund information" row).

`reason_families` keys into REASON_CODES (reason_code.py), so each section can
show the network codes it governs. Live families 11.3, 13.2 and 12.6.2 have no
row in the workbook — that is the sheet's scope, not a gap introduced here.
"""

# The four backend systems the matrix draws from, as Sheet4 names them.
DATABASES = {
    "I": {
        "name": "Database I",
        "focus": "Order information",
        "holds": ["Refund information", "Order information", "Invoice Breakup",
                  "Communication history", "Logistics information",
                  "Order detailed description", "Return information"],
    },
    "II": {
        "name": "Database II",
        "focus": "Transaction details",
        "holds": ["Transaction history", "IP information",
                  "Customer information (name and address)", "Geo location"],
    },
    "III": {
        # Sheet4 gives III and IV no focus line; these two are editorial,
        # written from what the columns hold.
        "name": "Database III",
        "focus": "Payment, account & policy records",
        "holds": ["Payment history", "Binding history", "Account history",
                  "3DS Secure", "Introduction", "Terms and conditions",
                  "Refund policy"],
    },
    "IV": {
        "name": "Database IV",
        "focus": "Fulfilment proof",
        "holds": ["Proof of delivery"],
    },
}

EVIDENCE_MATRIX = [
    {
        "num": 1,
        "labels": ["Unauthorized transactions"],
        "reason_families": ["10.3", "10.4"],
        "items": [
            {"name": "3D Secure",             "primary": True,  "sources": ["III"],      "method": "system"},
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Account history",       "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Binding history",       "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Payment history",       "primary": False, "sources": ["III"],      "method": "manual"},
            {"name": "Geo location",          "primary": False, "sources": ["II"],       "method": None},
            {"name": "Undisputed transaction", "primary": True, "sources": ["II"],       "method": None},
            {"name": "Highlight the disputed transaction",
                                              "primary": False, "sources": ["II"],       "method": None},
        ],
    },
    {
        "num": 2,
        "labels": ["Goods not received"],
        "reason_families": ["13.1"],
        "variants": ["If item delivered", "If item in transit", "If item lost in transit",
                     "If item awaiting collection", "If item returned to sender"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "manual",
             "variants_for": ["If item delivered", "If item in transit", "If item lost in transit"]},
            {"name": "Proof of delivery",     "primary": True,  "sources": ["IV"],       "method": "system",
             "variants_for": ["If item delivered"]},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": None},
        ],
    },
    {
        "num": 3,
        "labels": ["Product Unacceptable", "Product Unsatisfactory",
                   "Merchant not as described", "Return merchandise"],
        "reason_families": ["13.3"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information / product detailed description",
                                              "primary": True,  "sources": ["I"],        "method": "manual"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Proof of delivery",     "primary": False, "sources": ["IV"],       "method": "manual"},
            {"name": "Return information",    "primary": True,  "sources": ["I"],        "method": "system"},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": "system"},
        ],
    },
    {
        "num": 4,
        "labels": ["Credit not Processed"],
        "reason_families": ["13.6"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Proof of delivery",     "primary": False, "sources": ["IV"],       "method": "manual"},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": "manual"},
            {"name": "Reason for not giving the credit",
                                              "primary": True,  "sources": ["III"],      "method": None},
        ],
    },
    {
        "num": 5,
        "labels": ["Duplicate payment"],
        "reason_families": ["12.6.1"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Two transaction details showing two different timestamps",
                                              "primary": True,  "sources": ["II"],       "method": "manual"},
        ],
    },
    {
        "num": 6,
        "labels": ["Incorrect amount"],
        "reason_families": ["12.5"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Invoice Breakup",       "primary": True,  "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": "system"},
        ],
    },
    {
        "num": 7,
        "labels": ["Cancelled Merchandise"],
        "reason_families": ["13.7"],
        "items": [
            {"name": "Refund information",    "primary": True,  "sources": ["I", "III"], "method": "system"},
            {"name": "Order information",     "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Invoice Breakup",       "primary": False, "sources": ["I"],        "method": "system"},
            {"name": "Communication history", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Logistics information", "primary": False, "sources": ["I"],        "method": "manual"},
            {"name": "Cancellation policy",   "primary": True,  "sources": ["III"],      "method": "system"},
            {"name": "Terms and conditions",  "primary": False, "sources": ["III"],      "method": "system"},
            {"name": "Refund policy",         "primary": False, "sources": ["III"],      "method": "system"},
        ],
    },
]

# Reason family -> its section, so a live case resolves straight to its
# requirements. Derivable only because the families are disjoint across
# sections — if a family is ever listed under two sections, this silently
# keeps the later one, so the assertion makes that mistake loud instead.
SECTION_BY_FAMILY = {fam: sec for sec in EVIDENCE_MATRIX
                     for fam in sec["reason_families"]}
assert len(SECTION_BY_FAMILY) == sum(len(s["reason_families"]) for s in EVIDENCE_MATRIX), \
    "a reason family appears in two EVIDENCE_MATRIX sections"
