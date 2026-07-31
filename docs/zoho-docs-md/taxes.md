# Taxes

Your business' financials are affected by regulatory taxes and each organization has different country specific taxes to adhere to.

### Attribute

| Attribute                       | Data Type | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| :------------------------------ | :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tax_id                          | string    | ID of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| tax_name                        | string    | Name of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| tax_percentage                  | double    | Number of Percentage Taxable.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| tax_type                        | string    | Type to determine whether it is a simple or compound tax. <br>Allowed Values: `tax`, `compound_tax`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| tax_factor                      | string    | **(Mexico only)** Type of Tax Factor. <br>Allowed values: `rate`, `share`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tds_payable_account_id          | string    | **(Mexico only)** Input Tax ID. The amount of money charged to you as Tax on your purchases.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| tax_authority_id                | string    | **(United States, Mexico only)** ID of the tax authority. Tax authority depends on the location of the customer. For example, if the customer is located in NY, then the tax authority is NY tax authority.                                                                                                                                                                                                                                                                                                                                                                                                            |
| tax_authority_name              | string    | Name of the Tax Authority                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| is_value_added                  | boolean   | Check if Tax is Value Added                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| tax_specific_type               | string    | **(India, Mexico, South Africa only)** <br>Type of Tax For **Indian** Edition. Allowed Values : `igst`, `cgst`, `sgst`, `nil`, `cess`.<br>Type of Tax for **Mexico** Edition. Allowed Values : `isr`, `iva`, `ieps`.<br>Type of Tax for **South Africa** Edition. Allowed Values :<br>`soa_less_than_28d` - Supply of accommodation not exceeding 28 days,<br>`soa_more_than_28d` - Supply of accommodation exceeding than 28 days,<br>`ciu_prev_tax_supply` - Change in use (Taxable supplies),<br>`ciu_prev_nontax_supply` - Change in use (Non-Taxable supplies),<br>`export_of_shg` - Export of second hand goods. |
| country                         | string    | **(United Kingdom, Europe, Global only)** Country to which the tax belongs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| country_code                    | string    | **(United Kingdom, Europe, GCC, Global only)** Two letter country code for the EU country to which the tax belongs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| purchase_tax_expense_account_id | long      | **(Australia, Canada only)** Account ID in which Purchase Tax will be Computed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |

### Example

```json
{
    "tax_id": "982000000566009",
    "tax_name": "Sales Group",
    "tax_percentage": 10.5,
    "tax_type": "tax",
    "tax_factor": "rate",
    "tds_payable_account_id": "132086000000107337",
    "tax_authority_id": "460000000066001",
    "tax_authority_name": "Illinois Department of Revenue",
    "is_value_added": false,
    "tax_specific_type": "string",
    "country": "string",
    "country_code": "UK",
    "purchase_tax_expense_account_id": 0
}
```

---

## Create a tax

