Here is the Markdown documentation for the **Items** module, including all endpoint descriptions, attributes, and request examples.

# Items

Items are the products or services that you sell to your customers.

### End Points

| Method     | URL                            | Description                                        |
| :--------- | :----------------------------- | :------------------------------------------------- |
| **POST**   | `/items`                       | Create an Item                                     |
| **PUT**    | `/items`                       | Update an item using a custom field's unique value |
| **GET**    | `/items`                       | List items                                         |
| **GET**    | `/itemdetails`                 | Bulk fetch item details                            |
| **PUT**    | `/items/{item_id}`             | Update an item                                     |
| **GET**    | `/items/{item_id}`             | Get an item                                        |
| **DELETE** | `/items/{item_id}`             | Delete an item                                     |
| **PUT**    | `/item/{item_id}/customfields` | Update custom field in existing items              |
| **POST**   | `/items/{item_id}/active`      | Mark as active                                     |
| **POST**   | `/items/{item_id}/inactive`    | Mark as inactive                                   |

---

## Attributes

| Attribute                   | Type    | Description                                                                                                                                                         |
| :-------------------------- | :------ | :------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `item_id`                   | string  | ID of the item.                                                                                                                                                     |
| `name`                      | string  | Name of the item. Max-length [100]                                                                                                                                  |
| `status`                    | string  | Status of the item. It can be `active` or `inactive`                                                                                                                |
| `description`               | string  | Description for the item. Max-length [2000]                                                                                                                         |
| `rate`                      | double  | Price of the item.                                                                                                                                                  |
| `unit`                      | string  | If there is a measurement unit for the items you are adding.                                                                                                        |
| `tax_id`                    | string  | ID of the tax to be associated to the item. (Not applicable for US, India)                                                                                          |
| `purchase_tax_rule_id`      | string  | Id of the purchase tax rule (Mexico, Kenya, South Africa only)                                                                                                      |
| `sales_tax_rule_id`         | string  | Id of the sales tax rule (Mexico, Kenya, South Africa only)                                                                                                         |
| `tax_name`                  | string  | Name of the tax.                                                                                                                                                    |
| `hsn_or_sac`                | string  | HSN Code (India, Kenya, South Africa only)                                                                                                                          |
| `sat_item_key_code`         | string  | Add SAT Item Key Code for your goods/services (Mexico only).                                                                                                        |
| `unitkey_code`              | string  | Add Unit Key Code for your goods/services (Mexico only).                                                                                                            |
| `tax_percentage`            | string  | Percent of the tax.                                                                                                                                                 |
| `tax_type`                  | string  | Type of the tax.                                                                                                                                                    |
| `sku`                       | string  | SKU value of item, should be unique throughout the product                                                                                                          |
| `product_type`              | string  | Specify the type of an item. Allowed values: `goods`, `service`, `digital_service`. For SouthAfrica Edition: `service`, `goods`, `capital_service`, `capital_goods` |
| `item_tax_preferences`      | array   | Array containing tax details. See below. (India only)                                                                                                               |
| `custom_fields`             | array   | Custom fields for an item. See below.                                                                                                                               |
| `locations`                 | array   | Location details for stock. See below.                                                                                                                              |
| `is_taxable`                | boolean | Boolean to track the taxability of the item. (India, US, Mexico, Kenya, South Africa only)                                                                          |
| `tax_exemption_id`          | string  | ID of the tax exemption. Mandatory if `is_taxable` is false. (India, US, Mexico, Kenya, South Africa only)                                                          |
| `purchase_tax_exemption_id` | string  | ID of the purchase tax exemption. Mandatory if `is_taxable` is false. (Kenya, South Africa only)                                                                    |
| `account_id`                | string  | ID of the account to which the item has to be associated with.                                                                                                      |
| `avatax_tax_code`           | string  | Avalara Tax Code (Avalara Integration only)                                                                                                                         |
| `avatax_use_code`           | string  | Avalara Use Code (Avalara Integration only)                                                                                                                         |
| `item_type`                 | string  | Type of the item: `sales`, `purchases`, `sales_and_purchases`, `inventory`. Default: `sales`.                                                                       |
| `purchase_description`      | string  | Purchase description for the item.                                                                                                                                  |
| `purchase_rate`             | string  | Purchase price of the item.                                                                                                                                         |
| `purchase_account_id`       | string  | ID of the COGS account. Mandatory if `item_type` is purchase / sales and purchase / inventory.                                                                      |
| `inventory_account_id`      | string  | ID of the stock account. Mandatory if `item_type` is inventory.                                                                                                     |
| `vendor_id`                 | string  | Preferred vendor ID.                                                                                                                                                |
| `reorder_level`             | string  | Reorder level of the item.                                                                                                                                          |

