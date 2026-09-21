# Expenses

A typical expense is incurred when money goes out of your pocket. Whether its a product you buy from your vendor to run your business, or food that you eat while on business trips, it's important to track the money you spend.

## Attributes

| Attribute                         | Type    | Description                                                                                             |
| :-------------------------------- | :------ | :------------------------------------------------------------------------------------------------------ |
| **expense_id**                    | string  | Unique identifier of the expense.                                                                       |
| **transaction_id**                | string  |                                                                                                         |
| **transaction_type**              | string  |                                                                                                         |
| **gst_no**                        | string  | *India only.* 15 digit GST identification number of the vendor.                                         |
| **gst_treatment**                 | string  | *India only.* Choose whether the contact is GST registered/unregistered/consumer/overseas.              |
| **tax_treatment**                 | string  | *GCC, Kenya, South Africa only.* VAT treatment for the expense.                                         |
| **destination_of_supply**         | string  | *India only.* Place where the goods/services are supplied to.                                           |
| **destination_of_supply_state**   | string  | *India only.* State to where goods/services are supplied                                                |
| **place_of_supply**               | string  | *GCC only.* The place of supply is where a transaction is considered to have occurred for VAT purposes. |
| **hsn_or_sac**                    | string  | *India, Kenya only.* Add HSN/SAC code for your goods/services                                           |
| **source_of_supply**              | string  | *India only.* Place from where the goods/services are supplied.                                         |
| **paid_through_account_name**     | string  | Enter the name of the paid through account.                                                             |
| **vat_reg_no**                    | string  | Enter VAT registration number.                                                                          |
| **reverse_charge_tax_id**         | string  | ID of the reverse charge tax                                                                            |
| **reverse_charge_tax_name**       | string  | *India only.* Enter name of the reverse charge tax                                                      |
| **reverse_charge_tax_percentage** | double  | *India only.* Enter percentage of the reverse charge tax                                                |
| **reverse_charge_tax_amount**     | integer | *India only.* Enter amount of the reverse charge tax                                                    |
| **tax_amount**                    | double  |                                                                                                         |
| **is_itemized_expense**           | boolean |                                                                                                         |
| **is_pre_gst**                    | string  | *India only.* Applicable for transactions that fall before july 1, 2017                                 |
| **trip_id**                       | string  | Enter trip ID                                                                                           |
| **trip_number**                   | string  | Enter trip number                                                                                       |
| **reverse_charge_vat_total**      | double  | *India only.* Enter total of the reverse charge vat tax.                                                |
| **acquisition_vat_total**         | double  | Enter acquisition vat total.                                                                            |
| **acquisition_vat_summary**       | array   | Summary of acquisition VAT. Contains objects with `tax` which has `tax_name` and `tax_amount`.          |
| **reverse_charge_vat_summary**    | array   | Summary of reverse charge VAT. Contains objects with `tax` which has `tax_name` and `tax_amount`.       |
| **taxes**                         | array   | *Mexico only.* List of taxes applied. Contains `tax_id` and `tax_amount`.                               |
| **expense_item_id**               | string  |                                                                                                         |
| **account_id**                    | string  | ID of the expense account.                                                                              |
| **account_name**                  | string  |                                                                                                         |
| **date**                          | string  | Date of the expense                                                                                     |
| **tax_id**                        | string  |                                                                                                         |
| **tax_name**                      | string  |                                                                                                         |
| **tax_percentage**                | double  |                                                                                                         |
| **currency_id**                   | string  |                                                                                                         |
| **currency_code**                 | string  |                                                                                                         |
| **exchange_rate**                 | double  |                                                                                                         |
| **sub_total**                     | double  |                                                                                                         |
| **total**                         | double  |                                                                                                         |
| **bcy_total**                     | double  |                                                                                                         |
| **amount**                        | double  | Amount of the Expense.                                                                                  |
| **is_inclusive_tax**              | boolean |                                                                                                         |
| **reference_number**              | string  | Reference number of the expense. Max-length [100]                                                       |
| **description**                   | string  | Description of the expense. Max-length [100]                                                            |
| **is_billable**                   | boolean |                                                                                                         |
| **is_personal**                   | boolean |                                                                                                         |
| **customer_id**                   | string  | ID of the expense account.                                                                              |
| **customer_name**                 | string  | Name of the Custome for which expense is raised. Max-length [100]                                       |
| **expense_receipt_name**          | string  |                                                                                                         |
| **expense_receipt_type**          | string  |                                                                                                         |
| **last_modified_time**            | string  |                                                                                                         |
| **status**                        | string  | Expense status                                                                                          |
| **invoice_id**                    | string  |                                                                                                         |
| **invoice_number**                | string  |                                                                                                         |
| **location_id**                   | string  | Location ID                                                                                             |
| **location_name**                 | string  | Name of the location.                                                                                   |
| **project_id**                    | string  | ID of the project associated with the customer.                                                         |
| **project_name**                  | string  |                                                                                                         |
| **mileage_rate**                  | double  | Mileage rate for a particular mileage expense.                                                          |
| **mileage_type**                  | string  |                                                                                                         |
| **expense_type**                  | string  |                                                                                                         |
| **start_reading**                 | double  | Start reading of odometer when creating a mileage expense where `mileage_type` is `odometer`.           |
| **end_reading**                   | double  | End reading of odometer when creating a mileage expense where `mileage_type` is `odometer`.             |
| **custom_fields**                 | array   | Additional fields for the payments. Contains `index`, `value`, `label`, `data_type`.                    |

