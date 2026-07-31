# Retainer Invoices

A lot of businesses collect an advance payment (or retainer) for products sold or services rendered by them. This amount collected will not be an income but a liability to the company. The revenue is earned only when the product is delivered or the service is completed, if not delivered or completed the advance payment made will be returned to the customer.

## Attributes

| Attribute                                           | Type    | Description                                                                                                                                                                           |
| :-------------------------------------------------- | :------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| retainerinvoice_id                                  | string  | ID of the retainerinvoice                                                                                                                                                             |
| retainerinvoice_number                              | string  | number of the retainer invoice.Variants: `retainerinvoice_number_startswith` and `retainerinvoice_number_contains`. Max-length [100]                                                  |
| date                                                | string  | The date of creation of the retainer invoice.                                                                                                                                         |
| status                                              | string  | retainer invoice status.Allowed Values: `sent`, `draft`, `overdue`, `paid`, `void`, `unpaid`, `partially_paid` and `viewed`                                                           |
| is_pre_gst                                          | string  | Applicable for transactions that fall before july 1, 2017                                                                                                                             |
| place_of_supply                                     | string  | Place where the goods/services are supplied to. (If not given, `place of contact` given for the contact will be taken). **India only**.                                               |
| project_id                                          | string  | ID of the project                                                                                                                                                                     |
| project_name                                        | string  | Name of the project                                                                                                                                                                   |
| last_payment_date                                   | string  | The last payment date of the retainer invoice                                                                                                                                         |
| reference_number                                    | string  | The reference number of the retainer invoice. Max-length [100]                                                                                                                        |
| customer_id                                         | string  | ID of the customer the retainer invoice has to be created.                                                                                                                            |
| customer_name                                       | string  | The name of the customer. Max-length [100]                                                                                                                                            |
| contact_persons_associated                          | array   | Contact Persons associated with the transaction.                                                                                                                                      |
| contact_persons_associated.contact_person_id        | long    | Unique ID of the Contact Person.                                                                                                                                                      |
| contact_persons_associated.contact_person_name      | string  | Name of the Contact Person                                                                                                                                                            |
| contact_persons_associated.first_name               | string  | First Name of the Contact Person.                                                                                                                                                     |
| contact_persons_associated.last_name                | string  | Last Name of the Contact Person.                                                                                                                                                      |
| contact_persons_associated.contact_person_email     | string  | Email ID of the Contact Person.                                                                                                                                                       |
| contact_persons_associated.phone                    | string  | Phone Number of the Contact Person.                                                                                                                                                   |
| contact_persons_associated.mobile                   | string  | Mobile Number of the Contact Person.                                                                                                                                                  |
| contact_persons_associated.communication_preference | object  | Preferred modes of communication for the contact person at transaction level.                                                                                                         |
| communication_preference.is_email_enabled           | boolean | Used to check if Email communication preference is enabled for the contact person at transaction level.                                                                               |
| communication_preference.is_whatsapp_enabled        | boolean | Used to check if WhatsApp communication preference is enabled for the contact person at transaction level. **WhatsApp integration only**.                                             |
| currency_id                                         | string  | The currenct id of the currency                                                                                                                                                       |
| currency_code                                       | string  | The currency code in which the retainer invoice is created.                                                                                                                           |
| currency_symbol                                     | string  | The currency symbol in which the retainer invoice is created.                                                                                                                         |
| exchange_rate                                       | float   | Exchange rate of the currency.                                                                                                                                                        |
| is_viewed_by_client                                 | boolean | Boolean is retainer invoice viewed by client in client portal.                                                                                                                        |
| client_viewed_time                                  | boolean | client viewed time for retainer invoice in client portal.                                                                                                                             |
| is_inclusive_tax                                    | boolean |                                                                                                                                                                                       |
| location_id                                         | string  | Location ID                                                                                                                                                                           |
| location_name                                       | string  | Name of the location.                                                                                                                                                                 |
| line_items                                          | array   | Line items of a retainer invoice.                                                                                                                                                     |
| line_items.line_item_id                             | string  | The line item id                                                                                                                                                                      |
| line_items.description                              | string  | The description of the line items. Max-length [2000]                                                                                                                                  |
| line_items.item_order                               | integer | The order of the line item_order                                                                                                                                                      |
| line_items.rate                                     | double  | Rate of the line item.                                                                                                                                                                |
| line_items.bcy_rate                                 | float   | base currency rate                                                                                                                                                                    |
| line_items.tax_id                                   | string  | ID of the tax or tax group applied to the estimate                                                                                                                                    |
| line_items.tax_name                                 | string  | The name of the tax                                                                                                                                                                   |
| line_items.tax_type                                 | string  | The type of the tax                                                                                                                                                                   |
| line_items.tax_percentage                           | float   | The percentage of tax levied                                                                                                                                                          |
| line_items.item_total                               | float   | The total amount of the line items                                                                                                                                                    |
| line_items.location_id                              | string  | Location ID                                                                                                                                                                           |
| line_items.location_name                            | string  | Name of the location.                                                                                                                                                                 |
| sub_total                                           | float   | The sub total of the all items                                                                                                                                                        |
| total                                               | string  | The total amount to be paid                                                                                                                                                           |
| taxes                                               | array   | List of the taxes levied                                                                                                                                                              |
| taxes.tax_name                                      | string  | The name of the tax                                                                                                                                                                   |
| taxes.tax_amount                                    | float   | The amount of the tax levied                                                                                                                                                          |
| payment_made                                        | float   | The amount paid                                                                                                                                                                       |
| payment_drawn                                       | float   | The amount drawn                                                                                                                                                                      |
| balance                                             | string  | The unpaid amount                                                                                                                                                                     |
| allow_partial_payments                              | boolean | Boolean to check if partial payments are allowed for the contact                                                                                                                      |
| price_precision                                     | integer | The precision value on the price                                                                                                                                                      |
| payment_options                                     | object  | Payment options for the retainer invoice, online payment gateways and bank accounts. Will be displayed in the pdf.                                                                    |
| payment_options.payment_gateways                    | array   | Online payment gateways through which payment can be made.                                                                                                                            |
| payment_gateways.configured                         | boolean | Boolean check to see if a payment gateway ahs been configured                                                                                                                         |
| payment_gateways.additional_field1                  | string  | Paypal payment method. Allowed Values: `standard` and `adaptive`                                                                                                                      |
| payment_gateways.gateway_name                       | string  | Name of the payment gateway associated with the retainer invoice. E.g. paypal, stripe.Allowed Values: `paypal`, `authorize_net`, `payflow_pro`, `stripe`, `2checkout` and `braintree` |
| is_emailed                                          | string  | Boolean check to if the email was sent                                                                                                                                                |
| documents                                           | array   | documents attached to the retainer invoice                                                                                                                                            |
| billing_address                                     | object  |                                                                                                                                                                                       |
| billing_address.address                             | string  |                                                                                                                                                                                       |
| billing_address.street2                             | string  |                                                                                                                                                                                       |
| billing_address.city                                | string  |                                                                                                                                                                                       |
| billing_address.state                               | string  |                                                                                                                                                                                       |
| billing_address.zip                                 | string  |                                                                                                                                                                                       |
| billing_address.country                             | string  |                                                                                                                                                                                       |
| billing_address.fax                                 | string  |                                                                                                                                                                                       |
| shipping_address                                    | object  |                                                                                                                                                                                       |
| shipping_address.address                            | string  |                                                                                                                                                                                       |
| shipping_address.city                               | string  |                                                                                                                                                                                       |
| shipping_address.state                              | string  |                                                                                                                                                                                       |
| shipping_address.zip                                | string  |                                                                                                                                                                                       |
| shipping_address.country                            | string  |                                                                                                                                                                                       |
| shipping_address.fax                                | string  |                                                                                                                                                                                       |
| notes                                               | string  | The notes added below expressing gratitude or for conveying some information.                                                                                                         |
| terms                                               | string  | The terms added below expressing gratitude or for conveying some information.                                                                                                         |
| custom_fields                                       | array   | Custom fields for a reatiner invoice.                                                                                                                                                 |
| custom_fields.index                                 | integer | The index of the custom field                                                                                                                                                         |
| custom_fields.show_on_pdf                           | boolean | Boolean value to check if the custom field is to be dispplayed on the pdf.                                                                                                            |
| custom_fields.value                                 | string  |                                                                                                                                                                                       |
| custom_fields.label                                 | string  | The label of the custom field.                                                                                                                                                        |
| template_id                                         | string  | ID of the pdf template associated with the retainer invoice.                                                                                                                          |
| template_name                                       | string  |                                                                                                                                                                                       |
| page_width                                          | string  |                                                                                                                                                                                       |
| page_height                                         | string  |                                                                                                                                                                                       |
| orientation                                         | string  |                                                                                                                                                                                       |
| template_type                                       | string  | The type of template type                                                                                                                                                             |
| created_time                                        | string  | The time of creation of the retainer invoice                                                                                                                                          |
| last_modified_time                                  | string  | The time of last modification of the retainer invoice                                                                                                                                 |
| created_by_id                                       | string  |                                                                                                                                                                                       |
| attachment_name                                     | string  |                                                                                                                                                                                       |
| can_send_in_mail                                    | boolean |                                                                                                                                                                                       |
| invoice_url                                         | string  |                                                                                                                                                                                       |

