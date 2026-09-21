Here is the converted documentation in Markdown format.

# Purchase Order

A purchase order is an official document that a buyer issues to a seller, indicating relevant information about what they want to buy, the quantity, the price agreed for that particular product or service.

### End Points

| Method     | URL                                                          | Description                                                 |
| :--------- | :----------------------------------------------------------- | :---------------------------------------------------------- |
| **POST**   | `/purchaseorders`                                            | Create a purchase order                                     |
| **PUT**    | `/purchaseorders`                                            | Update a purchase order using a custom field's unique value |
| **GET**    | `/purchaseorders`                                            | List purchase orders                                        |
| **PUT**    | `/purchaseorders/{purchase_order_id}`                        | Update a purchase order                                     |
| **GET**    | `/purchaseorders/{purchase_order_id}`                        | Get a purchase order                                        |
| **DELETE** | `/purchaseorders/{purchase_order_id}`                        | Delete purchase order                                       |
| **PUT**    | `/purchaseorder/{purchaseorder_id}/customfields`             | Update custom field in existing purchaseorders              |
| **POST**   | `/purchaseorders/{purchaseorder_id}/status/open`             | Mark a purchase order as open                               |
| **POST**   | `/purchaseorders/{purchaseorder_id}/status/billed`           | Mark as billed                                              |
| **POST**   | `/purchaseorders/{purchaseorder_id}/status/cancelled`        | Cancel a purchase order                                     |
| **POST**   | `/purchaseorders/{purchaseorder_id}/submit`                  | Submit a purchase order for approval                        |
| **POST**   | `/purchaseorders/{purchaseorder_id}/approve`                 | Approve a purchase order                                    |
| **POST**   | `/purchaseorders/{purchaseorder_id}/email`                   | Email a purchase order                                      |
| **GET**    | `/purchaseorders/{purchaseorder_id}/email`                   | Get purchase order email content                            |
| **PUT**    | `/purchaseorders/{purchaseorder_id}/address/billing`         | Update billing address                                      |
| **GET**    | `/purchaseorders/templates`                                  | List purchase order templates                               |
| **PUT**    | `/purchaseorders/{purchaseorder_id}/templates/{template_id}` | Update purchase order template                              |
| **POST**   | `/purchaseorders/{purchaseorder_id}/attachment`              | Add attachment to a purchase order                          |
| **PUT**    | `/purchaseorders/{purchaseorder_id}/attachment`              | Update attachment preference                                |
| **GET**    | `/purchaseorders/{purchaseorder_id}/attachment`              | Get a purchase order attachment                             |
| **DELETE** | `/purchaseorders/{purchaseorder_id}/attachment`              | Delete an attachment                                        |
| **POST**   | `/purchaseorders/{purchaseorder_id}/comments`                | Add comment                                                 |
| **GET**    | `/purchaseorders/{purchaseorder_id}/comments`                | List purchase order comments & history                      |
| **PUT**    | `/purchaseorders/{purchaseorder_id}/comments/{comment_id}`   | Update comment                                              |
| **DELETE** | `/purchaseorders/{purchaseorder_id}/comments/{comment_id}`   | Delete a comment                                            |
| **POST**   | `/purchaseorders/{purchaseorder_id}/reject`                  | Reject Purchase Order                                       |

---

## Attributes