**Sub-Attributes for `item_tax_preferences` (India Only):**

| Attribute           | Type   | Description                                  |
| :------------------ | :----- | :------------------------------------------- |
| `tax_id`            | string | ID of the tax to be associated to the item.  |
| `tax_specification` | string | Set whether the tax type is intra/interstate |

**Sub-Attributes for `custom_fields`:**

| Attribute        | Type   | Description               |
| :--------------- | :----- | :------------------------ |
| `customfield_id` | long   | ID of the custom field.   |
| `value`          | string | Value of the Custom Field |

**Sub-Attributes for `locations`:**

| Attribute                         | Type    | Description                                 |
| :-------------------------------- | :------ | :------------------------------------------ |
| `location_id`                     | string  | Location ID                                 |
| `location_name`                   | string  | Name of the location                        |
| `status`                          | string  | Status of the item (`active` or `inactive`) |
| `is_primary`                      | boolean | Mention whether the item is primary or not  |
| `location_stock_on_hand`          | string  | Current available stock in your location.   |
| `location_available_stock`        | string  | Available stock in your location.           |
| `location_actual_available_stock` | string  | Actual available stock in your location.    |

---

## Create an Item

Create a new item.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Argument               | Type    | Required | Description                                               |
| :--------------------- | :------ | :------- | :-------------------------------------------------------- |
| `name`                 | string  | Required | Name of the item. Max-length [100]                        |
| `rate`                 | double  | Required | Price of the item.                                        |
| `description`          | string  | Optional | Description for the item. Max-length [2000]               |
| `tax_id`               | string  | Optional | ID of the tax to be associated to the item.               |
| `sku`                  | string  | Optional | SKU value of item.                                        |
| `product_type`         | string  | Optional | Type of item (`goods`, `service`, etc.)                   |
| `account_id`           | string  | Optional | ID of the account.                                        |
| `item_type`            | string  | Optional | `sales`, `purchases`, `sales_and_purchases`, `inventory`. |
| `purchase_rate`        | string  | Optional | Purchase price.                                           |
| `purchase_account_id`  | string  | Optional | COGS account ID.                                          |
| `inventory_account_id` | string  | Optional | Stock account ID.                                         |
| `vendor_id`            | string  | Optional | Preferred vendor ID.                                      |
| `reorder_level`        | string  | Optional | Reorder level.                                            |
| `locations`            | array   | Optional | Stock details per location.                               |
| `custom_fields`        | array   | Optional | Custom fields for the item.                               |
| `hsn_or_sac`           | string  | Optional | HSN Code (India/Kenya/SA)                                 |
| `is_taxable`           | boolean | Optional | Taxability status.                                        |
| `tax_exemption_id`     | string  | Optional | Tax exemption ID.                                         |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/items?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"name":"Hard Drive","rate":120,"description":"500GB","tax_id":982000000037049,"locations":[{"location_id":"460000000038080","initial_stock":" ","initial_stock_rate":" "}],"tax_percentage":"70%","sku":"s12345","product_type":"goods","is_taxable":true,"custom_fields":[{"customfield_id":"46000000012845","value":"Normal"}]}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The item has been added.",
    "item": {
        "item_id": 45667789900,
        "name": "Hard Drive",
        "status": "active",
        "description": "500GB",
        "rate": 120,
        "unit": "100GB",
        "tax_id": 982000000037049,
        "tax_name": "Sales Tax",
        "tax_percentage": "70%",
        "tax_type": "tax",
        "sku": "s12345",
        "product_type": "goods",
        "custom_fields": [
            {
                "customfield_id": "46000000012845",
                "value": "Normal"
            }
        ],
        "locations": [
            {
                "location_id": "460000000038080",
                "location_name": "",
                "status": "active",
                "is_primary": false,
                "location_stock_on_hand": "",
                "location_available_stock": "",
                "location_actual_available_stock": ""
            }
        ]
    }
}
```

---

## Update an item using a custom field's unique value

Update an item using a custom field's unique value.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

Arguments are similar to creating an item.

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Headers

| Header                      | Type    | Required | Description                                        |
| :-------------------------- | :------ | :------- | :------------------------------------------------- |
| `X-Unique-Identifier-Key`   | string  | Required | Unique CustomField Api Name                        |
| `X-Unique-Identifier-Value` | string  | Required | Unique CustomField Value                           |
| `X-Upsert`                  | boolean | Optional | If true, creates a new item if no record is found. |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/items?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"name":"Hard Drive","rate":120}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Item details have been saved.",
    "item": {
        "item_id": 45667789900,
        "name": "Hard Drive",
        "status": "active",
        ...
    }
}
```