### Retainer Invoice Example
```json
{
    "retainerinvoice_id": 982000000567114,
    "retainerinvoice_number": "RET-00003",
    "date": "2013-11-17",
    "status": "draft",
    "is_pre_gst": false,
    "place_of_supply": "TN",
    "project_id": 982000000567154,
    "project_name": "string",
    "last_payment_date": " ",
    "reference_number": " ",
    "customer_id": 982000000567001,
    "customer_name": "Bowman & Co",
    "contact_persons_associated": [
        {
            "contact_person_id": 982000000567003,
            "contact_person_name": "David",
            "first_name": "David",
            "last_name": "Sujin",
            "contact_person_email": "willsmith@bowmanfurniture.com",
            "phone": "+1-925-921-9201",
            "mobile": "+1-4054439562",
            "communication_preference": {
                "is_email_enabled": true,
                "is_whatsapp_enabled": true
            }
        }
    ],
    "currency_id": 982000000000190,
    "currency_code": "USD",
    "currency_symbol": "USD",
    "exchange_rate": 1,
    "is_viewed_by_client": true,
    "client_viewed_time": true,
    "is_inclusive_tax": false,
    "location_id": "460000000038080",
    "location_name": "string",
    "line_items": [
        {
            "line_item_id": 982000000567021,
            "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
            "item_order": 1,
            "rate": 120,
            "bcy_rate": 120,
            "tax_id": 982000000557028,
            "tax_name": "VAT",
            "tax_type": "tax",
            "tax_percentage": 12.5,
            "item_total": 120,
            "location_id": "460000000038080",
            "location_name": "string"
        }
    ],
    "sub_total": 153,
    "total": 40.6,
    "taxes": [
        {
            "tax_name": "VAT",
            "tax_amount": 19.13
        }
    ],
    "payment_made": 26.91,
    "payment_drawn": 26.91,
    "balance": 40.6,
    "allow_partial_payments": true,
    "price_precision": 2,
    "payment_options": {
        "payment_gateways": [
            {
                "configured": true,
                "additional_field1": "standard",
                "gateway_name": "paypal"
            }
        ]
    },
    "is_emailed": false,
    "documents": [],
    "billing_address": {
        "address": "Suite 125, McMillan Avenue",
        "street2": "McMillan Avenue",
        "city": "San Francisco",
        "state": "CA",
        "zip": 94134,
        "country": "U.S.A",
        "fax": "+86-10-82637827"
    },
    "shipping_address": {
        "address": "Suite 125, McMillan Avenue",
        "city": "San Francisco",
        "state": "CA",
        "zip": 94134,
        "country": "U.S.A",
        "fax": "+86-10-82637827"
    },
    "notes": "Looking forward for your business.",
    "terms": "Terms & Conditions apply",
    "custom_fields": [
        {
            "index": 1,
            "show_on_pdf": false,
            "value": "The value of the custom field",
            "label": "Delivery Date"
        }
    ],
    "template_id": 982000000000143,
    "template_name": "Service - Classic",
    "page_width": "8.27in",
    "page_height": "11.69in",
    "orientation": "portrait",
    "template_type": "classic",
    "created_time": "2013-11-18T02:31:51-0800",
    "last_modified_time": "2013-11-18T02:31:51-0800",
    "created_by_id": 14909000000072000,
    "attachment_name": "new file",
    "can_send_in_mail": true,
    "invoice_url": "https://invoice.zoho.com/SecurePayment?CInvoiceID=23d84d0cf64f9a72ea0c66fded25a08c8bafd0ab508aff05323a9f80e2cd03fdc5dd568d3d6407bbda969d3e870d740b6fce549a9438c4ea"
}
```

