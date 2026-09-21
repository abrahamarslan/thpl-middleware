# Recurring Expenses

Recurring expenses are those expenses that repeat itself after a fixed interval of time.

### End Points

| Method     | URL                                                       | Description                                                     |
| :--------- | :-------------------------------------------------------- | :-------------------------------------------------------------- |
| **POST**   | `/recurringexpenses`                                      | Create a recurring expense                                      |
| **PUT**    | `/recurringexpenses`                                      | Update an recurring expense using a custom field's unique value |
| **GET**    | `/recurringexpenses`                                      | List recurring expenses                                         |
| **PUT**    | `/recurringexpenses/{recurring_expense_id}`               | Update a recurring expense                                      |
| **GET**    | `/recurringexpenses/{recurring_expense_id}`               | Get a recurring expense                                         |
| **DELETE** | `/recurringexpenses/{recurring_expense_id}`               | Delete a recurring expense                                      |
| **POST**   | `/recurringexpenses/{recurring_expense_id}/status/stop`   | Stop a recurring expense                                        |
| **POST**   | `/recurringexpenses/{recurring_expense_id}/status/resume` | Resume a recurring Expense                                      |
| **GET**    | `/recurringexpenses/{recurring_expense_id}/expenses`      | List child expenses created                                     |
| **GET**    | `/recurringexpenses/{recurring_expense_id}/comments`      | List recurring expense history                                  |

---

## Attributes