| Attribute                      | Data Type | Description                                                                                                                        |
| :----------------------------- | :-------- | :--------------------------------------------------------------------------------------------------------------------------------- |
| **purchaseorder_id**           | string    | The unique identifier of the purchase order.                                                                                       |
| **documents**                  | array     | Array of documents attached to the purchase order. Contains `document_id` and `file_name`.                                         |
| **vat_treatment**              | string    | **[UK only]** VAT treatment for the purchase order. Values: `uk`, `eu_vat_registered`, `overseas`.                                 |
| **gst_no**                     | string    | **[India only]** 15 digit GST identification number of the vendor.                                                                 |
| **gst_treatment**              | string    | **[India only]** GST treatment of the contact. Values: `business_gst`, `business_none`, `overseas`, `consumer`.                    |
| **tax_treatment**              | string    | **[GCC, Mexico, Kenya, South Africa only]** VAT treatment. Values vary by region (e.g., `vat_registered`, `non_gcc`, `non_kenya`). |
| **is_pre_gst**                 | boolean   | **[India only]** Applicable for transactions that fall before July 1, 2017.                                                        |
| **source_of_supply**           | string    | **[India only]** Place from where the goods/services are supplied.                                                                 |
| **destination_of_supply**      | string    | **[India only]** Place where the goods/services are supplied to.                                                                   |
| **place_of_supply**            | string    | **[GCC only]** The place of supply where transaction occurred. Supported codes for UAE/GCC.                                        |
| **pricebook_id**               | string    | Unique identifier of the pricebook used.                                                                                           |
| **pricebook_name**             | string    | Name of the pricebook.                                                                                                             |
| **is_reverse_charge_applied**  | boolean   | **[India only]** Applicable for transactions where you pay reverse charge.                                                         |
| **purchaseorder_number**       | string    | Unique identifier for the purchase order (Mandatory if auto-numbering is disabled).                                                |
| **date**                       | string    | The date when the purchase order was created (YYYY-MM-DD).                                                                         |
| **expected_delivery_date**     | string    | The expected delivery date of goods/services (YYYY-MM-DD).                                                                         |
| **discount**                   | string    | The discount amount or percentage applied to the total.                                                                            |
| **discount_account_id**        | string    | ID of the account where discount amount is recorded.                                                                               |
| **is_discount_before_tax**     | boolean   | True if discount is applied before tax, False otherwise.                                                                           |
| **reference_number**           | string    | External reference number for the purchase order.                                                                                  |
| **status**                     | string    | Status of the Purchase Order.                                                                                                      |
| **vendor_id**                  | string    | Unique identifier of the vendor.                                                                                                   |
| **vendor_name**                | string    | Name of the Vendor.                                                                                                                |
| **crm_owner_id**               | string    | Unique identifier of the CRM owner assigned.                                                                                       |
| **contact_persons_associated** | array     | Contact Persons associated with the transaction. Contains details like `contact_person_id`, `email`, `phone`, etc.                 |
| **currency_id**                | string    | Unique identifier of the currency.                                                                                                 |
| **currency_code**              | string    | Code of the Currency.                                                                                                              |
| **currency_symbol**            | string    | Symbol of the Currency.                                                                                                            |
| **exchange_rate**              | double    | Exchange rate used to convert to base currency.                                                                                    |
| **delivery_date**              | string    | The expected delivery date.                                                                                                        |
| **is_emailed**                 | boolean   | Check if the purchase order is emailed.                                                                                            |
| **is_inclusive_tax**           | boolean   | **[Not applicable for US]** True if line item rates include tax.                                                                   |
| **location_id**                | string    | Unique identifier of the business location/branch.                                                                                 |
| **location_name**              | string    | Name of the location.                                                                                                              |
| **line_items**                 | array     | List of items. Includes `item_id`, `line_item_id`, `sku`, `rate`, `quantity`, `tax_id`, etc.                                       |
| **sub_total**                  | double    | Sub Total of the Purchase Order.                                                                                                   |
| **tax_total**                  | double    | Total Tax amount.                                                                                                                  |
| **total**                      | double    | Total of the Purchase Order.                                                                                                       |
| **taxes**                      | array     | Array of taxes applied.                                                                                                            |
| **acquisition_vat_summary**    | array     | **[UK, Europe only]** Summary of VAT Acquisition.                                                                                  |
| **acquisition_vat_total**      | double    | **[UK, Europe only]** Total VAT Acquisition.                                                                                       |
| **reverse_charge_vat_summary** | array     | **[UK, Europe only]** Summary of Reverse Charge.                                                                                   |
| **reverse_charge_vat_total**   | double    | **[UK, Europe only]** Total Reverse Charge.                                                                                        |
| **billing_address**            | object    | Address object containing `address`, `city`, `state`, `zip`, `country`, `attention`, etc.                                          |
| **notes**                      | string    | Additional information or comments.                                                                                                |
| **terms**                      | string    | Terms and conditions.                                                                                                              |
| **ship_via**                   | string    | Shipment Preference.                                                                                                               |
| **ship_via_id**                | string    | ID of the Shipment Preference.                                                                                                     |
| **attention**                  | string    | Name/Designation of the contact person for delivery.                                                                               |
| **delivery_org_address_id**    | string    | ID of the organization address for delivery.                                                                                       |
| **delivery_customer_id**       | string    | ID of the customer for drop-shipping scenarios.                                                                                    |
| **delivery_address**           | object    | Delivery address details.                                                                                                          |
| **price_precision**            | integer   | Price Precision for the values.                                                                                                    |
| **custom_fields**              | array     | Custom fields. Contains `customfield_id` and `value`.                                                                              |
| **attachment_name**            | string    | Name of the Attachment.                                                                                                            |
| **can_send_in_mail**           | boolean   | Send attachment with email.                                                                                                        |
| **template_id**                | string    | ID of the PDF template used.                                                                                                       |
| **template_name**              | string    | Name of the template.                                                                                                              |
| **page_width**                 | string    | Width of the page.                                                                                                                 |
| **page_height**                | string    | Height of the page.                                                                                                                |
| **orientation**                | string    | Orientation of the page.                                                                                                           |
| **template_type**              | string    | Type of the template.                                                                                                              |
| **created_time**               | string    | Created Time.                                                                                                                      |
| **created_by_id**              | string    | ID of the User who created the PO.                                                                                                 |
| **last_modified_time**         | string    | Last Modified Time.                                                                                                                |
| **can_mark_as_bill**           | boolean   | Can the PO be marked as billed.                                                                                                    |
| **can_mark_as_unbill**         | boolean   | Can the PO be marked as unbilled.                                                                                                  |