---

## Create a retainerinvoice
Create a retainer invoice for your customer.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices`

### Arguments
| Argument                   | Type   | Required | Description                                                                                                                           |
| :------------------------- | :----- | :------- | :------------------------------------------------------------------------------------------------------------------------------------ |
| customer_id                | string | Required | ID of the customer the retainer invoice has to be created.                                                                            |
| reference_number           | string | Optional | The reference number of the retainer invoice. Max-length [100]                                                                        |
| date                       | string | Optional | The date of creation of the retainer invoice.                                                                                         |
| contact_persons_associated | array  | Optional | Contact Persons associated with the transaction.                                                                                      |
| custom_fields              | array  | Optional | Custom fields for a reatiner invoice.                                                                                                 |
| notes                      | string | Optional | The notes added below expressing gratitude or for conveying some information.                                                         |
| terms                      | string | Optional | The terms added below expressing gratitude or for conveying some information.                                                         |
| location_id                | string | Optional | Location ID                                                                                                                           |
| line_items                 | array  | Required | Line items of an invoice.                                                                                                             |
| payment_options            | object | Optional | Payment options for the retainer invoice, online payment gateways and bank accounts. Will be displayed in the pdf.                    |
| template_id                | string | Optional | ID of the pdf template associated with the retainer invoice.                                                                          |
| place_of_supply            | string | Optional | Place where the goods/services are supplied to. (If not given, `place of contact` given for the contact will be taken) **India only** |

### Query Parameters
| Parameter                     | Type    | Required | Description                                                                                                                 |
| :---------------------------- | :------ | :------- | :-------------------------------------------------------------------------------------------------------------------------- |
| organization_id               | string  | Required | ID of the organization                                                                                                      |
| ignore_auto_number_generation | boolean | Optional | Ignore auto invoice number generation for this invoice. This mandates the invoice number. Allowed values `true` and `false` |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The retainer invoice has been created.",
    "retainerinvoice": {
        "retainerinvoice_id": 982000000567114,
        "retainerinvoice_number": "RET-00003",
        "date": "2013-11-17",
        "status": "draft",
        "is_pre_gst": false,
        "place_of_supply": "TN",
        "project_id": 982000000567154,
        "project_name": "string",
        "last_payment_date": " ",
        "reference_number": " ",
        "customer_id": 982000000567001,
        "customer_name": "Bowman & Co",
        "contact_persons_associated": [
            {
                "contact_person_id": 982000000567003,
                "contact_person_name": "David",
                "first_name": "David",
                "last_name": "Sujin",
                "contact_person_email": "willsmith@bowmanfurniture.com",
                "phone": "+1-925-921-9201",
                "mobile": "+1-4054439562",
                "communication_preference": {
                    "is_email_enabled": true,
                    "is_whatsapp_enabled": true
                }
            }
        ],
        "currency_id": 982000000000190,
        "currency_code": "USD",
        "currency_symbol": "USD",
        "exchange_rate": 1,
        "is_viewed_by_client": true,
        "client_viewed_time": true,
        "is_inclusive_tax": false,
        "location_id": "460000000038080",
        "location_name": "string",
        "line_items": [
            {
                "line_item_id": 982000000567021,
                "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
                "item_order": 1,
                "rate": 120,
                "bcy_rate": 120,
                "tax_id": 982000000557028,
                "tax_name": "VAT",
                "tax_type": "tax",
                "tax_percentage": 12.5,
                "item_total": 120,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "sub_total": 153,
        "total": 40.6,
        "taxes": [
            {
                "tax_name": "VAT",
                "tax_amount": 19.13
            }
        ],
        "payment_made": 26.91,
        "payment_drawn": 26.91,
        "balance": 40.6,
        "allow_partial_payments": true,
        "price_precision": 2,
        "payment_options": {
            "payment_gateways": [
                {
                    "configured": true,
                    "additional_field1": "standard",
                    "gateway_name": "paypal"
                }
            ]
        },
        "is_emailed": false,
        "documents": [],
        "billing_address": {
            "address": "Suite 125, McMillan Avenue",
            "street2": "McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "shipping_address": {
            "address": "Suite 125, McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "notes": "Looking forward for your business.",
        "terms": "Terms & Conditions apply",
        "custom_fields": [
            {
                "index": 1,
                "show_on_pdf": false,
                "value": "The value of the custom field",
                "label": "Delivery Date"
            }
        ],
        "template_id": 982000000000143,
        "template_name": "Service - Classic",
        "page_width": "8.27in",
        "page_height": "11.69in",
        "orientation": "portrait",
        "template_type": "classic",
        "created_time": "2013-11-18T02:31:51-0800",
        "last_modified_time": "2013-11-18T02:31:51-0800",
        "created_by_id": 14909000000072000,
        "attachment_name": "new file",
        "can_send_in_mail": true,
        "invoice_url": "https://invoice.zoho.com/SecurePayment?CInvoiceID=23d84d0cf64f9a72ea0c66fded25a08c8bafd0ab508aff05323a9f80e2cd03fdc5dd568d3d6407bbda969d3e870d740b6fce549a9438c4ea"
    }
}
```

