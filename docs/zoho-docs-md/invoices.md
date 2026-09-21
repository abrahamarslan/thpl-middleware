# Invoices

Invoice is a document sent to your client that indicates the products/services sold by you with the payment information that the client has to make.

---

## Invoice Attributes

| Attribute               | Type    | Description                                                                   |
| :---------------------- | :------ | :---------------------------------------------------------------------------- |
| **invoice_id**          | string  | ID of the invoice                                                             |
| **invoice_number**      | string  | Unique identifier or reference number for the invoice.                        |
| **is_pre_gst**          | boolean | [India only] Applicable for transactions that fall before July 1, 2017        |
| **place_of_supply**     | string  | [India, GCC only] Place where the goods/services are supplied to.             |
| **gst_no**              | string  | [India only] 15 digit GST identification number of the customer.              |
| **gst_treatment**       | string  | [India only] GST treatment (business_gst, business_none, overseas, consumer). |
| **cfdi_usage**          | string  | [Mexico only] Choose CFDI Usage.                                              |
| **vat_treatment**       | string  | [UK only] VAT treatment for the invoices (uk, eu_vat_registered, overseas).   |
| **tax_treatment**       | string  | [GCC, Mexico, Kenya, South Africa only] VAT treatment for the invoice.        |
| **date**                | string  | The date on which the invoice is created (yyyy-mm-dd).                        |
| **status**              | string  | Status: sent, draft, overdue, paid, void, unpaid, partially_paid, viewed.     |
| **payment_terms**       | integer | Number of days allowed for payment.                                           |
| **payment_terms_label** | string  | Custom label for payment terms.                                               |
| **due_date**            | string  | The date by which payment is due (yyyy-mm-dd).                                |
| **customer_id**         | string  | Unique identifier of the customer.                                            |
| **customer_name**       | string  | The name of the customer.                                                     |
| **currency_code**       | string  | The currency code in which the invoice is created.                            |
| **exchange_rate**       | float   | Exchange rate used to convert amounts to base currency.                       |
| **discount**            | float   | Discount amount applied to the invoice.                                       |
| **line_items**          | array   | List of items in the invoice.                                                 |
| **sub_total**           | float   | The sub total of all items.                                                   |
| **tax_total**           | double  | The total amount of tax levied.                                               |
| **total**               | string  | The total amount to be paid.                                                  |
| **balance**             | string  | The unpaid amount.                                                            |
| **billing_address**     | object  | Billing address for the invoice.                                              |
| **shipping_address**    | object  | Shipping address for the invoice.                                             |
| **notes**               | string  | Additional information to be displayed on the invoice.                        |
| **terms**               | string  | Terms and conditions.                                                         |

---

## Create an invoice

Create an invoice for your customer.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Arguments