---

## Create an Expense
Create billable or non-billable expense.

`OAuth Scope : ZohoBooks.expenses.CREATE`

### Arguments

| Argument                     | Type    | Required   | Description                                                                       |
| :--------------------------- | :------ | :--------- | :-------------------------------------------------------------------------------- |
| `account_id`                 | string  | (Required) | ID of the expense account.                                                        |
| `date`                       | string  | (Required) | Date of the expense                                                               |
| `amount`                     | double  | (Required) | Amount of the Expense.                                                            |
| `tax_id`                     | string  | (Optional) |                                                                                   |
| `source_of_supply`           | string  | (Optional) | *India only.* Place from where the goods/services are supplied.                   |
| `destination_of_supply`      | string  | (Optional) | *India only.* Place where the goods/services are supplied to.                     |
| `place_of_supply`            | string  | (Optional) | *GCC only.* The place of supply for VAT purposes.                                 |
| `hsn_or_sac`                 | string  | (Optional) | *India, Kenya only.* Add HSN/SAC code.                                            |
| `gst_no`                     | string  | (Optional) | *India only.* 15 digit GST identification number of the vendor.                   |
| `reverse_charge_tax_id`      | string  | (Optional) | ID of the reverse charge tax                                                      |
| `location_id`                | string  | (Optional) | Location ID                                                                       |
| `line_items`                 | array   | (Optional) | Array of line items for itemized expenses. See line items attributes below.       |
| `taxes`                      | array   | (Optional) | *Mexico only.* List of taxes applied.                                             |
| `is_inclusive_tax`           | boolean | (Optional) |                                                                                   |
| `is_billable`                | boolean | (Optional) |                                                                                   |
| `reference_number`           | string  | (Optional) | Reference number of the expense. Max-length [100]                                 |
| `description`                | string  | (Optional) | Description of the expense. Max-length [100]                                      |
| `customer_id`                | string  | (Optional) | ID of the expense account.                                                        |
| `currency_id`                | string  | (Optional) |                                                                                   |
| `exchange_rate`              | double  | (Optional) |                                                                                   |
| `project_id`                 | string  | (Optional) | ID of the project associated with the customer.                                   |
| `mileage_type`               | string  | (Optional) |                                                                                   |
| `vat_treatment`              | string  | (Optional) | *UK only.* VAT treatment for the expense.                                         |
| `tax_treatment`              | string  | (Optional) | *GCC, Kenya, South Africa only.* VAT treatment for the expense.                   |
| `product_type`               | string  | (Optional) | *UK, South Africa only.* Type of the expense.                                     |
| `acquisition_vat_id`         | string  | (Optional) | *UK only.* ID of the tax applied for EU - goods expense acquisition VAT.          |
| `reverse_charge_vat_id`      | string  | (Optional) | *UK only.* ID of the tax applied for non UK - service expense reverse charge VAT. |
| `start_reading`              | double  | (Optional) | Start reading of odometer.                                                        |
| `end_reading`                | double  | (Optional) | End reading of odometer.                                                          |
| `distance`                   | string  | (Optional) | Distance travelled.                                                               |
| `mileage_unit`               | string  | (Optional) | Unit of the distance travelled. Allowed Values: `km` and `mile`                   |
| `mileage_rate`               | double  | (Optional) | Mileage rate for a particular mileage expense.                                    |
| `employee_id`                | string  | (Optional) | *UK only.* ID of the employee who has submitted this mileage expense.             |
| `vehicle_type`               | string  | (Optional) | *UK only.* Vehicle type. Allowed Values: `car`, `van`, `motorcycle` and `bike`    |
| `can_reclaim_vat_on_mileage` | string  | (Optional) | *UK only.* To specify if tax can be reclaimed for this mileage expense.           |
| `fuel_type`                  | string  | (Optional) | *UK only.* Fuel type. Allowed Values: `petrol`, `lpg` and `diesel`                |
| `engine_capacity_range`      | string  | (Optional) | *UK only.* Engine capacity range.                                                 |
| `paid_through_account_id`    | string  | (Required) | Search expenses by paid through account id.                                       |
| `vendor_id`                  | string  | (Optional) | ID of the vendor the expense is made.                                             |
| `custom_fields`              | array   | (Optional) | Custom fields for an expense.                                                     |