---

## List a retainer invoices
List all retainer invoices with pagination.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices`

### Query Parameters
| Parameter       | Type    | Required | Description                                                                                                                                                                                                                                                   |
| :-------------- | :------ | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| organization_id | string  | Required | ID of the organization                                                                                                                                                                                                                                        |
| print           | boolean | Optional | Print the exported pdf.                                                                                                                                                                                                                                       |
| sort_column     | string  | Optional | Sort retainer invoices.Allowed Values: `customer_name`, `retainer invoice_number`, `date`, ` due_date`, `total`, `balance` and `created_time`                                                                                                                 |
| filter_by       | string  | Optional | Filter invoices by any status or payment expected date.Allowed Values: ` Status.All`, `Status.Sent`, ` Status.Draft`, `Status.OverDue`, `Status.Paid`, `Status.Void`, `Status.Unpaid`, `Status.PartiallyPaid`, `Status.Viewed` and `Date.PaymentExpectedDate` |
| sort_order      | string  | Optional | The order for sorting                                                                                                                                                                                                                                         |
| page            | integer | Optional | Number of pages                                                                                                                                                                                                                                               |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                               |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "retainerinvoices": [
        {
            "retainerinvoice_id": 982000000567114,
            "customer_name": "Bowman & Co",
            "retainerinvoice_number": "RET-00003",
            "customer_id": 982000000567001,
            "status": "draft",
            "reference_number": " ",
            "project_or_estimate_name": "new project",
            "date": "2013-11-17",
            "currency_id": 982000000000190,
            "currency_code": "USD",
            "is_viewed_by_client": true,
            "client_viewed_time": true,
            "total": 40.6,
            "balance": 40.6,
            "created_time": "2013-11-18T02:31:51-0800",
            "last_modified_time": "2013-11-18T02:31:51-0800",
            "is_emailed": false,
            "last_payment_date": " ",
            "has_attachment": true
        },
        {...},
        {...}
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false,
        "report_name": "Retainer Invoices",
        "applied_filter": "Status.All",
        "sort_column": "created_time",
        "sort_order": "D"
    }
}
```

