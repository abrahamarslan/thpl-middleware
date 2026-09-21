# Sales Receipt

A sales receipt is a document sent to customers when you sell them goods or services and record payment for it simultaneously. In a retail environment, this means that you only need to create one single transaction to record sales and collect payment. Sales receipts are commonly used in places where cash and sale is recorded instantly such as e-commerce websites and POS.

---

## Create a sales receipt

Create a sales receipt for immediate payment transactions.

`OAuth Scope : ZohoBooks.invoices.CREATE`

### Arguments

| Name               | Type   | Required     | Description                                                                                                                                                                                                                                                          |
| :----------------- | :----- | :----------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **customer_id**    | string | **Required** | Unique identifier for the customer                                                                                                                                                                                                                                   |
| **receipt_number** | string | Optional     | Sales receipt number (required if auto-numbering is disabled)                                                                                                                                                                                                        |
| **date**           | string | Optional     | Date of the sales receipt                                                                                                                                                                                                                                            |
| **payment_mode**   | string | **Required** | Mode through which payment was received. Allowed values: `cash`, `check`, `credit_card`, `bank_transfer`, etc.                                                                                                                                                       |
| **line_items**     | array  | Optional     | Line items for the sales receipt. <br>**Sub-Attributes:**<br><ul><li>`item_id` (string): ID of the item</li><li>`rate` (double): Rate of the item</li><li>`quantity` (double): Quantity of the item</li><li>`tax_id` (string): ID of the tax to be applied</li></ul> |
| **notes**          | string | Optional     | Notes for the sales receipt                                                                                                                                                                                                                                          |
| **terms**          | string | Optional     | Terms and conditions                                                                                                                                                                                                                                                 |

### Query Parameters

| Name                              | Type    | Required     | Description                                                                                                 |
| :-------------------------------- | :------ | :----------- | :---------------------------------------------------------------------------------------------------------- |
| **organization_id**               | string  | **Required** | ID of the organization                                                                                      |
| **ignore_auto_number_generation** | boolean | Optional     | Ignore auto sales receipt number generation for this sales receipt. This mandates the sales receipt number. |
| **can_send_in_mail**              | boolean | Optional     | Send the sales receipt to customer via email.                                                               |

### Request Example

**Body Parameters**
```json
{
    "customer_id": "460000000017138",
    "receipt_number": "SR-00001",
    "date": "2014-07-28",
    "payment_mode": "cash",
    "line_items": [
        {
            "item_id": "460000000017088",
            "rate": 120,
            "quantity": 2,
            "tax_id": "460000000017094"
        }
    ],
    "notes": "Thank you for your business",
    "terms": "Payment received in full"
}
```