| Attribute                         | Data Type | Description                                                                                                                                                                                                                                                                                                                                                            |
| :-------------------------------- | :-------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **account_id**                    | string    | The account identifier.                                                                                                                                                                                                                                                                                                                                                |
| **recurrence_name**               | string    | Name of the Recurring Expense. Max-length [100].                                                                                                                                                                                                                                                                                                                       |
| **start_date**                    | string    | Start date of the recurring expense. Expenses will not be generated for dates prior to the current date. Format [yyyy-mm-dd].                                                                                                                                                                                                                                          |
| **end_date**                      | string    | Date on which recurring expense has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                                                                                                                                                                                                                                                               |
| **is_pre_gst**                    | boolean   | Applicable for transactions that fall before july 1, 2017. **[India only]**                                                                                                                                                                                                                                                                                            |
| **source_of_supply**              | string    | Place from where the goods/services are supplied. (If not given, `place of contact` given for the contact will be taken). **[India only]**                                                                                                                                                                                                                             |
| **destination_of_supply**         | string    | Place where the goods/services are supplied to. (If not given, organisation's home state will be taken). **[India only]**                                                                                                                                                                                                                                              |
| **place_of_supply**               | string    | The place of supply is where a transaction is considered to have occurred for VAT purposes. <br>Supported codes for UAE emirates: `AB`, `AJ`, `DU`, `FU`, `RA`, `SH`, `UM`.<br>Supported codes for GCC: `AE`, `SA`, `BH`, `KW`, `OM`, `QA`. **[GCC only]**                                                                                                             |
| **gst_no**                        | string    | 15 digit GST identification number of the vendor. **[India only]**                                                                                                                                                                                                                                                                                                     |
| **gst_treatment**                 | string    | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values: `business_gst`, `business_none`, `overseas`, `consumer`. **[India only]**                                                                                                                                                                                                 |
| **tax_treatment**                 | string    | VAT treatment for the recurring expense.<br>**GCC:** `vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc` (`dz_vat_...` for UAE).<br>**Kenya:** `vat_registered`, `vat_not_registered`, `non_kenya`.<br>**South Africa:** `vat_registered`, `vat_not_registered`, `overseas`. **[GCC, Mexico, Kenya, South Africa only]** |
| **destination_of_supply_state**   | string    | Place to where the goods/services are supplied. **[India only]**                                                                                                                                                                                                                                                                                                       |
| **hsn_or_sac**                    | string    | Add HSN/SAC code for your goods/services. **[India, Kenya only]**                                                                                                                                                                                                                                                                                                      |
| **vat_treatment**                 | string    | VAT treatment for the expense. Values: `uk`, `eu_vat_registered`, `overseas` (Pre-Brexit: `eu_vat_not_registered`, `non_eu`). **[UK only]**                                                                                                                                                                                                                            |
| **reverse_charge_tax_id**         | string    | Enter reverse charge tax ID. Used to specify whether the transaction is applicable for Domestic Reverse Charge (DRC) or not. **[India, GCC, South Africa only]**                                                                                                                                                                                                       |
| **reverse_charge_tax_name**       | string    | Enter reverse charge tax name. **[India only]**                                                                                                                                                                                                                                                                                                                        |
| **reverse_charge_tax_percentage** | double    | Tax percentage of the reverse charge. **[India only]**                                                                                                                                                                                                                                                                                                                 |
| **reverse_charge_tax_amount**     | double    | Tax amount of the reverse charge. **[India only]**                                                                                                                                                                                                                                                                                                                     |
| **is_reverse_charge_applied**     | boolean   | Applicable for transactions where you pay reverse charge. **[India only]**                                                                                                                                                                                                                                                                                             |
| **acquisition_vat_total**         | double    | Enter the total acquisition vat.                                                                                                                                                                                                                                                                                                                                       |
| **reverse_charge_vat_total**      | double    | Enter the total of the reverse charge vat. **[India only]**                                                                                                                                                                                                                                                                                                            |
| **acquisition_vat_summary**       | array     | Summary of the VAT Acquistion. Contains `tax_name` and `tax_amount`.                                                                                                                                                                                                                                                                                                   |
| **reverse_charge_vat_summary**    | array     | Summary of the Reverse Charge. Contains `tax_name` and `tax_amount`.                                                                                                                                                                                                                                                                                                   |
| **recurrence_frequency**          | string    | Frequency of recurrence.                                                                                                                                                                                                                                                                                                                                               |
| **repeat_every**                  | string    | Interval for repetition.                                                                                                                                                                                                                                                                                                                                               |
| **amount**                        | double    | Recurring Expense amount.                                                                                                                                                                                                                                                                                                                                              |
| **total**                         | double    | Total amount.                                                                                                                                                                                                                                                                                                                                                          |
| **sub_total**                     | double    | Sub-total amount.                                                                                                                                                                                                                                                                                                                                                      |
| **bcy_total**                     | double    | Base Currency Total.                                                                                                                                                                                                                                                                                                                                                   |
| **product_type**                  | string    | Type of the expense. <br>**UK:** `digital_service`, `goods`, `service`.<br>**South Africa:** `service`, `goods`, `capital_service`, `capital_goods`. **[UK, South Africa only]**                                                                                                                                                                                       |
| **acquisition_vat_id**            | string    | ID of the tax applied in case this is an EU - goods expense and acquisition VAT needs to be reported. **[UK only]**                                                                                                                                                                                                                                                    |
| **reverse_charge_vat_id**         | string    | ID of the tax applied in case this is a non UK - service expense and reverse charge VAT needs to be reported. **[India, UK only]**                                                                                                                                                                                                                                     |
| **tax_id**                        | string    | The Tax ID.                                                                                                                                                                                                                                                                                                                                                            |
| **tax_name**                      | string    | The Tax Name.                                                                                                                                                                                                                                                                                                                                                          |
| **tax_percentage**                | double    | The Tax Percentage.                                                                                                                                                                                                                                                                                                                                                    |
| **created_time**                  | string    | Time of creation.                                                                                                                                                                                                                                                                                                                                                      |
| **last_modified_time**            | string    | Time of last modification.                                                                                                                                                                                                                                                                                                                                             |
| **is_inclusive_tax**              | boolean   | Is tax included in the amount.                                                                                                                                                                                                                                                                                                                                         |
| **is_billable**                   | boolean   | Is the expense billable.                                                                                                                                                                                                                                                                                                                                               |
| **customer_id**                   | string    | Search expenses by customer id.                                                                                                                                                                                                                                                                                                                                        |
| **currency_id**                   | string    | The currency ID.                                                                                                                                                                                                                                                                                                                                                       |
| **exchange_rate**                 | double    | The exchange rate.                                                                                                                                                                                                                                                                                                                                                     |
| **project_id**                    | string    | The project ID.                                                                                                                                                                                                                                                                                                                                                        |
| **project_name**                  | string    | The project name.                                                                                                                                                                                                                                                                                                                                                      |
| **custom_fields**                 | array     | Custom fields for a recurring-expense. Contains `customfield_id` and `value`.                                                                                                                                                                                                                                                                                          |
| **location_id**                   | string    | Location ID.                                                                                                                                                                                                                                                                                                                                                           |
| **location_name**                 | string    | Name of the location.                                                                                                                                                                                                                                                                                                                                                  |
| **line_item**                     | object    | Line item details (see below).                                                                                                                                                                                                                                                                                                                                         |

**Line Item Object:**
*   `line_item_id`, `account_id`, `account_name` (Max-length 100), `description` (Max-length 100), `tax_amount`, `tax_id`, `tax_name`, `tax_type`, `tax_percentage`, `item_total`, `item_order`, `hsn_or_sac` **[India, Kenya only]**, `reverse_charge_tax_id` **[India, GCC, South Africa only]**, `reverse_charge_tax_name` **[India only]**, `reverse_charge_tax_percentage` **[India only]**, `reverse_charge_tax_amount` **[India only]**.

---

## Create a recurring expense

Create a recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.CREATE`

### Arguments

| Argument                  | Type    | Required | Description                                                                                                                   |
| :------------------------ | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------- |
| **account_id**            | string  | Required |                                                                                                                               |
| **recurrence_name**       | string  | Required | Name of the Recurring Expense. Max-length [100]                                                                               |
| **start_date**            | string  | Required | Start date of the recurring expense. Expenses will not be generated for dates prior to the current date. Format [yyyy-mm-dd]. |
| **end_date**              | string  | Optional | Date on which recurring expense has to expire. Can be left as empty to run forever. Format [yyyy-mm-dd].                      |
| **recurrence_frequency**  | string  | Required |                                                                                                                               |
| **repeat_every**          | string  | Required |                                                                                                                               |
| **gst_no**                | string  | Optional | 15 digit GST identification number of the vendor. **[India only]**                                                            |
| **source_of_supply**      | string  | Optional | Place from where the goods/services are supplied. **[India only]**                                                            |
| **destination_of_supply** | string  | Optional | Place where the goods/services are supplied to. **[India only]**                                                              |
| **place_of_supply**       | string  | Optional | The place of supply (VAT purposes). See Attribute table for codes. **[GCC only]**                                             |
| **reverse_charge_tax_id** | string  | Optional | ID for Domestic Reverse Charge (DRC). **[India, GCC, South Africa only]**                                                     |
| **location_id**           | string  | Optional | Location ID                                                                                                                   |
| **line_items**            | array   | Optional | Array of line items.                                                                                                          |
| **amount**                | double  | Required | Recurring Expense amount.                                                                                                     |
| **vat_treatment**         | string  | Optional | VAT treatment. **[UK only]**                                                                                                  |
| **tax_treatment**         | string  | Optional | VAT/Tax treatment. **[GCC, Mexico, Kenya, South Africa only]**                                                                |
| **product_type**          | string  | Optional | Type of expense. **[UK, South Africa only]**                                                                                  |
| **acquisition_vat_id**    | string  | Optional | Tax ID for EU goods acquisition. **[UK only]**                                                                                |
| **reverse_charge_vat_id** | string  | Optional | Tax ID for reverse charge VAT. **[India, UK only]**                                                                           |
| **tax_id**                | string  | Optional |                                                                                                                               |
| **is_inclusive_tax**      | boolean | Optional |                                                                                                                               |
| **is_billable**           | boolean | Optional |                                                                                                                               |
| **customer_id**           | string  | Optional | Search expenses by customer id.                                                                                               |
| **project_id**            | string  | Optional |                                                                                                                               |
| **currency_id**           | string  | Optional |                                                                                                                               |
| **exchange_rate**         | double  | Optional |                                                                                                                               |
| **custom_fields**         | array   | Optional | Custom fields for a recurring-expense.                                                                                        |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```json
{
    "account_id": 982000000561057,
    "recurrence_name": "Monthly Rental",
    "start_date": "2016-11-19T00:00:00.000Z",
    "end_date": " ",
    "recurrence_frequency": "months",
    "repeat_every": 1,
    "gst_no": "22AAAAA0000A1Z5",
    "source_of_supply": "AP",
    "destination_of_supply": "TN",
    "place_of_supply": "DU",
    "reverse_charge_tax_id": 982000000567254,
    "location_id": "460000000038080",
    "line_items": [
        {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "description": " ",
            "amount": 112.5,
            "tax_id": 982000000566007,
            "item_order": 1,
            "product_type": "goods",
            "acquisition_vat_id": " ",
            "reverse_charge_vat_id": " ",
            "reverse_charge_tax_id": 982000000567254,
            "tax_exemption_code": "string",
            "tax_exemption_id": 982000000567267
        }
    ],
    "amount": 112.5,
    "vat_treatment": "eu_vat_not_registered",
    "tax_treatment": "vat_registered",
    "product_type": "goods",
    "acquisition_vat_id": " ",
    "reverse_charge_vat_id": " ",
    "tax_id": 982000000566007,
    "is_inclusive_tax": false,
    "is_billable": true,
    "customer_id": 982000000567001,
    "project_id": " ",
    "currency_id": 982000000567001,
    "exchange_rate": 1,
    "custom_fields": [
        {
            "customfield_id": "46000000012845",
            "value": "Normal"
        }
    ]
}
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring expense has been created",
    "recurring_expense": {
        "account_id": 982000000561057,
        "recurrence_name": "Monthly Rental",
        "start_date": "2016-11-19T00:00:00.000Z",
        "end_date": " ",
        "is_pre_gst": false,
        "source_of_supply": "AP",
        "destination_of_supply": "TN",
        "place_of_supply": "DU",
        "gst_no": "22AAAAA0000A1Z5",
        "gst_treatment": "business_gst",
        "tax_treatment": "vat_registered",
        "destination_of_supply_state": "AP",
        "hsn_or_sac": 80540,
        "vat_treatment": "eu_vat_not_registered",
        "reverse_charge_tax_id": 982000000567254,
        "reverse_charge_tax_name": "inter",
        "reverse_charge_tax_percentage": 10,
        "reverse_charge_tax_amount": 10,
        "is_reverse_charge_applied": false,
        "acquisition_vat_total": 0,
        "reverse_charge_vat_total": 10,
        "acquisition_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "recurrence_frequency": "months",
        "repeat_every": 1,
        "amount": 112.5,
        "total": 128.25,
        "sub_total": 90,
        "bcy_total": 100,
        "product_type": "goods",
        "acquisition_vat_id": " ",
        "reverse_charge_vat_id": " ",
        "tax_id": 982000000566007,
        "tax_name": "SalesTax",
        "tax_percentage": 10.5,
        "created_time": "2013-11-18T02:17:40.080Z",
        "last_modified_time": " ",
        "is_inclusive_tax": false,
        "is_billable": true,
        "customer_id": 982000000567001,
        "currency_id": 982000000567001,
        "exchange_rate": 1,
        "project_id": " ",
        "project_name": " ",
        "custom_fields": [
            {
                "customfield_id": "46000000012845",
                "value": "Normal"
            }
        ],
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item": {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "account_name": "Rent",
            "description": " ",
            "tax_amount": 11.85,
            "tax_id": 982000000566007,
            "tax_name": "SalesTax",
            "tax_type": "tax",
            "tax_percentage": 10.5,
            "item_total": 100,
            "item_order": 1,
            "hsn_or_sac": 80540,
            "reverse_charge_tax_id": 982000000567254,
            "reverse_charge_tax_name": "inter",
            "reverse_charge_tax_percentage": 10,
            "reverse_charge_tax_amount": 10
        }
    }
}
```

---

## Update an recurring expense using a custom field's unique value

A custom field will have unique values if it's configured to not accept duplicate values. Now, you can use that custom field's value to update a recurring expense by providing its API name in the `X-Unique-Identifier-Key` header and its value in the `X-Unique-Identifier-Value` header. Based on this value, the corresponding recurring expense will be retrieved and updated. Additionally, there is an optional `X-Upsert` header. If the `X-Upsert` header is true and the custom field's unique value is not found in any of the existing recurring expenses, a new recurring expense will be created if the necessary payload details are available.

*   **OAuth Scope:** `ZohoBooks.expenses.UPDATE`

### Headers

| Header                        | Type    | Required | Description                                                                        |
| :---------------------------- | :------ | :------- | :--------------------------------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string  | Required | Unique CustomField Api Name                                                        |
| **X-Unique-Identifier-Value** | string  | Required | Unique CustomField Value                                                           |
| **X-Upsert**                  | boolean | Optional | If there is no record is found unique custom field value , will create new invoice |

### Arguments

(Same as Create Recurring Expense)

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Recurring expense information has been updated",
    "recurring_expense": {
        "account_id": 982000000561057,
        "recurrence_name": "Monthly Rental",
        "start_date": "2016-11-19T00:00:00.000Z",
        "end_date": " ",
        "is_pre_gst": false,
        "source_of_supply": "AP",
        "destination_of_supply": "TN",
        "place_of_supply": "DU",
        "gst_no": "22AAAAA0000A1Z5",
        "gst_treatment": "business_gst",
        "tax_treatment": "vat_registered",
        "destination_of_supply_state": "AP",
        "hsn_or_sac": 80540,
        "vat_treatment": "eu_vat_not_registered",
        "reverse_charge_tax_id": 982000000567254,
        "reverse_charge_tax_name": "inter",
        "reverse_charge_tax_percentage": 10,
        "reverse_charge_tax_amount": 10,
        "is_reverse_charge_applied": false,
        "acquisition_vat_total": 0,
        "reverse_charge_vat_total": 10,
        "acquisition_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "recurrence_frequency": "months",
        "repeat_every": 1,
        "amount": 120.5,
        "total": 128.25,
        "sub_total": 90,
        "bcy_total": 100,
        "product_type": "goods",
        "acquisition_vat_id": " ",
        "reverse_charge_vat_id": " ",
        "tax_id": 982000000566007,
        "tax_name": "SalesTax",
        "tax_percentage": 10.5,
        "created_time": "2013-11-18T02:17:40.080Z",
        "last_modified_time": " ",
        "is_inclusive_tax": false,
        "is_billable": true,
        "customer_id": 982000000567001,
        "currency_id": 982000000567001,
        "exchange_rate": 1,
        "project_id": " ",
        "project_name": " ",
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item": {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "account_name": "Rent",
            "description": " ",
            "tax_amount": 11.85,
            "tax_id": 982000000566007,
            "tax_name": "SalesTax",
            "tax_type": "tax",
            "tax_percentage": 10.5,
            "item_total": 100,
            "item_order": 1,
            "hsn_or_sac": 80540,
            "reverse_charge_tax_id": 982000000567254,
            "reverse_charge_tax_name": "inter",
            "reverse_charge_tax_percentage": 10,
            "reverse_charge_tax_amount": 10
        }
    }
}
```