---

## update a retainerinvoice
Update an existing invoice.

`OAuth Scope : ZohoBooks.invoices.UPDATE`

**Endpoint:**
`PUT /retainerinvoices/{retainerinvoice_id}`

### Arguments
| Argument                   | Type   | Required | Description                                                                                                                           |
| :------------------------- | :----- | :------- | :------------------------------------------------------------------------------------------------------------------------------------ |
| customer_id                | string | Required | ID of the customer the retainer invoice has to be created.                                                                            |
| reference_number           | string | Optional | The reference number of the retainer invoice. Max-length [100]                                                                        |
| date                       | string | Optional | The date of creation of the retainer invoice.                                                                                         |
| contact_persons_associated | array  | Optional | Contact Persons associated with the transaction.                                                                                      |
| custom_fields              | array  | Optional | Custom fields for a reatiner invoice.                                                                                                 |
| notes                      | string | Optional | The notes added below expressing gratitude or for conveying some information.                                                         |
| terms                      | string | Optional | The terms added below expressing gratitude or for conveying some information.                                                         |
| location_id                | string | Optional | Location ID                                                                                                                           |
| line_items                 | array  | Required | Line items of a retainer invoice.                                                                                                     |
| payment_options            | object | Optional | Payment options for the retainer invoice, online payment gateways and bank accounts. Will be displayed in the pdf.                    |
| template_id                | string | Optional | ID of the pdf template associated with the retainer invoice.                                                                          |
| place_of_supply            | string | Optional | Place where the goods/services are supplied to. (If not given, `place of contact` given for the contact will be taken) **India only** |
| project_id                 | string | Optional | ID of the project                                                                                                                     |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Retainer Invoice information has been updated.",
    "retainerinvoice": {
        "retainerinvoice_id": 982000000567114,
        "retainerinvoice_number": "RET-00003",
        "date": "2013-11-17",
        "status": "draft",
        "is_pre_gst": false,
        "place_of_supply": "TN",
        "project_id": 982000000567154,
        "project_name": "string",
        "last_payment_date": " ",
        "reference_number": " ",
        "customer_id": 982000000567001,
        "customer_name": "Bowman & Co",
        "contact_persons_associated": [
            {
                "contact_person_id": 982000000567003,
                "contact_person_name": "David",
                "first_name": "David",
                "last_name": "Sujin",
                "contact_person_email": "willsmith@bowmanfurniture.com",
                "phone": "+1-925-921-9201",
                "mobile": "+1-4054439562",
                "communication_preference": {
                    "is_email_enabled": true,
                    "is_whatsapp_enabled": true
                }
            }
        ],
        "currency_id": 982000000000190,
        "currency_code": "USD",
        "currency_symbol": "USD",
        "exchange_rate": 1,
        "is_viewed_by_client": true,
        "client_viewed_time": true,
        "is_inclusive_tax": false,
        "location_id": "460000000038080",
        "location_name": "string",
        "line_items": [
            {
                "line_item_id": 982000000567021,
                "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
                "item_order": 1,
                "rate": 120,
                "bcy_rate": 120,
                "tax_id": 982000000557028,
                "tax_name": "VAT",
                "tax_type": "tax",
                "tax_percentage": 12.5,
                "item_total": 120,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "sub_total": 153,
        "total": 40.6,
        "taxes": [
            {
                "tax_name": "VAT",
                "tax_amount": 19.13
            }
        ],
        "payment_made": 26.91,
        "payment_drawn": 26.91,
        "balance": 40.6,
        "allow_partial_payments": true,
        "price_precision": 2,
        "payment_options": {
            "payment_gateways": [
                {
                    "configured": true,
                    "additional_field1": "standard",
                    "gateway_name": "paypal"
                }
            ]
        },
        "is_emailed": false,
        "documents": [],
        "billing_address": {
            "address": "Suite 125, McMillan Avenue",
            "street2": "McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "shipping_address": {
            "address": "Suite 125, McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "notes": "Looking forward for your business.",
        "terms": "Terms & Conditions apply",
        "custom_fields": [
            {
                "index": 1,
                "show_on_pdf": false,
                "value": "The value of the custom field",
                "label": "Delivery Date"
            }
        ],
        "template_id": 982000000000143,
        "template_name": "Service - Classic",
        "page_width": "8.27in",
        "page_height": "11.69in",
        "orientation": "portrait",
        "template_type": "classic",
        "created_time": "2013-11-18T02:31:51-0800",
        "last_modified_time": "2013-11-18T02:31:51-0800",
        "created_by_id": 14909000000072000,
        "attachment_name": "new file",
        "can_send_in_mail": true,
        "invoice_url": "https://invoice.zoho.com/SecurePayment?CInvoiceID=23d84d0cf64f9a72ea0c66fded25a08c8bafd0ab508aff05323a9f80e2cd03fdc5dd568d3d6407bbda969d3e870d740b6fce549a9438c4ea"
    }
}
```

---

## Get a retainer invoice
Get the details of a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices/{retainerinvoice_id}`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "retainerinvoice": {
        "retainerinvoice_id": 982000000567114,
        "retainerinvoice_number": "RET-00003",
        "date": "2013-11-17",
        "status": "draft",
        "is_pre_gst": false,
        "place_of_supply": "TN",
        "project_id": 982000000567154,
        "project_name": "string",
        "last_payment_date": " ",
        "reference_number": " ",
        "customer_id": 982000000567001,
        "customer_name": "Bowman & Co",
        "contact_persons_associated": [
            {
                "contact_person_id": 982000000567003,
                "contact_person_name": "David",
                "first_name": "David",
                "last_name": "Sujin",
                "contact_person_email": "willsmith@bowmanfurniture.com",
                "phone": "+1-925-921-9201",
                "mobile": "+1-4054439562",
                "communication_preference": {
                    "is_email_enabled": true,
                    "is_whatsapp_enabled": true
                }
            }
        ],
        "currency_id": 982000000000190,
        "currency_code": "USD",
        "currency_symbol": "USD",
        "exchange_rate": 1,
        "is_viewed_by_client": true,
        "client_viewed_time": true,
        "is_inclusive_tax": false,
        "location_id": "460000000038080",
        "location_name": "string",
        "line_items": [
            {
                "line_item_id": 982000000567021,
                "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
                "item_order": 1,
                "rate": 120,
                "bcy_rate": 120,
                "tax_id": 982000000557028,
                "tax_name": "VAT",
                "tax_type": "tax",
                "tax_percentage": 12.5,
                "item_total": 120,
                "location_id": "460000000038080",
                "location_name": "string"
            }
        ],
        "sub_total": 153,
        "total": 40.6,
        "taxes": [
            {
                "tax_name": "VAT",
                "tax_amount": 19.13
            }
        ],
        "payment_made": 26.91,
        "payment_drawn": 26.91,
        "balance": 40.6,
        "allow_partial_payments": true,
        "price_precision": 2,
        "payment_options": {
            "payment_gateways": [
                {
                    "configured": true,
                    "additional_field1": "standard",
                    "gateway_name": "paypal"
                }
            ]
        },
        "is_emailed": false,
        "documents": [],
        "billing_address": {
            "address": "Suite 125, McMillan Avenue",
            "street2": "McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "shipping_address": {
            "address": "Suite 125, McMillan Avenue",
            "city": "San Francisco",
            "state": "CA",
            "zip": 94134,
            "country": "U.S.A",
            "fax": "+86-10-82637827"
        },
        "notes": "Looking forward for your business.",
        "terms": "Terms & Conditions apply",
        "custom_fields": [
            {
                "index": 1,
                "show_on_pdf": false,
                "value": "The value of the custom field",
                "label": "Delivery Date"
            }
        ],
        "template_id": 982000000000143,
        "template_name": "Service - Classic",
        "page_width": "8.27in",
        "page_height": "11.69in",
        "orientation": "portrait",
        "template_type": "classic",
        "created_time": "2013-11-18T02:31:51-0800",
        "last_modified_time": "2013-11-18T02:31:51-0800",
        "created_by_id": 14909000000072000,
        "attachment_name": "new file",
        "can_send_in_mail": true,
        "invoice_url": "https://invoice.zoho.com/SecurePayment?CInvoiceID=23d84d0cf64f9a72ea0c66fded25a08c8bafd0ab508aff05323a9f80e2cd03fdc5dd568d3d6407bbda969d3e870d740b6fce549a9438c4ea"
    }
}
```

---

## Delete a retainer invoice
Delete an existing retainer invoice. Invoices which have payment or credits note applied cannot be deleted.

`OAuth Scope : ZohoBooks.invoices.DELETE`

**Endpoint:**
`DELETE /retainerinvoices/{retainerinvoice_id}`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The retainer invoice has been deleted."
}
```

---

## Mark a retainer invoice as sent
Mark a draft retainer invoice as sent.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{retainerinvoice_id}/status/sent`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/status/sent?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Retainer Invoice status has been changed to Sent."
}
```

---

## Update retainer invoice template
Update the pdf template associated with the retainer invoice.

`OAuth Scope : ZohoBooks.invoices.UPDATE`

**Endpoint:**
`PUT /retainerinvoices/{retainerinvoice_id}/templates/{template_id}`

### Path Parameters
| Parameter          | Type   | Required | Description                                         |
| :----------------- | :----- | :------- | :-------------------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice.          |
| template_id        | string | Required | Unique identifier of the retainer invoice template. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/templates/982000000000143?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Retainer Invoice information has been updated."
}
```

---

## Void a retainer invoice
Mark an invoice status as void. Upon voiding, the payments and credits associated with the retainer invoices will be unassociated and will be under customer credits.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{retainerinvoice_id}/status/void`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/status/void?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Retainer Invoice status has been changed to 'Void'."
}
```

---

## Mark as draft
Mark a voided retainer invoice as draft.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{reatinerinvoice_id}/status/draft`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| reatinerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/status/draft?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Status of retainer invoice changed from void to draft."
}
```

---

## Submit a retainer invoice for approval
Submit a retainer invoice for approval.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{reatinerinvoice_id}/submit`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| reatinerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/submit?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The Retainer Invoice has been successfully submitted for approval."
}
```

---

## Approve a retainer invoice.
Approve a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{reatinerinvoice_id}/approve`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| reatinerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/approve?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "You have approved the Retainer Invoice."
}
```

---

## Email a retainer invoice
Email a retainer invoice to the customer. Input json string is not mandatory. If input json string is empty, mail will be send with default mail content.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{retainerinvoice_id}/email`