### Line Item Attributes (for `line_items` array)
| Attribute               | Type   | Description                                   |
| :---------------------- | :----- | :-------------------------------------------- |
| `line_item_id`          | string |                                               |
| `account_id`            | string | (Required) ID of the expense account.         |
| `description`           | string | Description of the expense. Max-length [100]  |
| `amount`                | double | (Required) Amount of the Expense.             |
| `tax_id`                | string |                                               |
| `item_order`            | string |                                               |
| `product_type`          | string | *UK, South Africa only.* Type of the expense. |
| `acquisition_vat_id`    | string | *UK only.*                                    |
| `reverse_charge_vat_id` | string | *UK only.*                                    |
| `reverse_charge_tax_id` | string | ID of the reverse charge tax                  |
| `tax_exemption_code`    | string | *India only.* Enter tax exemption code        |
| `tax_exemption_id`      | string | *India only.* Enter tax exemption ID          |
| `location_id`           | string | Location ID                                   |

### Query Parameters

| Parameter         | Type   | Required   | Description                                                                                                                     |
| :---------------- | :----- | :--------- | :------------------------------------------------------------------------------------------------------------------------------ |
| `organization_id` | string | (Required) | ID of the organization                                                                                                          |
| `receipt`         | binary | (Optional) | Expense receipt file to attach. Allowed Extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp`, `pdf`, `xls`, `xlsx`, `doc` and `docx`. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/expenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_id": 982000000561057,
    "date": "2013-11-18",
    "amount": 112.5,
    "tax_id": 982000000566007,
    "source_of_supply": "AP",
    "destination_of_supply": "TN",
    "place_of_supply": "DU",
    "hsn_or_sac": 80540,
    "gst_no": "22AAAAA0000A1Z5",
    "reverse_charge_tax_id": 982000000561063,
    "location_id": "460000000038080",
    "line_items": [
        {
            "line_item_id": 10763000000140068,
            "account_id": 982000000561057,
            "description": "Marketing",
            "amount": 112.5,
            "tax_id": 982000000566007,
            "item_order": 1,
            "product_type": "goods",
            "acquisition_vat_id": " ",
            "reverse_charge_vat_id": " ",
            "reverse_charge_tax_id": 982000000561063,
            "tax_exemption_code": "string",
            "tax_exemption_id": 982000000561067,
            "location_id": "460000000038080"
        }
    ],
    "taxes": [
        {
            "tax_id": 982000000566007,
            "tax_amount": 11.85
        }
    ],
    "is_inclusive_tax": false,
    "is_billable": true,
    "reference_number": null,
    "description": "Marketing",
    "customer_id": 982000000567001,
    "currency_id": 982000000567001,
    "exchange_rate": 1,
    "project_id": 982000000567226,
    "mileage_type": "non_mileage",
    "vat_treatment": "eu_vat_not_registered",
    "tax_treatment": "vat_registered",
    "product_type": "goods",
    "acquisition_vat_id": " ",
    "reverse_charge_vat_id": " ",
    "start_reading": " ",
    "end_reading": " ",
    "distance": " ",
    "mileage_unit": " ",
    "mileage_rate": " ",
    "employee_id": "982000000030040",
    "vehicle_type": " ",
    "can_reclaim_vat_on_mileage": " ",
    "fuel_type": " ",
    "engine_capacity_range": " ",
    "paid_through_account_id": 982000000567250,
    "vendor_id": " ",
    "custom_fields": []
}'
```