| Name                    | Type    | Required | Description                                                                                                                                                                                                                                                     |
| :---------------------- | :------ | :------- | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **customer_id**         | string  | **Yes**  | Unique identifier of the customer.                                                                                                                                                                                                                              |
| **line_items**          | array   | **Yes**  | Line items for the invoice.<br>**Sub-arguments:**<br>`item_id` (Required): ID of the item.<br>`rate`: Unit rate.<br>`quantity`: Number of units.<br>`discount`: Discount amount/percent.<br>`tax_id`: ID of tax applied.<br>`hsn_or_sac`: [India] HSN/SAC code. |
| **invoice_number**      | string  | No       | Custom invoice number (requires `ignore_auto_number_generation=true`).                                                                                                                                                                                          |
| **date**                | string  | No       | Invoice date (yyyy-mm-dd).                                                                                                                                                                                                                                      |
| **due_date**            | string  | No       | Date payment is due.                                                                                                                                                                                                                                            |
| **payment_terms**       | integer | No       | Number of days for payment.                                                                                                                                                                                                                                     |
| **currency_id**         | string  | No       | ID of the currency.                                                                                                                                                                                                                                             |
| **exchange_rate**       | float   | No       | Exchange rate for currency conversion.                                                                                                                                                                                                                          |
| **discount**            | float   | No       | Discount amount or percentage.                                                                                                                                                                                                                                  |
| **discount_type**       | string  | No       | `entity_level` or `item_level`.                                                                                                                                                                                                                                 |
| **is_inclusive_tax**    | boolean | No       | True if rates are inclusive of tax.                                                                                                                                                                                                                             |
| **contact_persons**     | array   | No       | Array of contact person IDs to receive the invoice.                                                                                                                                                                                                             |
| **notes**               | string  | No       | Customer notes.                                                                                                                                                                                                                                                 |
| **terms**               | string  | No       | Terms and conditions.                                                                                                                                                                                                                                           |
| **billing_address_id**  | string  | No       | ID of billing address.                                                                                                                                                                                                                                          |
| **shipping_address_id** | string  | No       | ID of shipping address.                                                                                                                                                                                                                                         |
| **place_of_supply**     | string  | No       | [India, GCC] Place of supply code.                                                                                                                                                                                                                              |
| **gst_treatment**       | string  | No       | [India] GST treatment.                                                                                                                                                                                                                                          |
| **gst_no**              | string  | No       | [India] GST Number.                                                                                                                                                                                                                                             |
| **vat_treatment**       | string  | No       | [UK] VAT treatment.                                                                                                                                                                                                                                             |

### Query Parameters

| Name                              | Type    | Required | Description                                                  |
| :-------------------------------- | :------ | :------- | :----------------------------------------------------------- |
| **organization_id**               | string  | **Yes**  | ID of the organization.                                      |
| **send**                          | boolean | No       | Send the invoice to the contact person(s). Default: `false`. |
| **ignore_auto_number_generation** | boolean | No       | Ignore auto number generation (mandates `invoice_number`).   |
| **is_quick_create**               | boolean | No       | Enable quick create mode.                                    |

### Request Example

**JSON Body:**
```json
{
    "customer_id": "982000000567001",
    "contact_persons": [
        "982000000870911"
    ],
    "invoice_number": "INV-00003",
    "date": "2013-11-17",
    "payment_terms": 15,
    "due_date": "2013-12-03",
    "discount": 0,
    "is_discount_before_tax": true,
    "discount_type": "item_level",
    "is_inclusive_tax": false,
    "exchange_rate": 1,
    "line_items": [
        {
            "item_id": "982000000030049",
            "rate": 120,
            "quantity": 1,
            "tax_id": "982000000557028"
        }
    ],
    "notes": "Looking forward for your business.",
    "terms": "Terms & Conditions apply"
}
```

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"customer_id": "982000000567001", "line_items": [{"item_id": "982000000030049", "rate": 120, "quantity": 1}]}'
```

---

## List invoices

Get a list of invoices with pagination, filtering, and sorting.

*   **OAuth Scope:** `ZohoBooks.invoices.READ`

### Query Parameters

| Name                | Type    | Required | Description                                                                                         |
| :------------------ | :------ | :------- | :-------------------------------------------------------------------------------------------------- |
| **organization_id** | string  | **Yes**  | ID of the organization.                                                                             |
| **invoice_number**  | string  | No       | Search by invoice number (supports `startswith` and `contains`).                                    |
| **item_name**       | string  | No       | Search by item name.                                                                                |
| **item_id**         | string  | No       | Search by item ID.                                                                                  |
| **customer_name**   | string  | No       | Search by customer name.                                                                            |
| **customer_id**     | string  | No       | Search by customer ID.                                                                              |
| **status**          | string  | No       | Filter by status: `sent`, `draft`, `overdue`, `paid`, `void`, `unpaid`, `partially_paid`, `viewed`. |
| **date**            | string  | No       | Filter by date (variants: `_start`, `_end`, `_before`, `_after`).                                   |
| **due_date**        | string  | No       | Filter by due date.                                                                                 |
| **total**           | string  | No       | Search by total amount.                                                                             |
| **balance**         | string  | No       | Search by outstanding balance.                                                                      |
| **filter_by**       | string  | No       | Advanced filters (e.g., `Status.Overdue`, `Date.PaymentExpectedDate`).                              |
| **search_text**     | string  | No       | General search across multiple fields.                                                              |
| **sort_column**     | string  | No       | Sort by `customer_name`, `invoice_number`, `date`, `total`, etc.                                    |
| **page**            | integer | No       | Page number (Default: 1).                                                                           |
| **per_page**        | integer | No       | Records per page (Default: 200, Max: 200).                                                          |

### Request Example

**cURL:**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/invoices?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update an invoice

Update an existing invoice. To delete a line item, remove it from the `line_items` list in the payload.

*   **OAuth Scope:** `ZohoBooks.invoices.UPDATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Query Parameters