### Arguments
| Argument               | Type    | Required | Description                                                        |
| :--------------------- | :------ | :------- | :----------------------------------------------------------------- |
| send_from_org_email_id | boolean | Optional | Boolean to trigger the email from the organization's email address |
| to_mail_ids            | array   | Required | Array of email address of the recipients.                          |
| cc_mail_ids            | array   | Optional | Array of email address of the recipients to be cced.               |
| subject                | string  | Optional | The subject of the mail                                            |
| body                   | string  | Optional | The body of the mail                                               |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter               | Type    | Required | Description                                            |
| :---------------------- | :------ | :------- | :----------------------------------------------------- |
| organization_id         | string  | Required | ID of the organization                                 |
| send_customer_statement | boolean | Optional | Send customer statement pdf a with email.              |
| send_attachment         | boolean | Optional | Send the retainer invoice attachment a with the email. |
| attachments             | binary  | Optional | Files to be attached to the email                      |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Your retainer invoice has been sent."
}
```

---

## Get retainer invoice email content
Get the email content of a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices/{retainerinvoice_id}/email`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "gateways_configured": true,
    "deprecated_placeholders_used": [],
    "body": "Dear Customer,         <br><br><br><br>Thanks for your business.         <br><br><br><br>The retainer invoice RET-00001 is attached with this email. You can choose the easy way out and <a href= https://invoice.zoho.com/SecurePayment?CInvoiceID=b9800228e011ae86abe71227bdacb3c68e1af685f647dcaed747812e0b9314635e55ac6223925675b371fcbd2d5ae3dc  >pay online for this invoice.</a>         <br><br>Here's an overview of the invoice for your reference.         <br><br><br><br>Invoice Overview:         <br><br>Invoice  : INV-00001         <br><br>Date : 05 Aug 2013         <br><br>Amount : $541.82         <br><br><br><br>It was great working with you. Looking forward to working with you again.<br><br><br>\\nRegards<br>\\nZillium Inc<br>\\n\",",
    "error_list": [],
    "subject": "Retainer Invoice from Zillium Inc (Retainer Invoice#: RET-00001)",
    "to_contacts": [
        {
            "first_name": "David",
            "selected": false,
            "phone": "+1-925-921-9201",
            "email": "willsmith@bowmanfurniture.com",
            "last_name": "Sujin",
            "salutation": "Mr",
            "contact_person_id": 982000000567003,
            "mobile": "+1-4054439562"
        }
    ],
    "attachment_name": "new file",
    "email_template_id": "string",
    "file_name": "RET-00001.pdf",
    "from_emails": [
        {
            "user_name": "John Smith",
            "selected": false,
            "email": "willsmith@bowmanfurniture.com"
        }
    ],
    "customer_id": 982000000567001
}
```

---

## Update billing address
Updates the billing address for this retainer invoice alone.

`OAuth Scope : ZohoBooks.invoices.UPDATE`

**Endpoint:**
`PUT /retainerinvoices/{retainerinvoice_id}/address/billing`

### Arguments
| Argument | Type   | Required | Description             |
| :------- | :----- | :------- | :---------------------- |
| address  | string | Optional | address of the customer |
| city     | string | Optional | city of the customer    |
| state    | string | Optional | state of the customer   |
| zip      | string | Optional | zip of the customer     |
| country  | string | Optional | country of the customer |
| fax      | string | Optional | fax of the customer     |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/address/billing?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Billing address updated"
}
```