---

## List recurring expenses

List all the Expenses with pagination.

*   **OAuth Scope:** `ZohoBooks.expenses.READ`

### Query Parameters

| Parameter                   | Type    | Required | Description                                                                                                                                                                                                             |
| :-------------------------- | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id**         | string  | Required | ID of the organization                                                                                                                                                                                                  |
| **recurrence_name**         | string  | Optional | Search recurring expenses by recurring expense name. Variants: `recurrence_name_startswith` and `recurrence_name_contains`. Max-length [100]                                                                            |
| **last_created_date**       | string  | Optional | Search recurring expenses by date on when last expense was generated. Variants: `last_created_date_start`, `last_created_date_end`, `last_created_date_before` and `last_created_date_after` . Format [yyyy-mm-dd]      |
| **next_expense_date**       | string  | Optional | Search recurring expenses by date on which next expense will be generated. Variants: `next_expense_date_start`, `next_expense_date_end`, `next_expense_date_before` and `next_expense_date_after` . Format [yyyy-mm-dd] |
| **status**                  | string  | Optional | Search expenses by expense status. Allowed Values `active`, `stopped` and `expired`                                                                                                                                     |
| **account_id**              | string  | Optional |                                                                                                                                                                                                                         |
| **account_name**            | string  | Optional | Search expenses by expense account name. Variants `account_name_startswith` and `account_name_contains` . Max-length [100]                                                                                              |
| **amount**                  | double  | Optional | Search expenses by amount. Variants: `amount_less_than`, `amount_less_equals`, `amount_greater_than` and `amount_greater_than`                                                                                          |
| **customer_name**           | string  | Optional | Search expenses by customer name. Variants: `customer_name_startswith` and `customer_name_contains` . Max-length [100]                                                                                                  |
| **customer_id**             | string  | Optional | Search expenses by customer id.                                                                                                                                                                                         |
| **paid_through_account_id** | string  | Optional | Search expenses by paid through account id.                                                                                                                                                                             |
| **filter_by**               | string  | Optional | Filter expenses by expense status. Allowed Values `Status.All`, `Status.Active`, `Status.Expired` and `Status.Stopped`                                                                                                  |
| **search_text**             | string  | Optional | Search expenses by account name or description or `customer name` or `vendor name`. Max-length [100] .                                                                                                                  |
| **sort_column**             | string  | Optional | Sort expenses.Allowed Values `next_expense_date`, `account_name`, `total`, `last_created_date`, `recurrence_name`, `customer_name` and `created_time`                                                                   |
| **page**                    | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                                          |
| **per_page**                | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                         |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "recurring_expenses": [
        {
            "recurring_expense_id": 982000000567240,
            "recurrence_name": "Monthly Rental",
            "recurrence_frequency": "months",
            "repeat_every": 1,
            "last_created_date": "2013-11-18T00:00:00.000Z",
            "next_expense_date": "2013-12-18T00:00:00.000Z",
            "account_name": "Rent",
            "description": " ",
            "currency_id": 982000000567001,
            "currency_code": "USD",
            "total": 128.25,
            "is_billable": true,
            "customer_name": "Bowman & Co",
            "custom_fields": [
                {
                    "customfield_id": "46000000012845",
                    "value": "Normal"
                }
            ],
            "status": "active",
            "created_time": "2013-11-18T02:17:40.080Z",
            "last_modified_time": " "
        }
    ],
    "page_context": [
        {
            "sort_column": "account_name",
            "filter_by": "Status.Billable",
            "search_text": "Rent"
        }
    ]
}
```

---

## Update a recurring expense

Update a recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.UPDATE`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Arguments