| Name                              | Type    | Required | Description                    |
| :-------------------------------- | :------ | :------- | :----------------------------- |
| **organization_id**               | string  | **Yes**  | ID of the organization.        |
| **ignore_auto_number_generation** | boolean | No       | Ignore auto number generation. |

### Arguments

Same arguments as "Create an invoice".

### Request Example

**JSON Body:**
```json
{
    "customer_id": "982000000567001",
    "invoice_number": "INV-00003",
    "line_items": [
        {
            "line_item_id": "982000000567021",
            "item_id": "982000000030049",
            "quantity": 2,
            "rate": 120
        }
    ]
}
```

**cURL:**
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"customer_id":"982000000567001","line_items":[{"line_item_id":"982000000567021","item_id":"982000000030049","quantity":2}]}'
```

---

## Get an invoice

Get the details of an invoice.

*   **OAuth Scope:** `ZohoBooks.invoices.READ`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Query Parameters

| Name                | Type    | Required | Description                                     |
| :------------------ | :------ | :------- | :---------------------------------------------- |
| **organization_id** | string  | **Yes**  | ID of the organization.                         |
| **accept**          | string  | No       | Format: `json`, `pdf`, `html`. Default: `json`. |
| **print**           | boolean | No       | Print the exported PDF.                         |

### Request Example

**cURL:**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete an invoice

Delete an existing invoice. Invoices with payments or credits applied cannot be deleted.

*   **OAuth Scope:** `ZohoBooks.invoices.DELETE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Query Parameters

| Name                | Type   | Required | Description             |
| :------------------ | :----- | :------- | :---------------------- |
| **organization_id** | string | **Yes**  | ID of the organization. |

### Request Example

**cURL:**
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Mark an invoice as sent

Mark a draft invoice as sent.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Query Parameters

| Name                | Type   | Required | Description             |
| :------------------ | :----- | :------- | :---------------------- |
| **organization_id** | string | **Yes**  | ID of the organization. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/status/sent?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Void an invoice

Mark an invoice status as void. Payments and credits will be unassociated.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/status/void?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Mark as draft

Mark a voided invoice as draft.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/status/draft?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Email multiple invoices

Send multiple invoices (up to 10) via email.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Query Parameters

| Name                | Type   | Required | Description                  |
| :------------------ | :----- | :------- | :--------------------------- |
| **organization_id** | string | **Yes**  | ID of the organization.      |
| **invoice_ids**     | string | **Yes**  | Comma separated invoice IDs. |

### Arguments

| Name         | Type  | Required | Description                           |
| :----------- | :---- | :------- | :------------------------------------ |
| **contacts** | array | No       | Contact details for email/snail mail. |

### Request Example