---

## Create a purchase order

Create a purchase order for your vendor.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Arguments

| Argument                       | Type    | Required                             | Description                                                                                |
| :----------------------------- | :------ | :----------------------------------- | :----------------------------------------------------------------------------------------- |
| **vendor_id**                  | string  | Required                             | Unique identifier of the vendor.                                                           |
| **currency_id**                | string  | Optional                             | Unique identifier of the currency.                                                         |
| **contact_persons_associated** | array   | Optional                             | Contact Persons associated with the transaction.                                           |
| **purchaseorder_number**       | string  | Optional                             | Unique identifier for the purchase order. Mandatory if auto-number generation is disabled. |
| **gst_treatment**              | string  | Optional                             | **[India only]** GST treatment (e.g., `business_gst`).                                     |
| **tax_treatment**              | string  | Optional                             | **[GCC, Mexico, Kenya, South Africa only]** VAT treatment.                                 |
| **gst_no**                     | string  | Optional                             | **[India only]** 15 digit GST identification number.                                       |
| **source_of_supply**           | string  | Optional                             | **[India only]** Place of supply origin.                                                   |
| **destination_of_supply**      | string  | Optional                             | **[India only]** Place of supply destination.                                              |
| **place_of_supply**            | string  | Optional                             | **[GCC only]** Place of supply (e.g., `DU` for Dubai).                                     |
| **pricebook_id**               | string  | Optional                             | ID of the pricebook to be used.                                                            |
| **reference_number**           | string  | Optional                             | External reference number.                                                                 |
| **billing_address_id**         | long    | Optional                             | ID of the billing address.                                                                 |
| **crm_owner_id**               | string  | Optional                             | ID of the CRM owner.                                                                       |
| **crm_custom_reference_id**    | long    | Optional                             | ID of CRM Custom Reference.                                                                |
| **template_id**                | string  | Optional                             | ID of the PDF template.                                                                    |
| **date**                       | string  | Creation date (YYYY-MM-DD).          |
| **delivery_date**              | string  | Expected delivery date (YYYY-MM-DD). |
| **due_date**                   | string  | Due date.                            |
| **exchange_rate**              | double  | Optional                             | Currency exchange rate.                                                                    |
| **discount**                   | string  | Optional                             | Discount amount or percentage.                                                             |
| **discount_account_id**        | string  | Optional                             | Account ID for discount recording.                                                         |
| **is_discount_before_tax**     | boolean | Optional                             | Apply discount before tax.                                                                 |
| **is_inclusive_tax**           | boolean | Optional                             | **[Not applicable for US]** Rates include tax.                                             |
| **notes**                      | string  | Optional                             | Notes for the PO.                                                                          |
| **notes_default**              | string  | Optional                             | Default notes.                                                                             |
| **terms**                      | string  | Optional                             | Terms and conditions.                                                                      |
| **terms_default**              | string  | Optional                             | Default terms.                                                                             |
| **ship_via**                   | string  | Optional                             | Shipment Preference.                                                                       |
| **delivery_org_address_id**    | string  | Optional                             | Organization address ID for delivery.                                                      |
| **delivery_customer_id**       | string  | Optional                             | Customer ID for delivery.                                                                  |
| **attention**                  | string  | Optional                             | Attention contact name.                                                                    |
| **vat_treatment**              | string  | Optional                             | **[UK only]** VAT treatment.                                                               |
| **is_update_customer**         | string  | Optional                             | Check if customer should be updated.                                                       |
| **salesorder_id**              | long    | Optional                             | Linked Sales Order ID.                                                                     |
| **location_id**                | string  | Optional                             | Location ID.                                                                               |
| **line_items**                 | array   | Required                             | Line items of the purchase order.                                                          |
| **custom_fields**              | array   | Optional                             | Custom fields.                                                                             |
| **documents**                  | array   | Optional                             | Array of attached documents.                                                               |

