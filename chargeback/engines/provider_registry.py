"""Provider registry for the credential vault.

Transcribed by machine from Case Investigator's
src/lib/credentials/provider-credential-schemas.ts and the four
src/lib/integrations/*-registry.ts files (evidence-matrix style: the generator
lives in the session scratchpad, and the transcription asserts on shape before
writing). ChargeShield-specific entries — providers already in this app's
chooser lists or present in the demo book — are appended under each family and
marked verified=False, falling back to GENERIC_SCHEMA.

Pure data plus lookup helpers. Nothing here fetches anything: a saved
credential means credentials are on file, never that data was retrieved —
the same line the evidence pages draw.

Field secrecy is PER SCHEMA, not global: FedEx's apiKey is a plain client key
while DHL's apiKey is the secret itself. Callers must resolve secrecy through
secret_fields_for()/is_secret_field(), never through a global name set.
"""

from collections import OrderedDict


# The five tabs, keyed by ChargeShield's existing CREDENTIAL_PANELS keys —
# the storage layer, _client_connections and DATABASE_CONNECTORS all keep
# working against the same panel names. "other" maps to no database.
CATEGORY_ORDER = OrderedDict([
    ("gateway",   {"label": "Payment / Gateway",
                   "description": "Authorization, AVS/CVV results and transaction lookups"}),
    ("processor", {"label": "Processor",
                   "description": "Dispute details, chargeback records and settlement data"}),
    ("crm",       {"label": "CRM",
                   "description": "Order, customer and communication history"}),
    ("shipment",  {"label": "Shipping / Fulfillment",
                   "description": "Tracking, delivery confirmation and proof of delivery"}),
    ("other",     {"label": "Other / Custom API",
                   "description": "Any additional system exposing an HTTP API"}),
])

# The legacy field set, and the schema every unverified provider falls back to.
GENERIC_SCHEMA = {
    "environments": None,
    "environment_note": None,
    "source": ("Generic credential set — this provider's own credential model "
               "has not been verified against its documentation yet."),
    "fields": [
        {"key": "url", "label": "Portal / API URL", "type": "text",
         "secret": False, "required": False,
         "placeholder": "https://…",
         "description": "Where this system is reached."},
        {"key": "login_id", "label": "Login ID", "type": "text",
         "secret": False, "required": False,
         "description": "The account used to sign in."},
        {"key": "password", "label": "Password", "type": "password",
         "secret": True, "required": False,
         "description": "Stored encrypted; never displayed after saving."},
        {"key": "api_key", "label": "API Key", "type": "password",
         "secret": True, "required": False,
         "description": "Stored encrypted; never displayed after saving."},
    ],
}

# Providers per panel. verified=False -> GENERIC_SCHEMA + pending note.
PROVIDERS = {
    "gateway": [
        {"adapter": "stripe", "name": "Stripe", "verified": True},
        {"adapter": "adyen", "name": "Adyen", "verified": True},
        {"adapter": "braintree", "name": "Braintree", "verified": True},
        {"adapter": "authorize_net", "name": "Authorize.net", "verified": True},
        {"adapter": "cybersource", "name": "Cybersource", "verified": True},
        {"adapter": "nmi", "name": "NMI", "verified": True},
        {"adapter": "paypal", "name": "PayPal", "verified": True},
        {"adapter": "checkout_com", "name": "Checkout.com", "verified": True},
    ],
    "processor": [
        {"adapter": "stripe", "name": "Stripe", "verified": True},
        {"adapter": "adyen", "name": "Adyen", "verified": True},
        {"adapter": "braintree", "name": "Braintree", "verified": True},
        {"adapter": "paypal", "name": "PayPal", "verified": True},
        {"adapter": "worldpay", "name": "Worldpay", "verified": False},
        {"adapter": "chase_paymentech", "name": "Chase Paymentech", "verified": False},
        {"adapter": "first_data", "name": "First Data", "verified": False},
        {"adapter": "nuvei", "name": "Nuvei", "verified": False},
        {"adapter": "payu", "name": "PayU", "verified": False},
    ],
    "crm": [
        {"adapter": "shopify", "name": "Shopify", "verified": True},
        {"adapter": "zendesk", "name": "Zendesk", "verified": True},
        {"adapter": "salesforce", "name": "Salesforce", "verified": False},
        {"adapter": "hubspot", "name": "HubSpot", "verified": False},
        {"adapter": "konnektive", "name": "Konnektive CRM", "verified": False},
        {"adapter": "sticky_io", "name": "Sticky.io", "verified": False},
        {"adapter": "response_crm", "name": "Response CRM", "verified": False},
        {"adapter": "checkout_champ", "name": "Checkout Champ", "verified": False},
    ],
    "shipment": [
        {"adapter": "fedex", "name": "FedEx", "verified": True},
        {"adapter": "ups", "name": "UPS", "verified": True},
        {"adapter": "usps", "name": "USPS", "verified": True},
        {"adapter": "dhl", "name": "DHL", "verified": True},
        {"adapter": "ontrac", "name": "OnTrac", "verified": False},
        {"adapter": "blue_dart", "name": "Blue Dart", "verified": False},
        {"adapter": "dhl_express", "name": "DHL Express", "verified": False},
        {"adapter": "gig_logistics", "name": "GIG Logistics", "verified": False},
        {"adapter": "aramex", "name": "Aramex", "verified": False},
        {"adapter": "jt_express", "name": "J&T Express", "verified": False},
        {"adapter": "dpd", "name": "DPD", "verified": False},
        {"adapter": "royal_mail", "name": "Royal Mail", "verified": False},
    ],
    "other": [
        {"adapter": "custom_api", "name": "Custom API", "verified": True},
    ],
}