**cURL**
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/salesreceipts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"customer_id":"460000000017138","receipt_number":"SR-00001","date":"2014-07-28","payment_mode":"cash","line_items":[{"item_id":"460000000017088","rate":120,"quantity":2,"tax_id":"460000000017094"}],"notes":"Thank you for your business","terms":"Payment received in full"}'
```

### Response Example (201 Created)

```json
{
    "code": 0,
    "message": "Sales Receipt Created Successfully.",
    "salesreceipt": {
        "sales_receipt_id": "460000000039129",
        "receipt_number": "SR-00001",
        "date": "2014-07-28",
        "status": "sent",
        "payment_mode": "cash",
        "customer_id": "460000000017138",
        "customer_name": "Instruments Inc",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "line_items": [
            {
                "item_id": "460000000017088",
                "name": "Hard Drive",
                "description": "500GB, USB 2.0 interface",
                "rate": 120,
                "quantity": 2,
                "unit": "Nos",
                "item_total": 240,
                "tax_id": "460000000017094",
                "tax_name": "Sales Tax",
                "tax_percentage": 10
            }
        ],
        "sub_total": 240,
        "tax_total": 24,
        "total": 264,
        "notes": "Thank you for your business",
        "terms": "Payment received in full",
        "created_time": "2014-07-28T08:29:07+0530",
        "last_modified_time": "2014-08-25T11:23:26+0530"
    }
}
```

---

## List sales receipts

List all sales receipts.

`OAuth Scope : ZohoBooks.invoices.READ`

### Query Parameters

| Name                | Type    | Required     | Description                                                                                                                                                                                                                                                                           |
| :------------------ | :------ | :----------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **organization_id** | string  | **Required** | ID of the organization                                                                                                                                                                                                                                                                |
| **receipt_number**  | string  | Optional     | Search receipt by receipt number. Filters receipts based on their unique identifier. Supports `receipt_number_startswith` and `receipt_number_contains` variants. Maximum length is 100 characters. Useful for finding specific receipts or receipts with similar numbering patterns. |
| **item_name**       | string  | Optional     | Search receipt by item name. Supports `item_name_startswith` and `item_name_contains` variants. Maximum length is 100 characters.                                                                                                                                                     |
| **sort_column**     | string  | Optional     | Specify the column field for sorting sales receipt results. Available options include `customer_name`, `receipt_number`, `date`, `total`, and `created_time`.                                                                                                                         |
| **filter_by**       | string  | Optional     | Filter sales receipts by status. Allowed Values: `ThisWeek`, `ThisMonth`, `ThisQuarter`, `ThisYear`, `PreviousDay`, `PreviousWeek`, `PreviousMonth`, `PreviousQuarter`, `PreviousYear`, `Status.All`, `Status.Draft`, `Status.Sent`                                                   |
| **customer_id**     | string  | Optional     | Filter sales receipts by specific customer identifier.                                                                                                                                                                                                                                |
| **date**            | string  | Optional     | Filter sales receipts by date. Available variants include `date_start`, `date_end`, `date_before`, and `date_after`. Default date format: `yyyy-mm-dd`.                                                                                                                               |
| **total**           | double  | Optional     | Filter sales receipts by total amount using various range operators. Available variants include `total_start`, `total_end`, `total_less_than`, `total_greater_than`.                                                                                                                  |
| **page**            | integer | Optional     | Specify the page number for paginated results retrieval. Default value is 1 for the first page.                                                                                                                                                                                       |
| **per_page**        | integer | Optional     | Specify the maximum number of sales receipt records to return per page. Default value is 200 records per page.                                                                                                                                                                        |

### Request Example

**cURL**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/salesreceipts?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "success",
    "salesreceipts": [
        {
            "sales_receipt_id": "460000000039129",
            "receipt_number": "SR-00001",
            "date": "2014-07-28",
            "status": "sent",
            "payment_mode": "cash",
            "customer_id": "460000000017138",
            "customer_name": "Instruments Inc",
            "currency_id": "460000000000097",
            "currency_code": "USD",
            "currency_symbol": "$",
            "exchange_rate": 1,
            "line_items": [
                {
                    "item_id": "460000000017088",
                    "name": "Hard Drive",
                    "description": "500GB, USB 2.0 interface",
                    "rate": 120,
                    "quantity": 2,
                    "unit": "Nos",
                    "item_total": 240,
                    "tax_id": "460000000017094",
                    "tax_name": "Sales Tax",
                    "tax_percentage": 10
                }
            ],
            "sub_total": 240,
            "tax_total": 24,
            "total": 264,
            "notes": "Thank you for your business",
            "terms": "Payment received in full",
            "created_time": "2014-07-28T08:29:07+0530",
            "last_modified_time": "2014-08-25T11:23:26+0530"
        }
    ]
}
```

---

## Update a sales receipt

Update an existing sales receipt.

`OAuth Scope : ZohoBooks.invoices.UPDATE`

### Path Parameters

| Name                 | Type   | Required     |
| :------------------- | :----- | :----------- |
| **sales_receipt_id** | string | **Required** |

### Arguments

| Name               | Type   | Required     | Description                                                                                                                                                                                                   |
| :----------------- | :----- | :----------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **customer_id**    | string | **Required** | Unique identifier for the customer                                                                                                                                                                            |
| **receipt_number** | string | Optional     | Sales receipt number                                                                                                                                                                                          |
| **date**           | string | Optional     | Date of the sales receipt                                                                                                                                                                                     |
| **payment_mode**   | string | Optional     | Mode through which payment was received                                                                                                                                                                       |
| **line_items**     | array  | Optional     | Line items for the sales receipt. <br>**Sub-Attributes:**<br><ul><li>`item_id` (string): ID of the item</li><li>`rate` (double): Rate of the item</li><li>`quantity` (double): Quantity of the item</li></ul> |
| **notes**          | string | Optional     | Notes for the sales receipt                                                                                                                                                                                   |

### Query Parameters

| Name                | Type   | Required     | Description            |
| :------------------ | :----- | :----------- | :--------------------- |
| **organization_id** | string | **Required** | ID of the organization |

### Request Example

**Body Parameters**
```json
{
    "customer_id": "460000000017138",
    "receipt_number": "SR-00001",
    "date": "2014-07-28",
    "payment_mode": "cash",
    "line_items": [
        {
            "item_id": "460000000017088",
            "rate": 120,
            "quantity": 2
        }
    ],
    "notes": "Thank you for your business"
}
```