### Query Parameters

| Parameter                         | Type    | Required | Description                                                                   |
| :-------------------------------- | :------ | :------- | :---------------------------------------------------------------------------- |
| **organization_id**               | string  | Required | ID of the organization                                                        |
| **attachment**                    | binary  | Optional | Allowed Extensions: gif, png, jpeg, jpg, bmp, pdf, xls, xlsx, doc, docx.      |
| **ignore_auto_number_generation** | boolean | Optional | Ignore auto purchase order number generation (mandates purchaseorder_number). |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"vendor_id":"460000000026049","purchaseorder_number":"PO-00001","line_items":[{"item_id":"460000000027009","rate":112,"quantity":1}]}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Purchase Order has been added.",
    "purchaseorder": {
        "purchaseorder_id": "460000000062001",
        "purchaseorder_number": "PO-00001",
        "date": "2014-02-10",
        "status": "draft",
        "vendor_name": "string",
        "total": 112.00
    }
}
```

---

## Update a purchase order using a custom field's unique value

Update a purchase order by identifying it via a unique custom field value.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Headers

| Header                        | Type    | Required | Description                                                  |
| :---------------------------- | :------ | :------- | :----------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string  | Required | Unique CustomField Api Name                                  |
| **X-Unique-Identifier-Value** | string  | Required | Unique CustomField Value                                     |
| **X-Upsert**                  | boolean | Optional | If true, creates a new purchase order if no record is found. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

---

## List purchase orders

List all purchase orders.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Query Parameters

| Parameter                | Type    | Required | Description                                                                                       |
| :----------------------- | :------ | :------- | :------------------------------------------------------------------------------------------------ |
| **organization_id**      | string  | Required | ID of the organization                                                                            |
| **purchaseorder_number** | string  | Optional | Search by PO number.                                                                              |
| **reference_number**     | string  | Optional | Search by reference number.                                                                       |
| **date**                 | string  | Optional | Search by date (YYYY-MM-DD).                                                                      |
| **status**               | string  | Optional | Search by status (`draft`, `open`, `billed`, `cancelled`).                                        |
| **item_description**     | string  | Optional | Search by item description.                                                                       |
| **vendor_name**          | string  | Optional | Search by vendor name.                                                                            |
| **total**                | double  | Optional | Search by total amount.                                                                           |
| **vendor_id**            | string  | Optional | Search by vendor ID.                                                                              |
| **last_modified_time**   | string  | Optional | Search by last modified time.                                                                     |
| **item_id**              | string  | Optional | Search by item ID.                                                                                |
| **filter_by**            | string  | Optional | Filter status (`Status.All`, `Status.Draft`, `Status.Open`, `Status.Billed`, `Status.Cancelled`). |
| **search_text**          | string  | Optional | General search.                                                                                   |
| **sort_column**          | string  | Optional | Sort by column (`vendor_name`, `purchaseorder_number`, etc.).                                     |
| **custom_field**         | string  | Optional | Search by custom field.                                                                           |
| **page**                 | integer | Optional | Page number (Default: 1).                                                                         |
| **per_page**             | integer | Optional | Records per page (Default: 200).                                                                  |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "purchaseorders": [
        {
            "purchaseorder_id": "460000000062001",
            "vendor_name": "string",
            "status": "draft",
            "purchaseorder_number": "PO-00001",
            "date": "2014-02-10",
            "total": 40
        }
    ]
}
```