---

## List items

Get the list of all active items with pagination.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type    | Required | Description                                                                                                |
| :---------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------- |
| `organization_id` | string  | Required | ID of the organization                                                                                     |
| `name`            | string  | Optional | Search items by name. Variants: `name_startswith`, `name_contains`                                         |
| `description`     | string  | Optional | Search by description. Variants: `description_startswith`, `description_contains`                          |
| `rate`            | string  | Optional | Search by rate. Variants: `rate_less_than`, `rate_less_equals`, `rate_greater_than`, `rate_greater_equals` |
| `tax_id`          | string  | Optional | Search items by tax id.                                                                                    |
| `tax_name`        | string  | Optional | Search items by tax name.                                                                                  |
| `is_taxable`      | boolean | Optional | Filter by taxability.                                                                                      |
| `account_id`      | string  | Optional | Filter by account ID.                                                                                      |
| `filter_by`       | string  | Optional | Filter by status: `Status.All`, `Status.Active`, `Status.Inactive`.                                        |
| `search_text`     | string  | Optional | Search by name or description.                                                                             |
| `sort_column`     | string  | Optional | Sort items: `name`, `rate`, `tax_name`.                                                                    |
| `page`            | integer | Optional | Page number. Default: 1.                                                                                   |
| `per_page`        | integer | Optional | Records per page. Default: 200.                                                                            |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/items?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "items": [
        {
            "item_id": 45667789900,
            "name": "Hard Drive",
            "rate": 120,
            "status": "active",
             ...
        },
        ...
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false,
        "report_name": "Items",
        "sort_column": "string",
        "sort_order": "A"
    }
}
```

---

## Bulk fetch item details

Fetch item details for the mentioned item IDs.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type   | Required | Description                          |
| :---------------- | :----- | :------- | :----------------------------------- |
| `item_ids`        | string | Required | List of item ids separated by comma. |
| `organization_id` | string | Required | ID of the organization.              |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/itemdetails?item_ids=4815000000044208,4815000000044274&organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "items": [
        {
            "item_id": 45667789900,
            "name": "Hard Drive",
            ...
        },
        ...
    ]
}
```

---

## Update an item

Update the details of an item.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Arguments

The arguments are the same as creating an item (e.g., `name`, `rate`, `description`, etc.).

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/items/45667789900?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"name":"Hard Drive","rate":120}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Item details have been saved.",
    "item": {
        "item_id": 45667789900,
        "name": "Hard Drive",
        ...
    }
}
```

---

## Get an item

Details of an existing item.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/items/45667789900?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "item": {
        "item_id": 45667789900,
        "name": "Hard Drive",
        ...
    }
}
```

---

## Delete an item

Delete the item created. Items that are part of transaction cannot be deleted.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/items/45667789900?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The item has been deleted."
}
```

---

## Update custom field in existing items

Update the value of the custom field in existing items.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Arguments

| Argument         | Type   | Required | Description                |
| :--------------- | :----- | :------- | :------------------------- |
| `customfield_id` | long   | Optional | Custom field ID.           |
| `value`          | string | Optional | Value of the Custom Field. |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/item/45667789900/customfields?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '[{"customfield_id":"46000000012845","value":"Normal"}]'
```

### Response Example

```json
{
    "code": 0,
    "message": "Custom Fields Updated Successfully"
}
```

---

## Mark as active

Mark an inactive item as active.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/items/45667789900/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The item has been marked as active."
}
```

---

## Mark as inactive

Mark an active item as inactive.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `item_id` | string | Required | Unique identifier of the item. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/items/45667789900/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The item has been marked as inactive."
}
```