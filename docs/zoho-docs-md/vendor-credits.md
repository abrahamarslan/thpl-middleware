# Vendor Credits

Vendor credits are credits that you receive from your vendor, and is treated as an equivalent of physical cash that the vendor owes you. This helps you track the money you're owed until it is either paid by said vendor at a later date i.e refunded, or subtracted from any future bill amount due to that vendor.

### Vendor Credits OpenAPI Document
[Download Vendor Credits OpenAPI Document](vendor-credits.yml)

## Vendor Credit Attributes

| Attribute                  | Type    | Description                                                                                                                                                                                                                                                                                                                                         |
| :------------------------- | :------ | :-------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| vendor_credit_id           | string  | ID of the Vendor Credit                                                                                                                                                                                                                                                                                                                             |
| vendor_credit_number       | string  | Unique vendor credit number displayed in the interface. Auto-generated with DN prefix unless auto number generation is disabled. Max-Length [100]                                                                                                                                                                                                   |
| date                       | string  | The date on which the vendor credit is created. Must be in yyyy-mm-dd format. This date determines the accounting period and affects tax calculations.                                                                                                                                                                                              |
| source_of_supply           | string  | **🇮🇳 India only** Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken)                                                                                                                                                                                                           |
| destination_of_supply      | string  | **🇮🇳 India only** Place where the goods/services are supplied to. (If not given, organisation's home state will be taken)                                                                                                                                                                                                                            |
| place_of_supply            | string  | **GCC only** The place of supply is where a transaction is considered to have occurred for VAT purposes. <br>Supported codes for UAE emirates: `AB`, `AJ`, `DU`, `FU`, `RA`, `SH`, `UM`.<br>Supported codes for GCC countries: `AE`, `SA`, `BH`, `KW`, `OM`, `QA`.                                                                                  |
| gst_no                     | string  | **🇮🇳 India only** 15 digit GST identification number of the vendor.                                                                                                                                                                                                                                                                                  |
| gst_treatment              | string  | **🇮🇳 India only** Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values: `business_gst`, `business_none`, `overseas`, `consumer`.                                                                                                                                                                              |
| tax_treatment              | string  | **GCC, 🇲🇽 Mexico, 🇰🇪 Kenya, 🇿🇦 South Africa only** VAT treatment for the vendor credit. <br>Values: `vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc`, `dz_vat_registered` (UAE), `dz_vat_not_registered` (UAE), `home_country_mexico`, `border_region_mexico`, `non_mexico`, `non_kenya`, `overseas`. |
| pricebook_id               | string  | Unique identifier for the pricebook used for pricing items in the vendor credit.                                                                                                                                                                                                                                                                    |
| is_reverse_charge_applied  | boolean | **🇮🇳 India only** Applicable for transactions where you pay reverse charge.                                                                                                                                                                                                                                                                          |
| status                     | string  | Status of the vendor credit.                                                                                                                                                                                                                                                                                                                        |
| reference_number           | string  | Optional reference number for tracking purposes. Max-Length [100]                                                                                                                                                                                                                                                                                   |
| vendor_id                  | string  | Unique identifier for the vendor contact.                                                                                                                                                                                                                                                                                                           |
| vendor_name                | string  | Name of the Vendor Associated with the Vendor Credit.                                                                                                                                                                                                                                                                                               |
| currency_id                | string  | Unique identifier for the currency used in the vendor credit.                                                                                                                                                                                                                                                                                       |
| currency_code              | string  | Code of the Currency Involved in the Vendor Credit.                                                                                                                                                                                                                                                                                                 |
| exchange_rate              | double  | Exchange rate for converting the vendor credit currency to base currency.                                                                                                                                                                                                                                                                           |
| price_precision            | integer | Precision of the price.                                                                                                                                                                                                                                                                                                                             |
| vat_treatment              | string  | **🇬🇧 UK only** VAT treatment for the vendor credits. Values: `uk`, `eu_vat_registered`, `overseas`.                                                                                                                                                                                                                                                  |
| filed_in_vat_return_id     | string  | **🇬🇧 UK only** ID of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                   |
| filed_in_vat_return_name   | string  | **🇬🇧 UK only** Name of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                 |
| filed_in_vat_return_type   | string  | **🇬🇧 UK only** Type of the VAT Return the Vendor Credit is filed in.                                                                                                                                                                                                                                                                                 |
| is_inclusive_tax           | boolean | **🇺🇸 US only** Set to true if line item rates include tax amounts.                                                                                                                                                                                                                                                                                   |
| location_id                | string  | Unique identifier for the business location.                                                                                                                                                                                                                                                                                                        |
| location_name              | string  | Name of the location.                                                                                                                                                                                                                                                                                                                               |
| line_items                 | object  | Line items of a vendor credit. (See sub-attributes below)                                                                                                                                                                                                                                                                                           |
| acquisition_vat_summary    | array   | **🇬🇧 UK / Europe only** Summary of the VAT Acquisition.                                                                                                                                                                                                                                                                                              |
| acquisition_vat_total      | double  | **🇬🇧 UK / Europe only** Total of the VAT Acquisition.                                                                                                                                                                                                                                                                                                |
| reverse_charge_vat_summary | array   | **🇬🇧 UK / Europe only** Summary of the Reverse Charge.                                                                                                                                                                                                                                                                                               |
| reverse_charge_vat_total   | double  | **🇬🇧 UK / Europe only** Total of the Reverse Charge.                                                                                                                                                                                                                                                                                                 |
| documents                  | array   | Array of documents associated.                                                                                                                                                                                                                                                                                                                      |
| custom_fields              | array   | Array of custom fields.                                                                                                                                                                                                                                                                                                                             |
| sub_total                  | double  | Sub total of the vendor credit.                                                                                                                                                                                                                                                                                                                     |
| total                      | double  | Total of the vendor credit.                                                                                                                                                                                                                                                                                                                         |
| total_credits_used         | double  | Total credits used.                                                                                                                                                                                                                                                                                                                                 |
| total_refunded_amount      | double  | Total refunded amount.                                                                                                                                                                                                                                                                                                                              |
| balance                    | double  | Balance in the Vendor Credit.                                                                                                                                                                                                                                                                                                                       |
| notes                      | string  | Additional notes. Max-length [5000].                                                                                                                                                                                                                                                                                                                |
| comments                   | array   | Array of comments.                                                                                                                                                                                                                                                                                                                                  |
| vendor_credit_refunds      | array   | Array of refunds.                                                                                                                                                                                                                                                                                                                                   |
| bills_credited             | array   | Array of bills credited.                                                                                                                                                                                                                                                                                                                            |
| created_time               | string  | Time of Vendor Credit Creation.                                                                                                                                                                                                                                                                                                                     |
| last_modified_time         | string  | Last Modified Time of Vendor Credit.                                                                                                                                                                                                                                                                                                                |

### Vendor Credit Object Example
```json
{
    "vendor_credit_id": "3000000002075",
    "vendor_credit_number": "DN-00002",
    "date": "2014-08-28",
    "source_of_supply": "TN",
    "destination_of_supply": "TN",
    "place_of_supply": "DU",
    "gst_no": "22AAAAA0000A1Z5",
    "gst_treatment": "business_gst",
    "tax_treatment": "vat_registered",
    "status": "open",
    "vendor_id": "460000000020029",
    "vendor_name": "Bowman and Co",
    "currency_id": "3000000000083",
    "currency_code": "USD",
    "exchange_rate": 1,
    "line_items": [
        {
            "item_id": "460000000020071",
            "line_item_id": "460000000020077",
            "account_id": "460000000020097",
            "name": "Premium Plan - Web hosting",
            "quantity": 1,
            "rate": 30,
            "item_total": 30
        }
    ],
    "sub_total": 30,
    "total": 30,
    "balance": 30
}
```

---

## Create a vendor credit
Create a new vendor credit to record credits issued by vendors for returned items, overpayments, or adjustments. Supports multi-currency transactions, custom line items, tax calculations, and workflows.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Arguments

| Argument              | Type    | Required     | Description                                                          |
| :-------------------- | :------ | :----------- | :------------------------------------------------------------------- |
| vendor_id             | string  | **Required** | Unique identifier for the vendor contact.                            |
| currency_id           | string  | Optional     | Unique identifier for the currency.                                  |
| vat_treatment         | string  | Optional     | **🇬🇧 UK only** VAT treatment (`uk`, `eu_vat_registered`, `overseas`). |
| vendor_credit_number  | string  | Optional     | Mandatory if auto number generation is disabled.                     |
| gst_treatment         | string  | Optional     | **🇮🇳 India only** GST treatment.                                      |
| tax_treatment         | string  | Optional     | **GCC, 🇲🇽, 🇰🇪, 🇿🇦 only** VAT treatment.                                 |
| gst_no                | string  | Optional     | **🇮🇳 India only** 15 digit GST number.                                |
| source_of_supply      | string  | Optional     | **🇮🇳 India only** Place of supply source.                             |
| destination_of_supply | string  | Optional     | **🇮🇳 India only** Place of supply destination.                        |
| place_of_supply       | string  | Optional     | **GCC only** Place of supply code.                                   |
| pricebook_id          | string  | Optional     | Pricebook ID.                                                        |
| reference_number      | string  | Optional     | Reference number.                                                    |
| is_update_customer    | boolean | Optional     | Set to true to update customer info.                                 |
| date                  | string  | Optional     | Date of vendor credit (yyyy-mm-dd).                                  |
| exchange_rate         | double  | Optional     | Exchange rate.                                                       |
| is_inclusive_tax      | boolean | Optional     | **🇺🇸 US only** Set to true if rates include tax.                      |
| location_id           | string  | Optional     | Business location ID.                                                |
| line_items            | array   | Optional     | Line items of a vendor credit.                                       |
| notes                 | string  | Optional     | Additional notes.                                                    |
| documents             | array   | Optional     | Documents attached.                                                  |
| custom_fields         | array   | Optional     | Custom fields.                                                       |

### Query Parameters

| Parameter                     | Type    | Required     | Description                                                             |
| :---------------------------- | :------ | :----------- | :---------------------------------------------------------------------- |
| organization_id               | string  | **Required** | ID of the organization.                                                 |
| ignore_auto_number_generation | boolean | Optional     | Ignore auto number generation (vendor credit number becomes mandatory). |
| bill_id                       | string  | Optional     | Bill Associated with the Vendor Credit.                                 |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000020029",
    "currency_id": "3000000000083",
    "vendor_credit_number": "DN-00002",
    "date": "2014-08-28",
    "line_items": [
        {
            "item_id": "460000000020071",
            "account_id": "460000000020097",
            "name": "Premium Plan - Web hosting",
            "quantity": 1,
            "rate": 30
        }
    ]
}'
```

---

## List vendor credits
Retrieve a paginated list of vendor credits with comprehensive filtering, sorting, and search capabilities.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Query Parameters

| Parameter            | Type    | Required     | Description                                                                                      |
| :------------------- | :------ | :----------- | :----------------------------------------------------------------------------------------------- |
| organization_id      | string  | **Required** | ID of the organization.                                                                          |
| vendor_credit_number | string  | Optional     | Filter by specific number. Supports `_startswith` and `_contains`.                               |
| date                 | string  | Optional     | Filter by date (yyyy-mm-dd). Supports `_start`, `_end`, `_before`, `_after`.                     |
| status               | string  | Optional     | Filter by status (`open`, `closed`, `void`, `draft`).                                            |
| total                | string  | Optional     | Filter by total amount. Supports `_start`, `_end`, `_less_than`, `_greater_than`, etc.           |
| reference_number     | string  | Optional     | Filter by reference number. Supports `_startswith` and `_contains`.                              |
| customer_name        | string  | Optional     | Filter by vendor name. Supports `_startswith` and `_contains`.                                   |
| item_name            | string  | Optional     | Filter by item name.                                                                             |
| item_description     | string  | Optional     | Filter by item description.                                                                      |
| notes                | string  | Optional     | Filter by notes.                                                                                 |
| custom_field         | string  | Optional     | Filter by custom field.                                                                          |
| last_modified_time   | string  | Optional     | Filter by last modified time (ISO 8601).                                                         |
| customer_id          | long    | Optional     | Filter by customer ID.                                                                           |
| line_item_id         | long    | Optional     | Filter by line item ID.                                                                          |
| item_id              | long    | Optional     | Filter by item ID.                                                                               |
| tax_id               | long    | Optional     | Filter by tax ID.                                                                                |
| filter_by            | string  | Optional     | Predefined filters: `Status.All`, `Status.Open`, `Status.Draft`, `Status.Closed`, `Status.Void`. |
| search_text          | string  | Optional     | Text search across multiple fields.                                                              |
| sort_column          | string  | Optional     | Sort by `vendor_name`, `vendor_credit_number`, `balance`, `total`, `date`, `created_time`, etc.  |
| page                 | integer | Optional     | Page number. Default 1.                                                                          |
| per_page             | integer | Optional     | Records per page. Default 200.                                                                   |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update vendor credit
Update an existing vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.UPDATE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Arguments
Arguments are similar to the "Create a vendor credit" endpoint (e.g., `vendor_id`, `line_items`, `date`, `notes`, etc.).

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "vendor_id": "460000000020029",
    "vendor_credit_number": "DN-00002",
    "date": "2014-08-28",
    "line_items": [
        {
            "item_id": "460000000020071",
            "quantity": 1,
            "rate": 30
        }
    ]
}'
```