---

## List retainer invoice templates
Get all retainer invoice pdf templates.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices/templates`

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/templates?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "templates": [
        {
            "template_name": "Service - Classic",
            "template_id": 982000000000143,
            "template_type": "classic"
        },
        {...},
        {...}
    ]
}
```

---

## Add attachment to a retainer invoice
Attach a file to an invoice.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{retainerinvoice_id}/attachment`

### Arguments
| Argument         | Type    | Required | Description                                                      |
| :--------------- | :------ | :------- | :--------------------------------------------------------------- |
| can_send_in_mail | boolean | Optional |                                                                  |
| attachment       | binary  | Optional | The file to be attached. It has to be sent in multipart/formdata |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Your file has been attached."
}
```

---

## Get a retainer invoice attachment
Returns the file attached to the retainer invoice.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices/{retainerinvoice_id}/attachment`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success"
}
```

---

## Delete an attachment
Delete the file attached to the retainer invoice.

`OAuth Scope : ZohoBooks.invoices.DELETE`

**Endpoint:**
`DELETE /retainerinvoices/{retainerinvoice_id}/documents/{document_id}`

### Path Parameters
| Parameter          | Type   | Required | Description                                         |
| :----------------- | :----- | :------- | :-------------------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice.          |
| document_id        | string | Required | Unique identifier of the retainer invoice document. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/documents/982000000567115?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Your file is no longer attached to the invoice."
}
```

---

## Add comment
Add a comment for a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.CREATE`