---

## Update a purchase order

Update an existing purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **purchase_order_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter                         | Type    | Required | Description                                                              |
| :-------------------------------- | :------ | :------- | :----------------------------------------------------------------------- |
| **organization_id**               | string  | Required | ID of the organization                                                   |
| **attachment**                    | binary  | Optional | Allowed Extensions: gif, png, jpeg, jpg, bmp, pdf, xls, xlsx, doc, docx. |
| **ignore_auto_number_generation** | boolean | Optional | Ignore auto number generation.                                           |

### Arguments
(Same as Create Purchase Order)

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"vendor_id":"460000000026049","purchaseorder_number":"PO-00001","line_items":[{"item_id":"460000000027009","rate":112,"quantity":1}]}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Purchase Order has been updated.",
    "purchaseorder": {
        "purchaseorder_id": "460000000062001",
        "purchaseorder_number": "PO-00001",
        "status": "draft"
    }
}
```

---

## Get a purchase order

Get the details of a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **purchase_order_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type    | Required | Description                                     |
| :------------------ | :------ | :------- | :---------------------------------------------- |
| **organization_id** | string  | Required | ID of the organization                          |
| **print**           | boolean | Optional | Print the exported pdf.                         |
| **accept**          | string  | Optional | Format: `json`, `pdf`, `html`. Default: `json`. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "purchaseorder": {
        "purchaseorder_id": "460000000062001",
        "purchaseorder_number": "PO-00001",
        "vendor_id": "460000000026049",
        "status": "draft",
        "total": 40
    }
}
```

---

## Delete purchase order

Delete an existing purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.DELETE`

### Path Parameters

| Parameter             | Type   | Required | Description                              |
| :-------------------- | :----- | :------- | :--------------------------------------- |
| **purchase_order_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update custom field in existing purchaseorders

Update the value of the custom field in existing purchaseorders.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument           | Type   | Required | Description               |
| :----------------- | :----- | :------- | :------------------------ |
| **customfield_id** | long   | Optional |                           |
| **value**          | string | Optional | Value of the Custom Field |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorder/460000000062001/customfields?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '[{"customfield_id":"46000000012845","value":"Normal"}]'
```

---

## Mark a purchase order as open

Mark a draft purchase order as open.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/status/open?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Mark as billed

Mark a purchase order as billed.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/status/billed?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Cancel a purchase order

Mark a purchase order as cancelled.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/status/cancelled?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Submit a purchase order for approval

Submit a purchase order for approval.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/submit?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Approve a purchase order

Approve a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/approve?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Email a purchase order

Email a purchase order to the vendor.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type    | Required | Description                    |
| :------------------ | :------ | :------- | :----------------------------- |
| **organization_id** | string  | Required | ID of the organization         |
| **attachments**     | binary  | Optional | Files to be attached.          |
| **send_attachment** | boolean | Optional | Send PO attachment with email. |
| **file_name**       | string  | Optional | Name of the file.              |

### Arguments