Create a tax which can be associated with an item.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Attribute                       | Data Type | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| :------------------------------ | :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tax_name                        | string    | Name of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| tax_percentage                  | double    | Number of Percentage Taxable.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| tax_type                        | string    | Type to determine whether it is a simple or compound tax. <br>Allowed Values: `tax`, `compound_tax`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| tax_factor                      | string    | **(Mexico only)** Type of Tax Factor. <br>Allowed values: `rate`, `share`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_specific_type               | string    | **(India, Mexico, South Africa only)** <br>Type of Tax For **Indian** Edition. Allowed Values : `igst`, `cgst`, `sgst`, `nil`, `cess`.<br>Type of Tax for **Mexico** Edition. Allowed Values : `isr`, `iva`, `ieps`.<br>Type of Tax for **South Africa** Edition. Allowed Values :<br>`soa_less_than_28d` - Supply of accommodation not exceeding 28 days,<br>`soa_more_than_28d` - Supply of accommodation exceeding than 28 days,<br>`ciu_prev_tax_supply` - Change in use (Taxable supplies),<br>`ciu_prev_nontax_supply` - Change in use (Non-Taxable supplies),<br>`export_of_shg` - Export of second hand goods. |
| tax_authority_name              | string    | Name of the Tax Authority                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_authority_id                | string    | **(United States, Mexico only)** ID of the tax authority. Tax authority depends on the location of the customer. For example, if the customer is located in NY, then the tax authority is NY tax authority.                                                                                                                                                                                                                                                                                                                                                                                                            |
| country_code                    | string    | **(United Kingdom, Europe, GCC, Global only)** Two letter country code for the EU country to which the tax belongs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| purchase_tax_expense_account_id | long      | **(Australia, Canada only)** Account ID in which Purchase Tax will be Computed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| is_value_added                  | boolean   | Check if Tax is Value Added                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| update_recurring_invoice        | boolean   | Check if recurring invoice should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| update_recurring_expense        | boolean   | Check if recurring expenses should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| update_draft_invoice            | boolean   | Check if Draft Invoices should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| update_recurring_bills          | boolean   | Check if Recurring Bills should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| update_draft_so                 | boolean   | Check if Draft Sales Orders should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| update_subscription             | boolean   | Check if Subscriptions should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| update_project                  | boolean   | Check if Projects should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| is_editable                     | boolean   | Check if tax is editable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/taxes?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_name": "Sales Group",
    "tax_percentage": 10.5,
    "tax_type": "tax",
    "tax_factor": "rate",
    "tax_specific_type": "string",
    "tax_authority_name": "Illinois Department of Revenue",
    "tax_authority_id": "460000000066001",
    "country_code": "UK",
    "purchase_tax_expense_account_id": 0,
    "is_value_added": false,
    "update_recurring_invoice": false,
    "update_recurring_expense": false,
    "update_draft_invoice": false,
    "update_recurring_bills": false,
    "update_draft_so": false,
    "update_subscription": false,
    "update_project": false,
    "is_editable": true
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The tax has been added.",
    "tax": [
        {
            "tax_id": "982000000566009",
            "tax_name": "Sales Group",
            "tax_percentage": 10.5,
            "tax_type": "tax",
            "tax_factor": "rate",
            "tds_payable_account_id": "132086000000107337",
            "tax_authority_id": "460000000066001",
            "tax_authority_name": "Illinois Department of Revenue",
            "is_value_added": false,
            "tax_specific_type": "string",
            "country": "string",
            "country_code": "UK",
            "purchase_tax_expense_account_id": 0
        }
    ]
}
```

---

## List taxes

List of simple and compound taxes with pagination.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Attribute       | Data Type | Description                                                     |
| :-------------- | :-------- | :-------------------------------------------------------------- |
| organization_id | string    | **(Required)** ID of the organization                           |
| page            | integer   | Page number to be fetched. Default value is 1.                  |
| per_page        | integer   | Number of records to be fetched per page. Default value is 200. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxes?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "taxes": [
        {
            "tax_id": "982000000566009",
            "tax_name": "Sales Group",
            "tax_percentage": 10.5,
            "tax_type": "tax",
            "tax_factor": "rate",
            "tax_specific_type": "string",
            "tax_authority_id": "460000000066001",
            "tax_authority_name": "Illinois Department of Revenue",
            "is_value_added": false,
            "is_default_tax": true,
            "is_editable": true,
            "output_tax_account_name": "string",
            "purchase_tax_account_name": "string",
            "tax_account_id": "132086000000107333",
            "purchase_tax_account_id": "132086000000107337"
        }
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false,
        "report_name": "Taxes",
        "applied_filter": "Status.All",
        "sort_column": "created_time",
        "sort_order": "D"
    }
}
```

---

## Update a tax