**cURL**
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/salesreceipts/460000000039129?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"customer_id":"460000000017138","receipt_number":"SR-00001","date":"2014-07-28","payment_mode":"cash","line_items":[{"item_id":"460000000017088","rate":120,"quantity":2}],"notes":"Thank you for your business"}'
```

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "Sales Receipt Updated Successfully.",
    "salesreceipt": {
        "sales_receipt_id": "460000000039129",
        "receipt_number": "SR-00001",
        "date": "2014-07-28",
        "status": "sent",
        "payment_mode": "cash",
        "customer_id": "460000000017138",
        "customer_name": "Instruments Inc",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "line_items": [
            {
                "item_id": "460000000017088",
                "name": "Hard Drive",
                "description": "500GB, USB 2.0 interface",
                "rate": 120,
                "quantity": 2,
                "unit": "Nos",
                "item_total": 240,
                "tax_id": "460000000017094",
                "tax_name": "Sales Tax",
                "tax_percentage": 10
            }
        ],
        "sub_total": 240,
        "tax_total": 24,
        "total": 264,
        "notes": "Thank you for your business",
        "terms": "Payment received in full",
        "created_time": "2014-07-28T08:29:07+0530",
        "last_modified_time": "2014-08-25T11:23:26+0530"
    }
}
```

---

## Get a sales receipt

Get the details of a sales receipt.

`OAuth Scope : ZohoBooks.invoices.READ`

### Path Parameters

| Name                 | Type   | Required     |
| :------------------- | :----- | :----------- |
| **sales_receipt_id** | string | **Required** |

### Query Parameters

| Name                | Type   | Required     | Description                                                                                                                                      |
| :------------------ | :----- | :----------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id** | string | **Required** | ID of the organization                                                                                                                           |
| **accept**          | string | Optional     | Get the details of a particular sales receipt in formats such as json/ pdf/ html. Default format is json. Allowed Values: `json`, `pdf`, `html`. |

### Request Example

**cURL**
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/salesreceipts/460000000039129?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "success",
    "salesreceipt": {
        "sales_receipt_id": "460000000039129",
        "receipt_number": "SR-00001",
        "date": "2014-07-28",
        "status": "sent",
        "payment_mode": "cash",
        "customer_id": "460000000017138",
        "customer_name": "Instruments Inc",
        "currency_id": "460000000000097",
        "currency_code": "USD",
        "currency_symbol": "$",
        "exchange_rate": 1,
        "line_items": [
            {
                "item_id": "460000000017088",
                "name": "Hard Drive",
                "description": "500GB, USB 2.0 interface",
                "rate": 120,
                "quantity": 2,
                "unit": "Nos",
                "item_total": 240,
                "tax_id": "460000000017094",
                "tax_name": "Sales Tax",
                "tax_percentage": 10
            }
        ],
        "sub_total": 240,
        "tax_total": 24,
        "total": 264,
        "notes": "Thank you for your business",
        "terms": "Payment received in full",
        "created_time": "2014-07-28T08:29:07+0530",
        "last_modified_time": "2014-08-25T11:23:26+0530"
    }
}
```

---

## Delete a sales receipt

Delete an existing sales receipt.

`OAuth Scope : ZohoBooks.invoices.DELETE`

### Path Parameters

| Name                 | Type   | Required     |
| :------------------- | :----- | :----------- |
| **sales_receipt_id** | string | **Required** |

### Query Parameters

| Name                | Type   | Required     | Description            |
| :------------------ | :----- | :----------- | :--------------------- |
| **organization_id** | string | **Required** | ID of the organization |

### Request Example

**cURL**
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/salesreceipts/460000000039129?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "Sales Receipt Deleted Successfully."
}
```

---

## Email a sales receipt

Email a sales receipt to the customer.

`OAuth Scope : ZohoBooks.invoices.CREATE`

### Arguments

| Name            | Type   | Required     | Description                                |
| :-------------- | :----- | :----------- | :----------------------------------------- |
| **to_mail_ids** | array  | **Required** | Array of email addresses of the recipients |
| **subject**     | string | **Required** | Subject of the mail                        |
| **body**        | string | **Required** | Body of the mail                           |

### Query Parameters

| Name           | Type    | Required | Description                                |
| :------------- | :------ | :------- | :----------------------------------------- |
| **attach_pdf** | boolean | Optional | Send the sales receipt pdf with the email. |

### Request Example

**Body Parameters**
```json
{
    "to_mail_ids": [
        "john@safinstruments.com"
    ],
    "subject": "Sales Receipt from Zillium Inc",
    "body": "Please find the sales receipt attached."
}
```

**cURL**
```bash
curl --request POST \
  --url https://www.zohoapis.com/books/v3/salesreceipts/{sales_receipt_id}/email \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"to_mail_ids":["john@safinstruments.com"],"subject":"Sales Receipt from Zillium Inc","body":"Please find the sales receipt attached."}'
```

### Response Example (201 Created)

```json
{
    "code": 0,
    "message": "Your Sales Receipt has been sent."
}
```