# Why an unverified provider shows generic fields, in its own words.
PENDING_NOTES = {
    "worldpay": "Credential model not yet verified against Worldpay documentation.",
    "chase_paymentech": "Credential model not yet verified against Chase Paymentech documentation.",
    "first_data": "Credential model not yet verified against Fiserv/First Data documentation.",
    "salesforce": "Credential model not yet verified against Salesforce Connected App documentation.",
    "hubspot": "Credential model not yet verified against HubSpot private-app documentation.",
    "ontrac": "Credential model not yet verified against OnTrac documentation."
}

# The 15 verified schemas, verbatim from the Case Investigator source.
SCHEMAS = {
    "stripe": {
        "environments": None,
        "environment_note": "Stripe has no environment switch — a test key (sk_test_…) and a live key (sk_live_…) select the mode.",
        "source": "Stripe API docs: server-side requests authenticate with a secret API key; the key prefix determines test vs live.",
        "fields": [
            {
                "key": "secretKey",
                "label": "Secret API Key",
                "type": "password",
                "secret": True,
                "required": True,
                "placeholder": "sk_live_… or sk_test_…",
                "description": "Server-side credential used to authenticate API requests."
            },
            {
                "key": "webhookSecret",
                "label": "Webhook Signing Secret",
                "type": "password",
                "secret": True,
                "required": False,
                "placeholder": "whsec_…",
                "description": "Optional. Only needed if dispute webhooks are delivered to us."
            }
        ]
    },
    "adyen": {
        "environments": [
            [
                "test",
                "Test"
            ],
            [
                "live",
                "Live"
            ]
        ],
        "environment_note": None,
        "source": "Adyen API credentials: a web-service user (ws@Company.…) with an API key, scoped to a merchant account; live traffic additionally requires the account's live endpoint prefix.",
        "fields": [
            {
                "key": "apiUsername",
                "label": "API Username",
                "type": "text",
                "secret": False,
                "required": True,
                "placeholder": "ws@Company.YourCompany",
                "description": "The web-service user created in the Adyen Customer Area."
            },
            {
                "key": "apiKey",
                "label": "API Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential generated for that API user."
            },
            {
                "key": "merchantAccount",
                "label": "Merchant Account",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "The merchant account the API user is scoped to."
            },
            {
                "key": "liveEndpointPrefix",
                "label": "Live Endpoint Prefix",
                "type": "text",
                "secret": False,
                "required": False,
                "description": "Required for Live only — the account-specific URL prefix Adyen issues."
            }
        ]
    },
    "braintree": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "Braintree server SDK authentication: environment, merchant ID, public key and private key.",
        "fields": [
            {
                "key": "merchantId",
                "label": "Merchant ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Identifies your Braintree gateway account."
            },
            {
                "key": "publicKey",
                "label": "Public Key",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Paired with the private key to authenticate API calls."
            },
            {
                "key": "privateKey",
                "label": "Private Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential. Never share or embed in client code."
            }
        ]
    },
    "paypal": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "live",
                "Live"
            ]
        ],
        "environment_note": None,
        "source": "PayPal REST API: OAuth 2.0 client credentials — a Client ID and Client Secret issued per app, per environment.",
        "fields": [
            {
                "key": "clientId",
                "label": "Client ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Issued with your PayPal REST app for the selected environment."
            },
            {
                "key": "clientSecret",
                "label": "Client Secret",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential exchanged for an OAuth access token."
            }
        ]
    },
    "nmi": {
        "environments": None,
        "environment_note": "NMI does not use a sandbox toggle — a separate test account issues its own security key.",
        "source": "NMI Payment API: requests authenticate with a Security Key. Private keys are used server-to-server; public keys are used only for Collect.js tokenization.",
        "fields": [
            {
                "key": "securityKey",
                "label": "API Security Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential used to authenticate Payment API requests."
            },
            {
                "key": "keyType",
                "label": "Key Type",
                "type": "select",
                "secret": False,
                "required": True,
                "description": "Which permission level this key was issued with.",
                "options": [
                    [
                        "private",
                        "Private (server-to-server)"
                    ],
                    [
                        "public",
                        "Public (Collect.js tokenization)"
                    ]
                ]
            }
        ]
    },
    "checkout_com": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "Checkout.com API: server requests authenticate with a secret key (sk_…); the public key (pk_…) is only used for client-side tokenization.",
        "fields": [
            {
                "key": "secretKey",
                "label": "Secret API Key",
                "type": "password",
                "secret": True,
                "required": True,
                "placeholder": "sk_…",
                "description": "Server-side credential used to authenticate API requests."
            },
            {
                "key": "publicKey",
                "label": "Public Key",
                "type": "text",
                "secret": False,
                "required": False,
                "placeholder": "pk_…",
                "description": "Optional. Only needed if client-side tokenization is used."
            }
        ]
    },
    "authorize_net": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "Authorize.net API authentication: API Login ID plus Transaction Key; a Signature Key is used to verify webhooks.",
        "fields": [
            {
                "key": "apiLoginId",
                "label": "API Login ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Identifies your Authorize.net account for API calls."
            },
            {
                "key": "transactionKey",
                "label": "Transaction Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential paired with the API Login ID."
            },
            {
                "key": "signatureKey",
                "label": "Signature Key",
                "type": "password",
                "secret": True,
                "required": False,
                "description": "Optional. Used to verify the authenticity of webhook notifications."
            }
        ]
    },
    "cybersource": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "Cybersource REST API: HTTP Signature authentication using a merchant ID with a REST API key ID and its shared secret key.",
        "fields": [
            {
                "key": "merchantId",
                "label": "Merchant ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Your Cybersource merchant identifier."
            },
            {
                "key": "keyId",
                "label": "REST API Key ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Identifier of the REST shared-secret key pair."
            },
            {
                "key": "sharedSecret",
                "label": "Shared Secret Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential used to sign API requests."
            }
        ]
    },
    "shopify": {
        "environments": None,
        "environment_note": "Shopify credentials are issued per store, so the shop domain selects the account.",
        "source": "Shopify Admin API: a custom app installed on a store issues an Admin API access token, used with the store's myshopify domain.",
        "fields": [
            {
                "key": "shopDomain",
                "label": "Shop Domain",
                "type": "text",
                "secret": False,
                "required": True,
                "placeholder": "your-store.myshopify.com",
                "description": "The store this token was issued for."
            },
            {
                "key": "adminAccessToken",
                "label": "Admin API Access Token",
                "type": "password",
                "secret": True,
                "required": True,
                "placeholder": "shpat_…",
                "description": "Server-side credential for Admin API order and customer lookups."
            }
        ]
    },
    "zendesk": {
        "environments": None,
        "environment_note": "Zendesk credentials are per subdomain; there is no separate sandbox toggle.",
        "source": "Zendesk API: API-token authentication uses the account subdomain with an agent email in the form {email}/token and the API token as the password.",
        "fields": [
            {
                "key": "subdomain",
                "label": "Subdomain",
                "type": "text",
                "secret": False,
                "required": True,
                "placeholder": "yourcompany",
                "description": "The {subdomain} in yourcompany.zendesk.com."
            },
            {
                "key": "email",
                "label": "Agent Email",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "The agent account the API token belongs to."
            },
            {
                "key": "apiToken",
                "label": "API Token",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential generated in Zendesk Admin."
            }
        ]
    },
    "fedex": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "FedEx Developer Portal: OAuth credentials issued per project — an API key and a secret key, with the shipping account number for account-scoped calls.",
        "fields": [
            {
                "key": "apiKey",
                "label": "API Key",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Client key issued for your FedEx developer project."
            },
            {
                "key": "secretKey",
                "label": "Secret Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential exchanged for an OAuth token."
            },
            {
                "key": "accountNumber",
                "label": "Account Number",
                "type": "text",
                "secret": False,
                "required": False,
                "description": "Optional. Required for account-scoped tracking and POD requests."
            }
        ]
    },
    "ups": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "UPS Developer Portal: OAuth 2.0 client credentials — a Client ID and Client Secret issued per app, with the shipper account number for account-scoped calls.",
        "fields": [
            {
                "key": "clientId",
                "label": "Client ID",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Issued with your UPS developer application."
            },
            {
                "key": "clientSecret",
                "label": "Client Secret",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential exchanged for an OAuth token."
            },
            {
                "key": "accountNumber",
                "label": "Shipper Account Number",
                "type": "text",
                "secret": False,
                "required": False,
                "description": "Optional. Required for account-scoped tracking requests."
            }
        ]
    },
    "usps": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "USPS APIs: OAuth 2.0 client credentials — a Consumer Key and Consumer Secret issued through the USPS Developer Portal.",
        "fields": [
            {
                "key": "consumerKey",
                "label": "Consumer Key",
                "type": "text",
                "secret": False,
                "required": True,
                "description": "Issued with your USPS developer application."
            },
            {
                "key": "consumerSecret",
                "label": "Consumer Secret",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential exchanged for an OAuth token."
            }
        ]
    },
    "dhl": {
        "environments": None,
        "environment_note": "The DHL tracking API issues one key per developer application.",
        "source": "DHL API Developer Portal: tracking requests authenticate with an API key sent in the DHL-API-Key header.",
        "fields": [
            {
                "key": "apiKey",
                "label": "API Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential for DHL tracking requests."
            }
        ]
    },
    "custom_api": {
        "environments": [
            [
                "sandbox",
                "Sandbox"
            ],
            [
                "production",
                "Production"
            ]
        ],
        "environment_note": None,
        "source": "Generic HTTP API. Field set is intentionally open because the target system is merchant-defined.",
        "fields": [
            {
                "key": "baseUrl",
                "label": "Base URL",
                "type": "text",
                "secret": False,
                "required": True,
                "placeholder": "https://api.example.com",
                "description": "Root URL requests will be sent to."
            },
            {
                "key": "authType",
                "label": "Authentication Type",
                "type": "select",
                "secret": False,
                "required": True,
                "description": "How the credential is presented on each request.",
                "options": [
                    [
                        "bearer",
                        "Bearer token"
                    ],
                    [
                        "api_key_header",
                        "API key header"
                    ],
                    [
                        "basic",
                        "Basic auth"
                    ]
                ]
            },
            {
                "key": "credential",
                "label": "Token / API Key",
                "type": "password",
                "secret": True,
                "required": True,
                "description": "Server-side credential used to authenticate requests."
            },
            {
                "key": "headerName",
                "label": "Header Name",
                "type": "text",
                "secret": False,
                "required": False,
                "placeholder": "X-API-Key",
                "description": "Optional. Only used with the API key header method."
            }
        ]
    }
}