---

## Get vendor credit
Get details of a vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type    | Required     | Description                                                          |
| :-------------- | :------ | :----------- | :------------------------------------------------------------------- |
| organization_id | string  | **Required** | ID of the organization.                                              |
| print           | boolean | Optional     | Export PDF with default print option (`true`, `false`, `on`, `off`). |
| accept          | string  | Optional     | Format (`json`, `pdf`, `html`). Default is html.                     |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete vendor credit
Delete a vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.DELETE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Convert to open
Change an existing vendor credit status to open.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/status/open?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Void vendor credit
Mark an existing vendor credit as void.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/status/void?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Submit a Vendor credit for approval
Submit a Vendor credit for approval.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/submit?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Approve a Vendor credit
Approve a Vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/approve?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Apply credits to a bill
Apply vendor credit to existing bills.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Arguments
| Argument | Type  | Required     | Description                                                                 |
| :------- | :---- | :----------- | :-------------------------------------------------------------------------- |
| bills    | array | **Required** | List of bills to apply credits to. Contains `bill_id` and `amount_applied`. |

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/bills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "bills": [
        {
            "bill_id": "460000000057075",
            "amount_applied": 10
        }
    ]
}'
```

---

## List bills credited
List bills to which the vendor credit is applied.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/bills?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete bills credited
Delete the credits applied to a bill.

`OAuth Scope : ZohoBooks.debitnotes.DELETE`

### Path Parameters
| Parameter             | Type   | Required     | Description                                  |
| :-------------------- | :----- | :----------- | :------------------------------------------- |
| vendor_credit_id      | string | **Required** | Unique identifier of the vendor credit.      |
| vendor_credit_bill_id | string | **Required** | Unique identifier of the vendor credit bill. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/bills/460000000057075?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Refund a vendor credit
Refund vendor credit amount.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Arguments
| Argument         | Type   | Required     | Description                                        |
| :--------------- | :----- | :----------- | :------------------------------------------------- |
| date             | string | **Required** | Date of Vendor Credit Refund.                      |
| amount           | double | **Required** | Refund amount.                                     |
| account_id       | string | **Required** | Unique identifier for the chart of accounts entry. |
| refund_mode      | string | Optional     | Mode of Refund.                                    |
| reference_number | string | Optional     | Reference number.                                  |
| exchange_rate    | double | Optional     | Exchange rate.                                     |
| description      | string | Optional     | Detailed description.                              |

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/refunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2014-08-30",
    "refund_mode": "cash",
    "reference_number": "string",
    "amount": 13,
    "exchange_rate": 1,
    "account_id": "460000000020097",
    "description": "string"
}'
```