---

## Update an expense using a custom field's unique value

Update an expense by providing a custom field's unique value in the header.

`OAuth Scope : ZohoBooks.expenses.UPDATE`

### Arguments
See **Update an Expense** arguments.

### Query Parameters

| Parameter         | Type    | Required   | Description                     |
| :---------------- | :------ | :--------- | :------------------------------ |
| `organization_id` | string  | (Required) | ID of the organization          |
| `receipt`         | binary  | (Optional) | Expense receipt file to attach. |
| `delete_receipt`  | boolean | (Optional) |                                 |

### Headers

| Header                      | Type    | Required   | Description                                             |
| :-------------------------- | :------ | :--------- | :------------------------------------------------------ |
| `X-Unique-Identifier-Key`   | string  | (Required) | Unique CustomField Api Name                             |
| `X-Unique-Identifier-Value` | string  | (Required) | Unique CustomField Value                                |
| `X-Upsert`                  | boolean | (Optional) | If `true` and no record is found, creates a new invoice |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/expenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{
    "account_id": 982000000561057,
    "date": "2013-11-18",
    "amount": 120.5,
    ...
}'
```

---

## List Expenses
List all the Expenses with pagination.

`OAuth Scope : ZohoBooks.expenses.READ`

### Query Parameters

| Parameter                 | Type    | Required   | Description                                                             |
| :------------------------ | :------ | :--------- | :---------------------------------------------------------------------- |
| `organization_id`         | string  | (Required) | ID of the organization                                                  |
| `description`             | string  | (Optional) | Search expenses by description.                                         |
| `reference_number`        | string  | (Optional) | Search expenses by reference number.                                    |
| `date`                    | string  | (Optional) | Search expenses by expense date. Format [yyyy-mm-dd]                    |
| `status`                  | string  | (Optional) | Search expenses by expense status.                                      |
| `amount`                  | double  | (Optional) | Search expenses by amount.                                              |
| `account_name`            | string  | (Optional) | Search expenses by expense account name.                                |
| `customer_name`           | string  | (Optional) | Search expenses by customer name.                                       |
| `vendor_name`             | string  | (Optional) | Search expenses by vendor name.                                         |
| `customer_id`             | string  | (Optional) | ID of the expense account.                                              |
| `vendor_id`               | string  | (Optional) | ID of the vendor the expense is made.                                   |
| `recurring_expense_id`    | string  | (Optional) | Search expenses by recurring expense id.                                |
| `paid_through_account_id` | string  | (Optional) | Search expenses by paid through account id.                             |
| `search_text`             | string  | (Optional) | Search expenses by account name or description or customer/vendor name. |
| `sort_column`             | string  | (Optional) | Sort expenses.                                                          |
| `filter_by`               | string  | (Optional) | Filter expenses by expense status.                                      |
| `page`                    | integer | (Optional) | Page number to be fetched. Default value is 1.                          |
| `per_page`                | integer | (Optional) | Number of records to be fetched per page. Default value is 200.         |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/expenses?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Update an Expense
Update an existing Expense.

`OAuth Scope : ZohoBooks.expenses.UPDATE`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Arguments

| Argument                     | Type    | Required   | Description                                 |
| :--------------------------- | :------ | :--------- | :------------------------------------------ |
| `account_id`                 | string  | (Required) | ID of the expense account.                  |
| `date`                       | string  | (Required) | Date of the expense                         |
| `amount`                     | double  | (Required) | Amount of the Expense.                      |
| `tax_id`                     | string  | (Optional) |                                             |
| `source_of_supply`           | string  | (Optional) | *India only.*                               |
| `destination_of_supply`      | string  | (Optional) | *India only.*                               |
| `place_of_supply`            | string  | (Optional) | *GCC only.*                                 |
| `hsn_or_sac`                 | string  | (Optional) | *India, Kenya only.*                        |
| `gst_no`                     | string  | (Optional) | *India only.*                               |
| `reverse_charge_tax_id`      | string  | (Optional) |                                             |
| `line_items`                 | array   | (Optional) | Array of line items.                        |
| `location_id`                | string  | (Optional) | Location ID                                 |
| `taxes`                      | array   | (Optional) | *Mexico only.*                              |
| `is_inclusive_tax`           | boolean | (Optional) |                                             |
| `is_billable`                | boolean | (Optional) |                                             |
| `reference_number`           | string  | (Optional) | Reference number.                           |
| `description`                | string  | (Optional) | Description.                                |
| `customer_id`                | string  | (Optional) | ID of the customer.                         |
| `currency_id`                | string  | (Optional) |                                             |
| `exchange_rate`              | double  | (Optional) |                                             |
| `project_id`                 | string  | (Optional) | ID of the project.                          |
| `mileage_type`               | string  | (Optional) |                                             |
| `vat_treatment`              | string  | (Optional) | *UK only.*                                  |
| `tax_treatment`              | string  | (Optional) | *GCC, Kenya, South Africa only.*            |
| `product_type`               | string  | (Optional) | *UK, South Africa only.*                    |
| `acquisition_vat_id`         | string  | (Optional) | *UK only.*                                  |
| `reverse_charge_vat_id`      | string  | (Optional) | *UK only.*                                  |
| `start_reading`              | double  | (Optional) |                                             |
| `end_reading`                | double  | (Optional) |                                             |
| `distance`                   | string  | (Optional) |                                             |
| `mileage_unit`               | string  | (Optional) |                                             |
| `mileage_rate`               | double  | (Optional) |                                             |
| `employee_id`                | string  | (Optional) | *UK only.*                                  |
| `vehicle_type`               | string  | (Optional) | *UK only.*                                  |
| `can_reclaim_vat_on_mileage` | string  | (Optional) | *UK only.*                                  |
| `fuel_type`                  | string  | (Optional) | *UK only.*                                  |
| `engine_capacity_range`      | string  | (Optional) | *UK only.*                                  |
| `paid_through_account_id`    | string  | (Required) | Search expenses by paid through account id. |
| `vendor_id`                  | string  | (Optional) | ID of the vendor.                           |
| `custom_fields`              | array   | (Optional) | Custom fields.                              |

### Query Parameters

| Parameter         | Type    | Required   | Description                     |
| :---------------- | :------ | :--------- | :------------------------------ |
| `organization_id` | string  | (Required) | ID of the organization          |
| `receipt`         | binary  | (Optional) | Expense receipt file to attach. |
| `delete_receipt`  | boolean | (Optional) |                                 |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "account_id": 982000000561057,
    "date": "2013-11-18",
    "amount": 120.5,
    ...
}'
```