Update the details of a simple or compound tax.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Attribute                       | Data Type | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| :------------------------------ | :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| tax_id                          | string    | ID of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| tax_name                        | string    | Name of the Tax                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| tax_percentage                  | double    | Number of Percentage Taxable.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| tax_type                        | string    | Type to determine whether it is a simple or compound tax. <br>Allowed Values: `tax`, `compound_tax`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| tax_factor                      | string    | **(Mexico only)** Type of Tax Factor. <br>Allowed values: `rate`, `share`                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_specific_type               | string    | **(India, Mexico, South Africa only)** <br>Type of Tax For **Indian** Edition. Allowed Values : `igst`, `cgst`, `sgst`, `nil`, `cess`.<br>Type of Tax for **Mexico** Edition. Allowed Values : `isr`, `iva`, `ieps`.<br>Type of Tax for **South Africa** Edition. Allowed Values :<br>`soa_less_than_28d` - Supply of accommodation not exceeding 28 days,<br>`soa_more_than_28d` - Supply of accommodation exceeding than 28 days,<br>`ciu_prev_tax_supply` - Change in use (Taxable supplies),<br>`ciu_prev_nontax_supply` - Change in use (Non-Taxable supplies),<br>`export_of_shg` - Export of second hand goods. |
| tax_authority_name              | string    | Name of the Tax Authority                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| tax_authority_id                | string    | **(United States, Mexico only)** ID of the tax authority. Tax authority depends on the location of the customer. For example, if the customer is located in NY, then the tax authority is NY tax authority.                                                                                                                                                                                                                                                                                                                                                                                                            |
| country_code                    | string    | **(United Kingdom, Europe, GCC, Global only)** Two letter country code for the EU country to which the tax belongs.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| purchase_tax_expense_account_id | long      | **(Australia, Canada only)** Account ID in which Purchase Tax will be Computed                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| is_value_added                  | boolean   | Check if Tax is Value Added                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| update_recurring_invoice        | boolean   | Check if recurring invoice should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| update_recurring_expense        | boolean   | Check if recurring expenses should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| update_draft_invoice            | boolean   | Check if Draft Invoices should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| update_recurring_bills          | boolean   | Check if Recurring Bills should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| update_draft_so                 | boolean   | Check if Draft Sales Orders should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| update_subscription             | boolean   | Check if Subscriptions should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| update_project                  | boolean   | Check if Projects should be updated                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| is_editable                     | boolean   | Check if tax is editable                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| tds_payable_account_id          | string    | **(Mexico only)** Input Tax ID. The amount of money charged to you as Tax on your purchases.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |

### Path Parameters

| Attribute | Data Type | Description                                  |
| :-------- | :-------- | :------------------------------------------- |
| tax_id    | string    | **(Required)** Unique identifier of the tax. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/taxes/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_id": "982000000566009",
    "tax_name": "Sales Group",
    "tax_percentage": 10.5,
    "tax_type": "tax",
    "tax_factor": "rate",
    "tax_specific_type": "string",
    "tax_authority_name": "Illinois Department of Revenue",
    "tax_authority_id": "460000000066001",
    "country_code": "UK",
    "purchase_tax_expense_account_id": 0,
    "is_value_added": false,
    "update_recurring_invoice": false,
    "update_recurring_expense": false,
    "update_draft_invoice": false,
    "update_recurring_bills": false,
    "update_draft_so": false,
    "update_subscription": false,
    "update_project": false,
    "is_editable": true,
    "tds_payable_account_id": "132086000000107337"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax information has been saved.",
    "tax": [
        {
            "tax_id": "982000000566009",
            "tax_name": "Sales Group",
            "tax_percentage": 10.5,
            "tax_type": "tax",
            "tax_factor": "rate",
            "tds_payable_account_id": "132086000000107337",
            "tax_authority_id": "460000000066001",
            "tax_authority_name": "Illinois Department of Revenue",
            "is_value_added": false,
            "tax_specific_type": "string",
            "country": "string",
            "country_code": "UK",
            "purchase_tax_expense_account_id": 0
        }
    ]
}
```

---

## Get a tax

Get the details of a simple or compound tax.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Attribute | Data Type | Description                                  |
| :-------- | :-------- | :------------------------------------------- |
| tax_id    | string    | **(Required)** Unique identifier of the tax. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxes/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax": [
        {
            "tax_id": "982000000566009",
            "tax_name": "Sales Group",
            "tax_percentage": 10.5,
            "tax_type": "tax",
            "tax_factor": "rate",
            "tds_payable_account_id": "132086000000107337",
            "tax_authority_id": "460000000066001",
            "tax_authority_name": "Illinois Department of Revenue",
            "is_value_added": false,
            "tax_specific_type": "string",
            "country": "string",
            "country_code": "UK",
            "purchase_tax_expense_account_id": 0
        }
    ]
}
```

---

## Delete a tax

Delete a simple or compound tax.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Attribute | Data Type | Description                                  |
| :-------- | :-------- | :------------------------------------------- |
| tax_id    | string    | **(Required)** Unique identifier of the tax. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/taxes/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The record has been deleted."
}
```

---

## Create a tax group

Create a tax group associating multiple taxes.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Attribute      | Data Type | Description                                                                 |
| :------------- | :-------- | :-------------------------------------------------------------------------- |
| tax_group_name | string    | Name of the tax group to be created.                                        |
| taxes          | string    | Comma Seperated list of tax IDs that are to be associated to the tax group. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/taxgroups?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_group_name": "Sales Group",
    "taxes": "982000000566009"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_group": {
        "tax_group_id": "982000000566009",
        "tax_group_name": "Sales Group",
        "tax_group_percentage": 10.5,
        "taxes": [
            {
                "tax_id": "982000000566009",
                "tax_name": "Sales Group",
                "tax_percentage": 10.5,
                "tax_type": "tax",
                "tax_factor": "rate",
                "tax_authority_id": "460000000066001",
                "tax_authority_name": "Illinois Department of Revenue"
            }
        ]
    }
}
```