(Same as Create Recurring Expense)

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Recurring expense information has been updated",
    "recurring_expense": {
        "account_id": 982000000561057,
        "recurrence_name": "Monthly Rental",
        "start_date": "2016-11-19T00:00:00.000Z",
        "end_date": " ",
        "is_pre_gst": false,
        "source_of_supply": "AP",
        "destination_of_supply": "TN",
        "place_of_supply": "DU",
        "gst_no": "22AAAAA0000A1Z5",
        "gst_treatment": "business_gst",
        "tax_treatment": "vat_registered",
        "destination_of_supply_state": "AP",
        "hsn_or_sac": 80540,
        "vat_treatment": "eu_vat_not_registered",
        "reverse_charge_tax_id": 982000000567254,
        "reverse_charge_tax_name": "inter",
        "reverse_charge_tax_percentage": 10,
        "reverse_charge_tax_amount": 10,
        "is_reverse_charge_applied": false,
        "acquisition_vat_total": 0,
        "reverse_charge_vat_total": 10,
        "acquisition_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "recurrence_frequency": "months",
        "repeat_every": 1,
        "amount": 120.5,
        "total": 128.25,
        "sub_total": 90,
        "bcy_total": 100,
        "product_type": "goods",
        "acquisition_vat_id": " ",
        "reverse_charge_vat_id": " ",
        "tax_id": 982000000566007,
        "tax_name": "SalesTax",
        "tax_percentage": 10.5,
        "created_time": "2013-11-18T02:17:40.080Z",
        "last_modified_time": " ",
        "is_inclusive_tax": false,
        "is_billable": true,
        "customer_id": 982000000567001,
        "currency_id": 982000000567001,
        "exchange_rate": 1,
        "project_id": " ",
        "project_name": " ",
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item": {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "account_name": "Rent",
            "description": " ",
            "tax_amount": 11.85,
            "tax_id": 982000000566007,
            "tax_name": "SalesTax",
            "tax_type": "tax",
            "tax_percentage": 10.5,
            "item_total": 100,
            "item_order": 1,
            "hsn_or_sac": 80540,
            "reverse_charge_tax_id": 982000000567254,
            "reverse_charge_tax_name": "inter",
            "reverse_charge_tax_percentage": 10,
            "reverse_charge_tax_amount": 10
        }
    }
}
```

---

## Get a recurring expense

Get the details of the recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.READ`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "recurring_expense": {
        "recurring_expense_id": 982000000567240,
        "recurrence_name": "Monthly Rental",
        "start_date": "2016-11-19T00:00:00.000Z",
        "end_date": " ",
        "is_pre_gst": false,
        "source_of_supply": "AP",
        "destination_of_supply": "TN",
        "place_of_supply": "DU",
        "gst_no": "22AAAAA0000A1Z5",
        "gst_treatment": "business_gst",
        "destination_of_supply_state": "AP",
        "hsn_or_sac": 80540,
        "vat_treatment": "eu_vat_not_registered",
        "reverse_charge_tax_id": 982000000567254,
        "reverse_charge_tax_name": "inter",
        "reverse_charge_tax_percentage": 10,
        "reverse_charge_tax_amount": 10,
        "is_reverse_charge_applied": false,
        "acquisition_vat_total": 0,
        "reverse_charge_vat_total": 10,
        "acquisition_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "reverse_charge_vat_summary": [
            {
                "tax_name": "SalesTax",
                "tax_amount": 11.85
            }
        ],
        "recurrence_frequency": "months",
        "repeat_every": 1,
        "last_created_date": "2013-11-18T00:00:00.000Z",
        "next_expense_date": "2013-12-18T00:00:00.000Z",
        "account_id": 982000000561057,
        "account_name": "Rent",
        "currency_id": 982000000567001,
        "currency_code": "USD",
        "exchange_rate": 1,
        "tax_id": 982000000566007,
        "tax_name": "SalesTax",
        "tax_percentage": 10.5,
        "tax_amount": 11.85,
        "sub_total": 90,
        "total": 128.25,
        "bcy_total": 100,
        "amount": 112.5,
        "description": " ",
        "is_inclusive_tax": false,
        "is_billable": true,
        "customer_id": 982000000567001,
        "customer_name": "Bowman & Co",
        "status": "active",
        "created_time": "2013-11-18T02:17:40.080Z",
        "last_modified_time": " ",
        "project_id": " ",
        "project_name": " ",
        "location_id": "460000000038080",
        "location_name": "string",
        "line_item": {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "account_name": "Rent",
            "description": " ",
            "tax_amount": 11.85,
            "tax_id": 982000000566007,
            "tax_name": "SalesTax",
            "tax_type": "tax",
            "tax_percentage": 10.5,
            "item_total": 100,
            "item_order": 1,
            "hsn_or_sac": 80540,
            "reverse_charge_tax_id": 982000000567254,
            "reverse_charge_tax_name": "inter",
            "reverse_charge_tax_percentage": 10,
            "reverse_charge_tax_amount": 10
        }
    }
}
```

---

## Delete a recurring expense

Deleting an existing recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.DELETE`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring expense has been deleted."
}
```

---

## Stop a recurring expense

Stop an active recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.CREATE`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240/status/stop?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring expense has been stopped."
}
```

---

## Resume a recurring Expense

Resume a stopped recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.CREATE`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240/status/resume?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The recurring expense has been activated."
}
```

---

## List child expenses created

List child expenses created from recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.READ`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type    | Required | Description                                                                                                                                           |
| :------------------ | :------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id** | string  | Required | ID of the organization                                                                                                                                |
| **sort_column**     | string  | Optional | Sort expenses.Allowed Values `next_expense_date`, `account_name`, `total`, `last_created_date`, `recurrence_name`, `customer_name` and `created_time` |
| **page**            | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                        |
| **per_page**        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                       |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240/expenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "expensehistory": [
        {
            "expense_id": 982000000567250,
            "date": "string",
            "account_name": "Rent",
            "customer_name": "Bowman & Co",
            "total": 128.25,
            "status": "active",
            "vendor_name": " ",
            "paid_through_account_name": "Undeposited Funds"
        }
    ],
    "page_context": [
        {
            "sort_column": "account_name",
            "filter_by": "Status.Billable",
            "search_text": "Rent"
        }
    ]
}
```

---

## List recurring expense history

Get history and comments of a recurring expense.

*   **OAuth Scope:** `ZohoBooks.expenses.READ`

### Path Parameters

| Parameter                | Type   | Required | Description                                 |
| :----------------------- | :----- | :------- | :------------------------------------------ |
| **recurring_expense_id** | string | Required | Unique identifier of the recurring expense. |

### Query Parameters

| Parameter           | Type   | Required | Description            |
| :------------------ | :----- | :------- | :--------------------- |
| **organization_id** | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/recurringexpenses/982000000567240/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "comments": {
        "comment_id": 982000000567272,
        "recurring_expense_id": 982000000567240,
        "description": " ",
        "commented_by_id": 982000000554041,
        "commented_by": "John David",
        "date": "string",
        "time": "2.41 AM",
        "operation_type": "Added",
        "transaction_id": " ",
        "transaction_type": "expense"
    }
}
```