**Endpoint:**
`POST /retainerinvoices/{retainerinvoice_id}/comments`

### Arguments
| Argument                | Type    | Required | Description                                                |
| :---------------------- | :------ | :------- | :--------------------------------------------------------- |
| description             | string  | Optional | The description of the comment. Max-length [2000]          |
| payment_expected_date   | string  | Optional |                                                            |
| show_comment_to_clients | boolean | Optional | Boolean to check if the comment to be shown to the clients |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Comments added."
}
```

---

## List retainer invoice comments & history
Get the complete history and comments of a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.READ`

**Endpoint:**
`GET /retainerinvoices/{retainerinvoice_id}/comments`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "comments": [
        {
            "comment_id": 982000000567019,
            "retainerinvoice_id": 982000000567114,
            "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
            "commented_by_id": 982000000554041,
            "commented_by": "John David",
            "comment_type": "system",
            "operation_type": "Added",
            "date": "2013-11-17",
            "date_description": "yesterday",
            "time": "2:38 AM",
            "transaction_id": "982000000567204",
            "transaction_type": "retainer_payment"
        },
        {...},
        {...}
    ]
}
```

---

## Update comment
Update an existing comment of a retainer invoice.

`OAuth Scope : ZohoBooks.invoices.UPDATE`

**Endpoint:**
`PUT /retainerinvoices/{retainerinvoice_id}/comments/{comment_id}`

### Arguments
| Argument                | Type    | Required | Description                                                |
| :---------------------- | :------ | :------- | :--------------------------------------------------------- |
| description             | string  | Optional | The comment on a retainer invoice                          |
| show_comment_to_clients | boolean | Optional | Boolean to check if the comment to be shown to the clients |

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |
| comment_id         | string | Required | Unique identifier of the comment.          |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/comments/982000000567019?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The comment has been updated.",
    "comment": {
        "comment_id": 982000000567019,
        "retainerinvoice_id": 982000000567114,
        "description": "500GB, USB 2.0 interface 1400 rpm, protective hard case.",
        "commented_by_id": 982000000554041,
        "commented_by": "John David",
        "date": "2013-11-17",
        "date_description": "yesterday",
        "time": "2:38 AM",
        "comment_type": "system"
    }
}
```

---

## Delete a comment
Delete a retainer invoice comment.

`OAuth Scope : ZohoBooks.invoices.DELETE`

**Endpoint:**
`DELETE /retainerinvoices/{retainerinvoice_id}/comments/{comment_id}`

### Path Parameters
| Parameter          | Type   | Required | Description                                |
| :----------------- | :----- | :------- | :----------------------------------------- |
| retainerinvoice_id | string | Required | Unique identifier of the retainer invoice. |
| comment_id         | string | Required | Unique identifier of the comment.          |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/retainerinvoices/982000000567114/comments/982000000567019?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The comment has been deleted."
}
```