def provider_entry(panel_key, adapter):
    """The registry row for adapter under panel_key, or None."""
    for row in PROVIDERS.get(panel_key, []):
        if row["adapter"] == adapter:
            return row
    return None


def schema_for(adapter):
    """The field schema an adapter gets: its verified one, else the generic."""
    return SCHEMAS.get(adapter) or GENERIC_SCHEMA


def secret_fields_for(adapter):
    """The field keys that are secrets under this adapter's schema."""
    return {f["key"] for f in schema_for(adapter)["fields"] if f["secret"]}


def is_secret_field(adapter, field):
    return field in secret_fields_for(adapter)


def panel_allowed_fields(panel_key):
    """Every field key any of this panel's providers can store.

    Fed into both the save loop's allow-list and _restore_credentials' filter:
    miss either one and a new-style field is silently dropped — on save in the
    first case, on the next restart in the second.
    """
    fields = {"adapter", "environment"}
    for row in PROVIDERS.get(panel_key, []):
        fields.update(f["key"] for f in schema_for(row["adapter"])["fields"])
    fields.update(f["key"] for f in GENERIC_SCHEMA["fields"])
    return fields


def panel_secret_fields(panel_key):
    """Every field key that is a secret under ANY of this panel's providers.

    For display-shaping only (mask if it could be a secret); the save path uses
    the submitted adapter's own schema, where apiKey can be plain (FedEx) or
    secret (DHL)."""
    fields = set()
    for row in PROVIDERS.get(panel_key, []):
        fields.update(secret_fields_for(row["adapter"]))
    fields.update(f["key"] for f in GENERIC_SCHEMA["fields"] if f["secret"])
    return fields


# Every registry adapter must resolve to a schema (its own or the generic) and
# every unverified one must explain itself — the honesty contract of the page.
for _panel, _rows in PROVIDERS.items():
    for _row in _rows:
        assert schema_for(_row["adapter"]) is not None
        if not _row["verified"]:
            PENDING_NOTES.setdefault(
                _row["adapter"],
                f"Credential model not yet verified against {_row['name']} documentation.")
assert set(CATEGORY_ORDER) == set(PROVIDERS), "every tab needs a provider list"