---

## Get an Expense
Get the details of the Expense.

`OAuth Scope : ZohoBooks.expenses.READ`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete an Expense
Delete an existing expense.

`OAuth Scope : ZohoBooks.expenses.DELETE`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## List expense History & Comments
Get history and comments of expense.

`OAuth Scope : ZohoBooks.expenses.READ`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Create an employee
Create an employee for an expense.

`OAuth Scope : ZohoBooks.expenses.CREATE`

### Arguments

| Argument | Type   | Required   | Description |
| :------- | :----- | :--------- | :---------- |
| `name`   | string | (Required) |             |
| `email`  | string | (Required) |             |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/employees?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "name": "John David",
    "email": "johnsmith@zilliuminc.com"
}'
```

---

## List employees
List employees with pagination.

`OAuth Scope : ZohoBooks.expenses.READ`

### Query Parameters

| Parameter         | Type    | Required   | Description                                                     |
| :---------------- | :------ | :--------- | :-------------------------------------------------------------- |
| `organization_id` | string  | (Required) | ID of the organization                                          |
| `page`            | integer | (Optional) | Page number to be fetched. Default value is 1.                  |
| `per_page`        | integer | (Optional) | Number of records to be fetched per page. Default value is 200. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/employees?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Get an employee
Get the details of the employee.

`OAuth Scope : ZohoBooks.expenses.READ`

### Path Parameters

| Parameter     | Type   | Required   | Description                       |
| :------------ | :----- | :--------- | :-------------------------------- |
| `employee_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/employees/982000000030040?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete an employee
Delete an existing employee.