---

## Update a tax group

Update the details of the tax group.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Attribute      | Data Type | Description                                                                 |
| :------------- | :-------- | :-------------------------------------------------------------------------- |
| tax_group_name | string    | Name of the tax group to be created.                                        |
| taxes          | string    | Comma Seperated list of tax IDs that are to be associated to the tax group. |

### Path Parameters

| Attribute    | Data Type | Description                                        |
| :----------- | :-------- | :------------------------------------------------- |
| tax_group_id | string    | **(Required)** Unique identifier of the tax group. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/taxgroups/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_group_name": "Sales Group",
    "taxes": "982000000566009"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_group": {
        "tax_group_id": "982000000566009",
        "tax_group_name": "Sales Group",
        "tax_group_percentage": 10.5,
        "taxes": [
            {
                "tax_id": "982000000566009",
                "tax_name": "Sales Group",
                "tax_percentage": 10.5,
                "tax_type": "tax",
                "tax_factor": "rate",
                "tax_authority_id": "460000000066001",
                "tax_authority_name": "Illinois Department of Revenue"
            }
        ]
    }
}
```

---

## Get a tax group

Get the details of a tax group.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Attribute    | Data Type | Description                                        |
| :----------- | :-------- | :------------------------------------------------- |
| tax_group_id | string    | **(Required)** Unique identifier of the tax group. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxgroups/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_group": {
        "tax_group_id": "982000000566009",
        "tax_group_name": "Sales Group",
        "tax_group_percentage": 10.5,
        "taxes": [
            {
                "tax_id": "982000000566009",
                "tax_name": "Sales Group",
                "tax_percentage": 10.5,
                "tax_type": "tax",
                "tax_factor": "rate",
                "tax_authority_id": "460000000066001",
                "tax_authority_name": "Illinois Department of Revenue"
            }
        ]
    }
}
```

---

## Delete a tax group

Delete a tax group. Tax group that is associated to transactions cannot be deleted.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Attribute    | Data Type | Description                                        |
| :----------- | :-------- | :------------------------------------------------- |
| tax_group_id | string    | **(Required)** Unique identifier of the tax group. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/taxgroups/982000000566009?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The tax group has been deleted."
}
```

---

## Create a tax authority [US and CA Edition only]

Create a tax authority.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Attribute                 | Data Type | Description                                                |
| :------------------------ | :-------- | :--------------------------------------------------------- |
| tax_authority_name        | string    | **(Required)** Name of the Tax Authority                   |
| description               | string    | Description.                                               |
| registration_number       | string    | **(Canada only)** Registration Number of the Tax Authority |
| registration_number_label | string    | **(Canada only)**                                          |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/taxauthorities?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_authority_name": "Illinois Department of Revenue",
    "description": "The New York State Department of  Taxation and Finance",
    "registration_number": "string",
    "registration_number_label": "string"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax Authority has been added.",
    "tax_authority": {
        "tax_authority_id": "460000000066001",
        "tax_authority_name": "Illinois Department of Revenue",
        "description": "The New York State Department of  Taxation and Finance",
        "registration_number": "string",
        "registration_number_label": "string"
    }
}
```

---

## List tax authorities [US Edition only]