| Argument                   | Type    | Required | Description                               |
| :------------------------- | :------ | :------- | :---------------------------------------- |
| **to_mail_ids**            | array   | Required | Array of email address of the recipients. |
| **subject**                | string  | Optional | Subject of the mail.                      |
| **body**                   | string  | Required | Body of the mail.                         |
| **send_from_org_email_id** | boolean | Optional | Trigger from org email.                   |
| **from_address_id**        | long    | Optional | ID of From Address.                       |
| **cc_mail_ids**            | array   | Optional | CC email addresses.                       |
| **bcc_mail_ids**           | array   | Optional | BCC email addresses.                      |
| **mail_documents**         | array   | Optional | Array of document IDs to attach.          |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"to_mail_ids":["willsmith@bowmanfurniture.com"],"subject":"Purchase Order from Zillium Inc (PO #: PO-00001)","body":"Dear Bowman and Co, <br><br>The purchase order (PO-00001) is attached with this email."}'
```

---

## Get purchase order email content

Get the email content of a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter             | Type   | Required | Description                 |
| :-------------------- | :----- | :------- | :-------------------------- |
| **organization_id**   | string | Required | ID of the organization      |
| **email_template_id** | string | Optional | Specific email template ID. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/email?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update billing address

Updates the billing address for this purchase order alone.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument               | Type   | Required | Description                     |
| :--------------------- | :----- | :------- | :------------------------------ |
| **address**            | string | Optional | Address line.                   |
| **city**               | string | Optional | City.                           |
| **state**              | string | Optional | State.                          |
| **zip**                | string | Optional | ZIP Code.                       |
| **country**            | string | Optional | Country.                        |
| **fax**                | string | Optional | Fax Number.                     |
| **attention**          | string | Optional | Attention name.                 |
| **is_update_customer** | string | Optional | Update customer record as well. |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/address/billing?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"address":"string","city":"string","state":"string"}'
```

---

## List purchase order templates

Get all purchase order pdf templates.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/templates?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update purchase order template

Update the pdf template associated with the purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description                                       |
| :------------------- | :----- | :------- | :------------------------------------------------ |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order.          |
| **template_id**      | string | Required | Unique identifier of the purchase order template. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/templates/460000000011003?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add attachment to a purchase order

Attach a file to a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description                                                              |
| :------------------ | :----- | :------- | :----------------------------------------------------------------------- |
| **organization_id** | string | Required | ID of the organization                                                   |
| **attachment**      | binary | Optional | Allowed Extensions: gif, png, jpeg, jpg, bmp, pdf, xls, xlsx, doc, docx. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update attachment preference

Set whether you want to send the attached file while emailing the purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter            | Type    | Required | Description                                                          |
| :------------------- | :------ | :------- | :------------------------------------------------------------------- |
| **organization_id**  | string  | Required | ID of the organization                                               |
| **can_send_in_mail** | boolean | Required | Boolean to send the attachment with the purchase order when emailed. |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/attachment?organization_id=10234695&can_send_in_mail=false' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Get a purchase order attachment

Returns the file attached to the purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type    | Required | Description                          |
| :------------------ | :------ | :------- | :----------------------------------- |
| **organization_id** | string  | Required | ID of the organization               |
| **preview**         | boolean | Optional | Get the thumbnail of the attachment. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete an attachment

Delete the file attached to the purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.DELETE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add comment

Add a comment for a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.CREATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument                   | Type   | Required | Description                              |
| :------------------------- | :----- | :------- | :--------------------------------------- |
| **description**            | string | Required | The description of the comment.          |
| **expected_delivery_date** | string | Required | The expected delivery date (YYYY-MM-DD). |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"description":"This is a comment.","expected_delivery_date":"string"}'
```

---

## List purchase order comments & history

Get the complete history and comments of purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.READ`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update comment

Update an existing comment of a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |
| **comment_id**       | string | Required | Unique identifier of the comment.        |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

| Argument                   | Type   | Required | Description                              |
| :------------------------- | :----- | :------- | :--------------------------------------- |
| **description**            | string | Optional | The description of the comment.          |
| **expected_delivery_date** | string | Optional | The expected delivery date (YYYY-MM-DD). |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/comments/460000000012345?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"description":"This is a comment.","expected_delivery_date":"string"}'
```

---

## Delete a comment

Delete a purchase order comment.
`OAuth Scope : ZohoBooks.purchaseorders.DELETE`

### Path Parameters

| Parameter            | Type   | Required | Description                              |
| :------------------- | :----- | :------- | :--------------------------------------- |
| **purchaseorder_id** | string | Required | Unique identifier of the purchase order. |
| **comment_id**       | string | Required | Unique identifier of the comment.        |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000062001/comments/460000000012345?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Reject Purchase Order

Reject a purchase order.
`OAuth Scope : ZohoBooks.purchaseorders.UPDATE`

### Path Parameters

| Parameter            | Type   | Required | Description |
| :------------------- | :----- | :------- | :---------- |
| **purchaseorder_id** | string | Required |             |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/purchaseorders/460000000012345/reject?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```