`OAuth Scope : ZohoBooks.expenses.DELETE`

### Path Parameters

| Parameter     | Type   | Required   | Description                       |
| :------------ | :----- | :--------- | :-------------------------------- |
| `employee_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/employee/982000000030040?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add receipt to an expense.
Attach a receipt to an expense.

`OAuth Scope : ZohoBooks.expenses.CREATE`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description                                                                                                                     |
| :---------------- | :----- | :--------- | :------------------------------------------------------------------------------------------------------------------------------ |
| `organization_id` | string | (Required) | ID of the organization                                                                                                          |
| `receipt`         | binary | (Optional) | Expense receipt file to attach. Allowed Extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp`, `pdf`, `xls`, `xlsx`, `doc` and `docx`. |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049/receipt?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Get an expense receipt
Returns the receipt attached to the expense.

`OAuth Scope : ZohoBooks.expenses.READ`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type    | Required   | Description                       |
| :---------------- | :------ | :--------- | :-------------------------------- |
| `organization_id` | string  | (Required) | ID of the organization            |
| `preview`         | boolean | (Optional) | Get the thumbnail of the receipt. |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049/receipt?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Delete a receipt
Delete the receipt attached to the expense.

`OAuth Scope : ZohoBooks.expenses.DELETE`

### Path Parameters

| Parameter    | Type   | Required   | Description                       |
| :----------- | :----- | :--------- | :-------------------------------- |
| `expense_id` | string | (Required) | Unique identifier of the expense. |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049/receipt?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

---

## Add attachment to an expense
Attach one or multiple files to an expense. This endpoint allows you to attach various types of documents to support your expense records. Returns document details for the uploaded attachments.

`OAuth Scope : ZohoBooks.expenses.CREATE`

### Arguments

| Argument       | Type    | Required   | Description                                                                                                                                     |
| :------------- | :------ | :--------- | :---------------------------------------------------------------------------------------------------------------------------------------------- |
| `attachment`   | binary  | (Required) | Expense attachment file to attach. Allowed Extensions: `gif`, `png`, `jpeg`, `jpg`, `bmp`, `pdf`, `xls`, `xlsx`, `doc`, `docx`, `txt` and `csv` |
| `totalFiles`   | integer | (Optional) | Total number of files being uploaded.                                                                                                           |
| `document_ids` | array   | (Optional) | Array of document IDs for batch processing.                                                                                                     |

### Path Parameters

| Parameter    | Type   | Required   | Description |
| :----------- | :----- | :--------- | :---------- |
| `expense_id` | string | (Required) |             |

### Query Parameters

| Parameter         | Type   | Required   | Description            |
| :---------------- | :----- | :--------- | :--------------------- |
| `organization_id` | string | (Required) | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/expenses/982000000030049/attachment?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: multipart/form-data' \
  --form field1=value1 \
  --form field2=value2
```