**JSON Body:**
```json
{
    "contacts": [
        {
            "contact_id": "460000000026049",
            "email": true,
            "snail_mail": false
        }
    ]
}
```

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/email?organization_id=10234695&invoice_ids=460000000026049' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"contacts":[{"contact_id":"460000000026049","email":true,"snail_mail":false}]}'
```

---

## Create an instant invoice

Create an instant invoice for confirmed sales orders.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Query Parameters

| Name                | Type   | Required | Description             |
| :------------------ | :----- | :------- | :---------------------- |
| **salesorder_id**   | string | **Yes**  | ID of the sales order.  |
| **organization_id** | string | **Yes**  | ID of the organization. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/fromsalesorder?salesorder_id=2000000014088&organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Email an invoice

Email an invoice to the customer.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Arguments

| Name                       | Type    | Required | Description                                      |
| :------------------------- | :------ | :------- | :----------------------------------------------- |
| **to_mail_ids**            | array   | **Yes**  | Array of recipient email addresses.              |
| **cc_mail_ids**            | array   | No       | Array of CC email addresses.                     |
| **subject**                | string  | No       | Email subject.                                   |
| **body**                   | string  | No       | Email body.                                      |
| **send_from_org_email_id** | boolean | No       | Trigger email from organization's email address. |

### Request Example

**JSON Body:**
```json
{
    "to_mail_ids": ["willsmith@bowmanfurniture.com"],
    "subject": "Invoice from Zillium Inc",
    "body": "Dear Customer, Please find the invoice attached."
}
```

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"to_mail_ids":["willsmith@bowmanfurniture.com"],"subject":"Invoice from Zillium Inc","body":"Dear Customer, Please find the invoice attached."}'
```

---

## Submit an invoice for approval

Submit an invoice for approval.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/submit?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Approve an invoice

Approve an invoice.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/approve?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Bulk export Invoices

Export invoices as PDF (Max 25).

*   **OAuth Scope:** `ZohoBooks.invoices.READ`

### Query Parameters

| Name                | Type   | Required | Description                  |
| :------------------ | :----- | :------- | :--------------------------- |
| **organization_id** | string | **Yes**  | ID of the organization.      |
| **invoice_ids**     | string | **Yes**  | Comma separated invoice IDs. |

### Request Example

**cURL:**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/invoices/pdf?organization_id=10234695&invoice_ids=982000000567114,982000000567115' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add attachment to an invoice

Attach a file to an invoice. Allowed extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp`, `pdf`.

*   **OAuth Scope:** `ZohoBooks.invoices.CREATE`

### Path Parameters

| Name           | Type   | Required | Description                       |
| :------------- | :----- | :------- | :-------------------------------- |
| **invoice_id** | string | **Yes**  | Unique identifier of the invoice. |

### Query Parameters

| Name                 | Type    | Required | Description                         |
| :------------------- | :------ | :------- | :---------------------------------- |
| **organization_id**  | string  | **Yes**  | ID of the organization.             |
| **can_send_in_mail** | boolean | No       | Send attachment with invoice email. |
| **attachment**       | binary  | No       | The file to be attached.            |

### Request Example

**cURL:**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/invoices/982000000567114/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: multipart/form-data' \
  --form 'attachment=@/path/to/file.pdf'
```

---

## Generate payment link

Generates a payment link for the invoice with an expiry date.

*   **OAuth Scope:** `ZohoBooks.settings.ALL`

### Query Parameters

| Name                 | Type   | Required | Description             |
| :------------------- | :----- | :------- | :---------------------- |
| **organization_id**  | string | **Yes**  | ID of the organization. |
| **transaction_id**   | string | **Yes**  | Invoice ID.             |
| **transaction_type** | string | **Yes**  | Type: `invoice`.        |
| **link_type**        | string | **Yes**  | `Private` or `Public`.  |
| **expiry_time**      | string | **Yes**  | Format: `yyyy-MM-dd`.   |

### Request Example

**cURL:**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/share/paymentlink?transaction_id=982000000567114&transaction_type=invoice&link_type=public&expiry_time=2024-06-27&organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```