List of tax authorities.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxauthorities?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_authorities": [
        {
            "tax_authority_id": "460000000066001",
            "tax_authority_name": "Illinois Department of Revenue",
            "description": "The New York State Department of  Taxation and Finance",
            "registration_number": "string",
            "registration_number_label": "string"
        }
    ]
}
```

---

## Update a tax authority [US and CA Edition only]

Update the details of a tax authority.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Attribute                 | Data Type | Description                                                |
| :------------------------ | :-------- | :--------------------------------------------------------- |
| tax_authority_name        | string    | Name of the Tax Authority                                  |
| description               | string    | Description.                                               |
| registration_number       | string    | **(Canada only)** Registration Number of the Tax Authority |
| registration_number_label | string    | **(Canada only)**                                          |

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_authority_id | string    | **(Required)** Unique identifier of the tax authority. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/taxauthorities/460000000066001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_authority_name": "Illinois Department of Revenue",
    "description": "The New York State Department of  Taxation and Finance",
    "registration_number": "string",
    "registration_number_label": "string"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax Authority information has been updated.",
    "tax_authority": {
        "tax_authority_id": "460000000066001",
        "tax_authority_name": "Illinois Department of Revenue",
        "description": "The New York State Department of  Taxation and Finance",
        "registration_number": "string",
        "registration_number_label": "string"
    }
}
```

---

## Get a tax authority [US and CA Edition only]

Get the details of a tax authority.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_authority_id | string    | **(Required)** Unique identifier of the tax authority. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxauthorities/460000000066001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_authority": {
        "tax_authority_id": "460000000066001",
        "tax_authority_name": "Illinois Department of Revenue",
        "description": "The New York State Department of  Taxation and Finance",
        "registration_number": "string",
        "registration_number_label": "string"
    }
}
```

---

## Delete a tax authority [US and CA Edition only]

Delete a tax authority.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_authority_id | string    | **(Required)** Unique identifier of the tax authority. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/taxauthorities/460000000066001?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax authority has been deleted."
}
```

---

## Create a tax exemption [US Edition only]

Create a tax exemption.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Attribute          | Data Type | Description                                                            |
| :----------------- | :-------- | :--------------------------------------------------------------------- |
| tax_exemption_code | string    | **(Required)** **(India only)** Code of the Tax Exemption              |
| description        | string    | Description                                                            |
| type               | string    | **(Required)** Type of the tax exemption, can be `customer` or `item`. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/taxexemptions?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_exemption_code": "RESELLER",
    "description": "Tax exempted because the contact is a reseller.",
    "type": "customer"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax Exemption has been added.",
    "tax_exemption": {
        "tax_exemption_id": "460000000076002",
        "tax_exemption_code": "RESELLER",
        "description": "Tax exempted because the contact is a reseller.",
        "type": "customer"
    }
}
```

---

## List tax exemptions [US Edition only]

List of tax exemptions.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxexemptions?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_exemptions": [
        {
            "tax_exemption_id": "460000000076002",
            "tax_exemption_code": "RESELLER",
            "description": "Tax exempted because the contact is a reseller.",
            "type": "customer"
        }
    ]
}
```

---

## Update a tax exemption [US Edition only]

Update the details of a tax exemption.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Arguments

| Attribute          | Data Type | Description                                                            |
| :----------------- | :-------- | :--------------------------------------------------------------------- |
| tax_exemption_code | string    | **(Required)** **(India only)** Code of the Tax Exemption              |
| description        | string    | Description                                                            |
| type               | string    | **(Required)** Type of the tax exemption, can be `customer` or `item`. |

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_exemption_id | string    | **(Required)** Unique identifier of the tax exemption. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/settings/taxexemptions/460000000076002?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "tax_exemption_code": "RESELLER",
    "description": "Tax exempted because the contact is a reseller.",
    "type": "customer"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax Exemption has been updated.",
    "tax_exemption": {
        "tax_exemption_id": "460000000076002",
        "tax_exemption_code": "RESELLER",
        "description": "Tax exempted because the contact is a reseller.",
        "type": "customer"
    }
}
```

---

## Get a tax exemption [US Edition only]

Get the details of a tax exemption.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_exemption_id | string    | **(Required)** Unique identifier of the tax exemption. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/settings/taxexemptions/460000000076002?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "tax_exemption": {
        "tax_exemption_id": "460000000076002",
        "tax_exemption_code": "RESELLER",
        "description": "Tax exempted because the contact is a reseller.",
        "type": "customer"
    }
}
```

---

## Delete a tax exemption [US Edition only]

Delete a tax exemption.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Attribute        | Data Type | Description                                            |
| :--------------- | :-------- | :----------------------------------------------------- |
| tax_exemption_id | string    | **(Required)** Unique identifier of the tax exemption. |

### Query Parameters

| Attribute       | Data Type | Description                           |
| :-------------- | :-------- | :------------------------------------ |
| organization_id | string    | **(Required)** ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/settings/taxexemptions/460000000076002?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "Tax exemption has been deleted successfully."
}
```