---

## List refunds of a vendor credit
List all refunds of an existing vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type    | Required     | Description             |
| :-------------- | :------ | :----------- | :---------------------- |
| organization_id | string  | **Required** | ID of the organization. |
| page            | integer | Optional     | Page number.            |
| per_page        | integer | Optional     | Records per page.       |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/refunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update vendor credit refund
Update the refunded transaction.

`OAuth Scope : ZohoBooks.debitnotes.UPDATE`

### Path Parameters
| Parameter               | Type   | Required     | Description                                    |
| :---------------------- | :----- | :----------- | :--------------------------------------------- |
| vendor_credit_id        | string | **Required** | Unique identifier of the vendor credit.        |
| vendor_credit_refund_id | string | **Required** | Unique identifier of the vendor credit refund. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Arguments
| Argument         | Type   | Required     | Description       |
| :--------------- | :----- | :----------- | :---------------- |
| date             | string | **Required** | Date of refund.   |
| amount           | double | **Required** | Amount.           |
| account_id       | string | **Required** | Account ID.       |
| refund_mode      | string | Optional     | Refund mode.      |
| reference_number | string | Optional     | Reference number. |
| exchange_rate    | double | Optional     | Exchange rate.    |
| description      | string | Optional     | Description.      |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/refunds/3000000003151?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2014-08-28",
    "refund_mode": "cash",
    "reference_number": "string",
    "amount": 13,
    "exchange_rate": 1,
    "account_id": "460000000020097",
    "description": "string"
}'
```

---

## Get vendor credit refund
Get refund of a particular vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Path Parameters
| Parameter               | Type   | Required     | Description                                    |
| :---------------------- | :----- | :----------- | :--------------------------------------------- |
| vendor_credit_id        | string | **Required** | Unique identifier of the vendor credit.        |
| vendor_credit_refund_id | string | **Required** | Unique identifier of the vendor credit refund. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/refunds/3000000003151?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete vendor credit refund
Delete a vendor credit refund.

`OAuth Scope : ZohoBooks.debitnotes.DELETE`

### Path Parameters
| Parameter               | Type   | Required     | Description                                    |
| :---------------------- | :----- | :----------- | :--------------------------------------------- |
| vendor_credit_id        | string | **Required** | Unique identifier of the vendor credit.        |
| vendor_credit_refund_id | string | **Required** | Unique identifier of the vendor credit refund. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/refunds/3000000003151?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## List vendor credit refunds
List all refunds with pagination.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Query Parameters
| Parameter          | Type    | Required     | Description                                                                     |
| :----------------- | :------ | :----------- | :------------------------------------------------------------------------------ |
| organization_id    | string  | **Required** | ID of the organization.                                                         |
| customer_id        | long    | Optional     | Search by customer ID.                                                          |
| last_modified_time | string  | Optional     | Search by last modified time.                                                   |
| sort_column        | string  | Optional     | Sort by `vendor_name`, `vendor_credit_number`, `balance`, `total`, `date`, etc. |
| page               | integer | Optional     | Page number.                                                                    |
| per_page           | integer | Optional     | Records per page.                                                               |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/refunds?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add a comment
Add a comment to an existing vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.CREATE`

### Arguments
| Argument    | Type   | Required     | Description                 |
| :---------- | :----- | :----------- | :-------------------------- |
| description | string | **Required** | Description of the Comment. |

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "description": "Credits applied to Bill 1"
}'
```

---

## List vendor credit comments & history
Get history and comments of a vendor credit.

`OAuth Scope : ZohoBooks.debitnotes.READ`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete a comment
Delete a vendor credit comment.

`OAuth Scope : ZohoBooks.debitnotes.DELETE`

### Path Parameters
| Parameter        | Type   | Required     | Description                             |
| :--------------- | :----- | :----------- | :-------------------------------------- |
| vendor_credit_id | string | **Required** | Unique identifier of the vendor credit. |
| comment_id       | string | **Required** | Unique identifier of the comment.       |

### Query Parameters
| Parameter       | Type   | Required     | Description             |
| :-------------- | :----- | :----------- | :---------------------- |
| organization_id | string | **Required** | ID of the organization. |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/vendorcredits/3000000002075/comments/3000000002089?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```