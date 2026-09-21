# Fixed Assets

Fixed assets are long-term tangible assets that a business owns and uses to produce goods and services. In Zoho Books, you can record fixed assets and automatically calculate depreciation for them. You can sell or write off the asset when it is likely to generate a profit, after it has completed its useful life, or when it has been fully depreciated.

## Attributes

| Attribute                    | Type    | Description                                                                                                                                                                                                                               |
| :--------------------------- | :------ | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| fixed_asset_id               | string  | Unique identifier of the fixed asset.                                                                                                                                                                                                     |
| asset_name                   | string  | Enter the name of the fixed asset.                                                                                                                                                                                                        |
| status                       | string  | Status of the fixed asset                                                                                                                                                                                                                 |
| asset_number                 | string  | Number of the asset                                                                                                                                                                                                                       |
| asset_number_prefix          | string  | Prefix of the asset number                                                                                                                                                                                                                |
| asset_number_suffix          | integer | Suffix of the asset number                                                                                                                                                                                                                |
| description                  | string  | Description of the asset                                                                                                                                                                                                                  |
| total_life                   | number  | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| fixed_asset_type_id          | string  | Associate the fixed asset with a fixed asset type by specifying fixed asset type id.                                                                                                                                                      |
| fixed_asset_type_name        | string  | Name of fixed asset type                                                                                                                                                                                                                  |
| depreciation_method          | string  | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_percentage      | double  | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| depreciation_frequency       | string  | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| asset_cost                   | double  | Enter the purchase cost of the asset                                                                                                                                                                                                      |
| dep_start_value              | double  | Enter the value from which depreciation will be calculated.                                                                                                                                                                               |
| salvage_value                | double  | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| asset_purchase_date          | string  | Enter the Purchase date of the asset                                                                                                                                                                                                      |
| current_asset_value          | double  | Current value of the asset                                                                                                                                                                                                                |
| accumulated_dep_value        | double  | Accumulated value of the asset                                                                                                                                                                                                            |
| serial_no                    | string  | serial number of the asset                                                                                                                                                                                                                |
| depreciation_start_date      | string  | Enter the depreciation start date of the asset                                                                                                                                                                                            |
| last_depreciation_date       | string  | Last depreciation date                                                                                                                                                                                                                    |
| asset_account_id             | string  | Enter the account id to track the fixed asset.                                                                                                                                                                                            |
| asset_account_name           | string  | Name of the asset account                                                                                                                                                                                                                 |
| expense_account_id           | string  | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| expense_account_name         | string  | Name of the expense account                                                                                                                                                                                                               |
| depreciation_account_id      | string  | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_account_name    | string  | Name of the depreciation account                                                                                                                                                                                                          |
| computation_type             | string  | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |
| warranty_expiry_date         | string  | Enter the warranty expiration date of the asset                                                                                                                                                                                           |
| notes                        | string  | Provide notes for the asset, if required                                                                                                                                                                                                  |
| tags                         | array   |                                                                                                                                                                                                                                           |
| tags.tag_id                  | string  | ID of the tag                                                                                                                                                                                                                             |
| tags.tag_option_id           | string  | Option ID of the tag                                                                                                                                                                                                                      |
| associated_transactions      | array   | Transactions associated with the fixed asset                                                                                                                                                                                              |
| comments                     | array   |                                                                                                                                                                                                                                           |
| comments.comment_id          | string  | Unique identifier of the comment.                                                                                                                                                                                                         |
| comments.description         | string  | It displays the description of the comment added for the fixed asset                                                                                                                                                                      |
| comments.commented_by_id     | string  | User ID of the user who added comment                                                                                                                                                                                                     |
| comments.commented_by        | string  | Name of the user who added comment                                                                                                                                                                                                        |
| comments.comment_type        | string  | Type of the comment                                                                                                                                                                                                                       |
| comments.date                | string  | Comment added date                                                                                                                                                                                                                        |
| comments.date_description    | string  | Description of date                                                                                                                                                                                                                       |
| comments.time                | string  | Comment added time                                                                                                                                                                                                                        |
| comments.operation_type      | string  | Operation type of the comment                                                                                                                                                                                                             |
| custom_fields                | array   |                                                                                                                                                                                                                                           |
| custom_fields.customfield_id | string  | ID of the Custom Field                                                                                                                                                                                                                    |
| custom_fields.value          | string  | Value of the Custom Field                                                                                                                                                                                                                 |
| expense_account_id           | string  | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| depreciation_account_id      | string  | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_method          | string  | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_frequency       | string  | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| depreciation_percentage      | double  | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| total_life                   | number  | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| salvage_value                | double  | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| computation_type             | string  | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |

### Fixed Asset Example
```json
{
    "fixed_asset_id": "3640355000000319008",
    "asset_name": "Laptop",
    "status": "draft",
    "asset_number": "FA-00013",
    "asset_number_prefix": "FA-",
    "asset_number_suffix": 13,
    "description": "string",
    "total_life": 60,
    "fixed_asset_type_id": "3640355000000319008",
    "fixed_asset_type_name": "Machines",
    "depreciation_method": "declining_method",
    "depreciation_percentage": 12,
    "depreciation_frequency": "yearly",
    "asset_cost": 1000,
    "dep_start_value": 1000,
    "salvage_value": 100,
    "asset_purchase_date": "2024-12-17",
    "current_asset_value": 1000,
    "accumulated_dep_value": 0,
    "serial_no": "SN-0001",
    "depreciation_start_date": "2024-12-17",
    "last_depreciation_date": "",
    "asset_account_id": "3640355000000000367",
    "asset_account_name": "Furniture and Equipment",
    "expense_account_id": "3640355000000000421",
    "expense_account_name": "Telephone Expense",
    "depreciation_account_id": "3640355000000000367",
    "depreciation_account_name": "Furniture and Equipment",
    "computation_type": "prorata_basis",
    "warranty_expiry_date": "2027-12-17",
    "notes": "This is a laptop Model 2024",
    "tags": [
        {
            "tag_id": "460000000094001",
            "tag_option_id": "460000000048001",
            "tag_name": "Location",
            "tag_option_name": "USA"
        }
    ],
    "associated_transactions": [
        {}
    ],
    "comments": [
        {
            "comment_id": "3640355000000319013",
            "description": "string",
            "commented_by_id": "3640355000000075001",
            "commented_by": "Zoho Books",
            "comment_type": "system",
            "date": "2024-12-17",
            "date_description": "few seconds ago",
            "time": "11:34 AM",
            "operation_type": "Added"
        }
    ],
    "custom_fields": [
        {
            "customfield_id": "460000000098001",
            "value": "Normal"
        }
    ]
}
```

---

## Create a fixed asset
Create a fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets`

### Arguments
| Argument                     | Type   | Required | Description                                                                                                                                                                                                                               |
| :--------------------------- | :----- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| asset_name                   | string | Required | Enter the name of the fixed asset.                                                                                                                                                                                                        |
| fixed_asset_type_id          | string | Required | Associate the fixed asset with a fixed asset type by specifying fixed asset type id.                                                                                                                                                      |
| asset_account_id             | string | Required | Enter the account id to track the fixed asset.                                                                                                                                                                                            |
| expense_account_id           | string | Optional | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| depreciation_account_id      | string | Optional | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_method          | string | Optional | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_frequency       | string | Optional | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| depreciation_percentage      | double | Optional | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| total_life                   | number | Optional | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| salvage_value                | double | Optional | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| depreciation_start_date      | string | Optional | Enter the depreciation start date of the asset                                                                                                                                                                                            |
| description                  | string | Optional | Description of the asset                                                                                                                                                                                                                  |
| asset_cost                   | double | Required | Enter the purchase cost of the asset                                                                                                                                                                                                      |
| computation_type             | string | Optional | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |
| warranty_expiry_date         | string | Optional | Enter the warranty expiration date of the asset                                                                                                                                                                                           |
| asset_purchase_date          | string | Required | Enter the Purchase date of the asset                                                                                                                                                                                                      |
| serial_no                    | string | Optional | serial number of the asset                                                                                                                                                                                                                |
| dep_start_value              | double | Optional | Enter the value from which depreciation will be calculated.                                                                                                                                                                               |
| notes                        | string | Optional | Provide notes for the asset, if required                                                                                                                                                                                                  |
| tags                         | array  | Optional |                                                                                                                                                                                                                                           |
| tags.tag_id                  | string | Optional | ID of the tag                                                                                                                                                                                                                             |
| tags.tag_option_id           | string | Optional | Option ID of the tag                                                                                                                                                                                                                      |
| custom_fields                | array  | Optional |                                                                                                                                                                                                                                           |
| custom_fields.customfield_id | string | Optional | ID of the Custom Field                                                                                                                                                                                                                    |
| custom_fields.value          | string | Optional | Value of the Custom Field                                                                                                                                                                                                                 |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "asset_name": "Laptop",
    "fixed_asset_type_id": "3640355000000319008",
    "asset_account_id": "3640355000000000367",
    "expense_account_id": "3640355000000000421",
    "depreciation_account_id": "3640355000000000367",
    "depreciation_method": "declining_method",
    "depreciation_frequency": "yearly",
    "depreciation_percentage": 12,
    "total_life": 60,
    "salvage_value": 100,
    "depreciation_start_date": "2024-12-17",
    "description": "string",
    "asset_cost": 1000,
    "computation_type": "prorata_basis",
    "warranty_expiry_date": "2027-12-17",
    "asset_purchase_date": "2024-12-17",
    "serial_no": "SN-0001",
    "dep_start_value": 1000,
    "notes": "This is a laptop Model 2024",
    "tags": [
        {
            "tag_id": "460000000094001",
            "tag_option_id": "460000000048001"
        }
    ],
    "custom_fields": [
        {
            "customfield_id": "460000000098001",
            "value": "Normal"
        }
    ]
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The fixed asset has been created.",
    "fixed_asset": {
        "fixed_asset_id": "3640355000000319008",
        "asset_name": "Laptop",
        "status": "draft",
        "asset_number": "FA-00013",
        "asset_number_prefix": "FA-",
        "asset_number_suffix": 13,
        "description": "string",
        "total_life": 60,
        "fixed_asset_type_id": "3640355000000319008",
        "fixed_asset_type_name": "Machines",
        "depreciation_method": "declining_method",
        "depreciation_percentage": 12,
        "depreciation_frequency": "yearly",
        "asset_cost": 1000,
        "dep_start_value": 1000,
        "salvage_value": 100,
        "asset_purchase_date": "2024-12-17",
        "current_asset_value": 1000,
        "accumulated_dep_value": 0,
        "serial_no": "SN-0001",
        "depreciation_start_date": "2024-12-17",
        "last_depreciation_date": "",
        "asset_account_id": "3640355000000000367",
        "asset_account_name": "Furniture and Equipment",
        "expense_account_id": "3640355000000000421",
        "expense_account_name": "Telephone Expense",
        "depreciation_account_id": "3640355000000000367",
        "depreciation_account_name": "Furniture and Equipment",
        "computation_type": "prorata_basis",
        "warranty_expiry_date": "2027-12-17",
        "notes": "This is a laptop Model 2024",
        "tags": [
            {
                "tag_id": "460000000094001",
                "tag_option_id": "460000000048001",
                "tag_name": "Location",
                "tag_option_name": "USA"
            }
        ],
        "associated_transactions": [
            {...}
        ],
        "comments": [
            {
                "comment_id": "3640355000000319013",
                "description": "string",
                "commented_by_id": "3640355000000075001",
                "commented_by": "Zoho Books",
                "comment_type": "system",
                "date": "2024-12-17",
                "date_description": "few seconds ago",
                "time": "11:34 AM",
                "operation_type": "Added"
            }
        ],
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Get fixed asset list
fixed asset list.

`OAuth Scope : ZohoBooks.fixedasset.READ`

**Endpoint:**
`GET /fixedassets`

### Query Parameters
| Parameter       | Type    | Required | Description                                                                                                                                                                              |
| :-------------- | :------ | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| organization_id | string  | Required | ID of the organization                                                                                                                                                                   |
| filter_by       | string  | Optional | Filter fixed asset by fixed asset status. Allowed Values: `Status.All`, `Status.Active`, `Status.Cancel`, `Status.FullyDepreciated`, `Status.WriteOff`, `Status.Sold` and `Status.Draft` |
| sort_column     | string  | Optional | Sort fixed asset list. Allowed Values: `asset_name`, `asset_number`, `asset_cost`, `created_time` and `current_asset_value`                                                              |
| sort_order      | string  | Optional | Sort fixed asset list in ascendeing or descending order. Allowed Values: `A` and `D`                                                                                                     |
| page            | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                           |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                          |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/fixedassets?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "fixedassets": [
        {
            "fixed_asset_id": "3640355000000319008",
            "asset_number": "FA-00013",
            "asset_name": "Laptop",
            "status": "draft",
            "current_asset_value": 1000,
            "asset_cost": 1000,
            "fixed_asset_type_name": "Machines"
        },
        {...},
        {...}
    ]
}
```

---

## Update a fixed asset
Updates the fixed asset with given information.

`OAuth Scope : ZohoBooks.fixedasset.UPDATE`

**Endpoint:**
`PUT /fixedassets/{fixed_asset_id}`

### Arguments
| Argument                     | Type   | Required | Description                                                                                                                                                                                                                               |
| :--------------------------- | :----- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| asset_name                   | string | Required | Enter the name of the fixed asset.                                                                                                                                                                                                        |
| fixed_asset_type_id          | string | Required | Associate the fixed asset with a fixed asset type by specifying fixed asset type id.                                                                                                                                                      |
| asset_account_id             | string | Required | Enter the account id to track the fixed asset.                                                                                                                                                                                            |
| expense_account_id           | string | Optional | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| depreciation_account_id      | string | Optional | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_method          | string | Optional | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_frequency       | string | Optional | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| depreciation_percentage      | double | Optional | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| total_life                   | number | Optional | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| salvage_value                | double | Optional | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| depreciation_start_date      | string | Optional | Enter the depreciation start date of the asset                                                                                                                                                                                            |
| description                  | string | Optional | Description of the asset                                                                                                                                                                                                                  |
| asset_cost                   | double | Required | Enter the purchase cost of the asset                                                                                                                                                                                                      |
| computation_type             | string | Optional | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |
| warranty_expiry_date         | string | Optional | Enter the warranty expiration date of the asset                                                                                                                                                                                           |
| asset_purchase_date          | string | Required | Enter the Purchase date of the asset                                                                                                                                                                                                      |
| serial_no                    | string | Optional | serial number of the asset                                                                                                                                                                                                                |
| dep_start_value              | double | Optional | Enter the value from which depreciation will be calculated.                                                                                                                                                                               |
| notes                        | string | Optional | Provide notes for the asset, if required                                                                                                                                                                                                  |
| tags                         | array  | Optional |                                                                                                                                                                                                                                           |
| tags.tag_id                  | string | Optional | ID of the tag                                                                                                                                                                                                                             |
| tags.tag_option_id           | string | Optional | Option ID of the tag                                                                                                                                                                                                                      |
| custom_fields                | array  | Optional |                                                                                                                                                                                                                                           |
| custom_fields.customfield_id | string | Optional | ID of the Custom Field                                                                                                                                                                                                                    |
| custom_fields.value          | string | Optional | Value of the Custom Field                                                                                                                                                                                                                 |

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "asset_name": "Laptop",
    "fixed_asset_type_id": "3640355000000319008",
    "asset_account_id": "3640355000000000367",
    "expense_account_id": "3640355000000000421",
    "depreciation_account_id": "3640355000000000367",
    "depreciation_method": "declining_method",
    "depreciation_frequency": "yearly",
    "depreciation_percentage": 12,
    "total_life": 60,
    "salvage_value": 100,
    "depreciation_start_date": "2024-12-17",
    "description": "string",
    "asset_cost": 1000,
    "computation_type": "prorata_basis",
    "warranty_expiry_date": "2027-12-17",
    "asset_purchase_date": "2024-12-17",
    "serial_no": "SN-0001",
    "dep_start_value": 1000,
    "notes": "This is a laptop Model 2024",
    "tags": [
        {
            "tag_id": "460000000094001",
            "tag_option_id": "460000000048001"
        }
    ],
    "custom_fields": [
        {
            "customfield_id": "460000000098001",
            "value": "Normal"
        }
    ]
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The fixed asset has been updated.",
    "fixed_asset": {
        "fixed_asset_id": "3640355000000319008",
        "asset_name": "Laptop",
        "status": "draft",
        "asset_number": "FA-00013",
        "asset_number_prefix": "FA-",
        "asset_number_suffix": 13,
        "description": "string",
        "total_life": 60,
        "fixed_asset_type_id": "3640355000000319008",
        "fixed_asset_type_name": "Machines",
        "depreciation_method": "declining_method",
        "depreciation_percentage": 12,
        "depreciation_frequency": "yearly",
        "asset_cost": 1000,
        "dep_start_value": 1000,
        "salvage_value": 100,
        "asset_purchase_date": "2024-12-17",
        "current_asset_value": 1000,
        "accumulated_dep_value": 0,
        "serial_no": "SN-0001",
        "depreciation_start_date": "2024-12-17",
        "last_depreciation_date": "",
        "asset_account_id": "3640355000000000367",
        "asset_account_name": "Furniture and Equipment",
        "expense_account_id": "3640355000000000421",
        "expense_account_name": "Telephone Expense",
        "depreciation_account_id": "3640355000000000367",
        "depreciation_account_name": "Furniture and Equipment",
        "computation_type": "prorata_basis",
        "warranty_expiry_date": "2027-12-17",
        "notes": "This is a laptop Model 2024",
        "tags": [
            {
                "tag_id": "460000000094001",
                "tag_option_id": "460000000048001",
                "tag_name": "Location",
                "tag_option_name": "USA"
            }
        ],
        "associated_transactions": [
            {...}
        ],
        "comments": [
            {
                "comment_id": "3640355000000319013",
                "description": "string",
                "commented_by_id": "3640355000000075001",
                "commented_by": "Zoho Books",
                "comment_type": "system",
                "date": "2024-12-17",
                "date_description": "few seconds ago",
                "time": "11:34 AM",
                "operation_type": "Added"
            }
        ],
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Get fixed asset
Get the details of the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.READ`

**Endpoint:**
`GET /fixedassets/{fixed_asset_id}`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "fissed-asset": {
        "fixed_asset_id": "3640355000000319008",
        "asset_name": "Laptop",
        "status": "draft",
        "asset_number": "FA-00013",
        "asset_number_prefix": "FA-",
        "asset_number_suffix": 13,
        "description": "string",
        "total_life": 60,
        "fixed_asset_type_id": "3640355000000319008",
        "fixed_asset_type_name": "Machines",
        "depreciation_method": "declining_method",
        "depreciation_percentage": 12,
        "depreciation_frequency": "yearly",
        "asset_cost": 1000,
        "dep_start_value": 1000,
        "salvage_value": 100,
        "asset_purchase_date": "2024-12-17",
        "current_asset_value": 1000,
        "accumulated_dep_value": 0,
        "serial_no": "SN-0001",
        "depreciation_start_date": "2024-12-17",
        "last_depreciation_date": "",
        "asset_account_id": "3640355000000000367",
        "asset_account_name": "Furniture and Equipment",
        "expense_account_id": "3640355000000000421",
        "expense_account_name": "Telephone Expense",
        "depreciation_account_id": "3640355000000000367",
        "depreciation_account_name": "Furniture and Equipment",
        "computation_type": "prorata_basis",
        "warranty_expiry_date": "2027-12-17",
        "notes": "This is a laptop Model 2024",
        "tags": [
            {
                "tag_id": "460000000094001",
                "tag_option_id": "460000000048001",
                "tag_name": "Location",
                "tag_option_name": "USA"
            }
        ],
        "associated_transactions": [
            {...}
        ],
        "comments": [
            {
                "comment_id": "3640355000000319013",
                "description": "string",
                "commented_by_id": "3640355000000075001",
                "commented_by": "Zoho Books",
                "comment_type": "system",
                "date": "2024-12-17",
                "date_description": "few seconds ago",
                "time": "11:34 AM",
                "operation_type": "Added"
            }
        ],
        "custom_fields": [
            {
                "customfield_id": "460000000098001",
                "value": "Normal"
            }
        ]
    }
}
```

---

## Delete a fixed asset
Deletes the given fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.DELETE`

**Endpoint:**
`DELETE /fixedassets/{fixed_asset_id}`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected fixed asset has been deleted."
}
```

---

## Get fixed asset history
It displays a detailed summary of the asset from acquisition till write off.

`OAuth Scope : ZohoBooks.fixedasset.READ`

**Endpoint:**
`GET /fixedassets/{fixed_asset_id}/history`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type    | Required | Description                                                     |
| :-------------- | :------ | :------- | :-------------------------------------------------------------- |
| organization_id | string  | Required | ID of the organization                                          |
| page            | integer | Optional | Page number to be fetched. Default value is 1.                  |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200. |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/history?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "asset_history": [
        {
            "valuation_id": "3640355000000319008",
            "description": "string",
            "valuation_date": "2024-06-30",
            "depreciated_value": 91.65,
            "current_value": 824.78,
            "accumulated_value": 175.22,
            "type": "depreciation",
            "is_journal_posted": true
        },
        {...},
        {...}
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false
    }
}
```

---

## Get fixed asset's forecast depreciation
It displays a detailed summary of the asset's future depreciation rates.

`OAuth Scope : ZohoBooks.fixedasset.READ`

**Endpoint:**
`GET /fixedassets/{fixed_asset_id}/forecast`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/forecast?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "data": [
        {
            "valuation_date": "2024-06-30",
            "depreciated_value": 91.65,
            "current_value": 824.78,
            "accumulated_value": 175.22
        },
        {...},
        {...}
    ]
}
```

---

## Mark fixed asset as active
Mark the fixed asset as active to start calculating depreciation for the asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/status/active`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/status/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset's status changed"
}
```

---

## Cancel fixed asset
Cancel the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/status/cancel`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/status/cancel?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset's status changed"
}
```

---

## Mark fixed asset as draft
Mark the fixed asset as draft.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/status/draft`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/status/draft?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset's status changed"
}
```

---

## Write off fixed asset
Write off the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/writeoff`

### Arguments
| Argument           | Type   | Required | Description                                                                           |
| :----------------- | :----- | :------- | :------------------------------------------------------------------------------------ |
| date               | string | Required | Enter the date on which the fixed asset is written off                                |
| expense_account_id | string | Required | Enter an account id to track the expenses associated with the written-off fixed asset |
| reason             | string | Required | Enter the reason for writing off the fixed asset                                      |

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/writeoff?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "date": "2024-12-17",
    "expense_account_id": "3640355000000000421",
    "reason": "Asset is damaged"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset has been written off"
}
```

---

## Sell fixed asset
Sell the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/sell`

### Arguments
| Argument           | Type   | Required | Description                                                                                                                                           |
| :----------------- | :----- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| expense_account_id | string | Required | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense** |
| invoice_id         | string | Required | Enter the invoice id associated with selling the fixed asset.                                                                                         |
| line_item_id       | string | Required | Enter the line item id that is associated with the fixed asset account.                                                                               |
| reason             | string | Required | Enter the reason for selling the fixed asset                                                                                                          |

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/sell?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "expense_account_id": "3640355000000000421",
    "invoice_id": "3640355000000319008",
    "line_item_id": "3640355000000319008",
    "reason": "Asset is no longer required"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset has been sold"
}
```

---

## Add a comment
Add a comment to the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassets/{fixed_asset_id}/comments`

### Arguments
| Argument    | Type   | Required | Description                                                          |
| :---------- | :----- | :------- | :------------------------------------------------------------------- |
| description | string | Optional | It displays the description of the comment added for the fixed asset |

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "description": "Fixed asset is in good condition"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Comment has been added",
    "comment": {
        "comment_id": "3640355000000319013",
        "description": "string",
        "commented_by_id": "3640355000000075001",
        "commented_by": "Zoho Books",
        "comment_type": "system",
        "date": "2024-12-17",
        "date_description": "few seconds ago",
        "time": "11:34 AM",
        "operation_type": "Added"
    }
}
```

---

## Delete a comment
Delete the comment of the fixed asset.

`OAuth Scope : ZohoBooks.fixedasset.DELETE`

**Endpoint:**
`DELETE /fixedassets/{fixed_asset_id}/comments/{comment_id}`

### Path Parameters
| Parameter      | Type   | Required | Description                           |
| :------------- | :----- | :------- | :------------------------------------ |
| fixed_asset_id | string | Required | Unique identifier of the fixed asset. |
| comment_id     | string | Required | Unique identifier of the comment.     |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/fixedassets/3640355000000319008/comments/3640355000000319013?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Fixed asset comment has been deleted"
}
```

---

## Create a fixed asset type
Create a fixed asset type.

`OAuth Scope : ZohoBooks.fixedasset.CREATE`

**Endpoint:**
`POST /fixedassettypes`

### Arguments
| Argument                | Type   | Required | Description                                                                                                                                                                                                                               |
| :---------------------- | :----- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| fixed_asset_type_name   | string | Required | Enter the name of fixed asset type                                                                                                                                                                                                        |
| expense_account_id      | string | Required | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| depreciation_account_id | string | Required | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_method     | string | Required | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_frequency  | string | Required | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| depreciation_percentage | double | Required | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| total_life              | number | Required | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| salvage_value           | double | Required | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| computation_type        | string | Required | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/fixedassettypes?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "fixed_asset_type_name": "Machines",
    "expense_account_id": "3640355000000000421",
    "depreciation_account_id": "3640355000000000367",
    "depreciation_method": "declining_method",
    "depreciation_frequency": "yearly",
    "depreciation_percentage": 12,
    "total_life": 60,
    "salvage_value": 100,
    "computation_type": "prorata_basis"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The fixed asset type has been created.",
    "fixed_asset_type": {
        "fixed_asset_type_id": "3640355000000319008",
        "fixed_asset_type_name": "Machines",
        "expense_account_id": "3640355000000000421",
        "expense_account_name": "Telephone Expense",
        "depreciation_account_id": "3640355000000000367",
        "depreciation_account_name": "Furniture and Equipment",
        "depreciation_method": "declining_method",
        "depreciation_percentage": 12,
        "total_life": 60,
        "depreciation_frequency": "yearly",
        "computation_type": "prorata_basis"
    }
}
```

---

## Get fixed asset type list
fixed asset type list.

`OAuth Scope : ZohoBooks.fixedasset.READ`

**Endpoint:**
`GET /fixedassettypes`

### Query Parameters
| Parameter       | Type    | Required | Description                                                     |
| :-------------- | :------ | :------- | :-------------------------------------------------------------- |
| organization_id | string  | Required | ID of the organization                                          |
| page            | integer | Optional | Page number to be fetched. Default value is 1.                  |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200. |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/fixedassettypes?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "fixed_asset_types": [
        {
            "fixed_asset_type_id": "3640355000000319008",
            "fixed_asset_type_name": "Machines",
            "expense_account_id": "3640355000000000421",
            "expense_account_name": "Telephone Expense",
            "depreciation_account_id": "3640355000000000367",
            "depreciation_account_name": "Furniture and Equipment",
            "depreciation_method": "declining_method",
            "depreciation_percentage": 12,
            "total_life": 60,
            "depreciation_frequency": "yearly",
            "computation_type": "prorata_basis"
        },
        {...},
        {...}
    ]
}
```

---

## Update a fixed asset type
Updates the fixed asset type with given information.

`OAuth Scope : ZohoBooks.fixedasset.UPDATE`

**Endpoint:**
`PUT /fixedassettypes/{fixed_asset_type_id}`

### Arguments
| Argument                | Type   | Required | Description                                                                                                                                                                                                                               |
| :---------------------- | :----- | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| fixed_asset_type_name   | string | Required | Enter the name of fixed asset type                                                                                                                                                                                                        |
| expense_account_id      | string | Required | Enter the account id to track the expenses associated with the asset's depreciation.The available account types are **Expense** and **Other Expense**                                                                                     |
| depreciation_account_id | string | Required | Enter the account id to track the asset's depreciation over time.                                                                                                                                                                         |
| depreciation_method     | string | Required | Enter the depreciation method for your asset.The available methods are: `declining_method` and `straight_line`. <br>**For US and GLobal Edition:** `declining_method`, `straight_line`, `200_declining_method` and `150_declining_method` |
| depreciation_frequency  | string | Required | Enter the frequency of depreciation. The available frequencies are: `yearly` and `monthly`                                                                                                                                                |
| depreciation_percentage | double | Required | Enter the depreciation percentage only if the entered depreciation method is a declining method. The entered percentage should be within the range of 0 to 100                                                                            |
| total_life              | number | Required | Enter the total life of the asset (in months)                                                                                                                                                                                             |
| salvage_value           | double | Required | Enter the remaining amount of the asset after its useful life or the value after it's fully depreciated                                                                                                                                   |
| computation_type        | string | Required | Enter the computation types of assets. The available types are: `prorata_basis` and `no_prorata`                                                                                                                                          |

### Path Parameters
| Parameter           | Type   | Required | Description                                |
| :------------------ | :----- | :------- | :----------------------------------------- |
| fixed_asset_type_id | string | Required | Unique identifier of the fixed asset type. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/fixedassettypes/3640355000000319008?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "fixed_asset_type_name": "Machines",
    "expense_account_id": "3640355000000000421",
    "depreciation_account_id": "3640355000000000367",
    "depreciation_method": "declining_method",
    "depreciation_frequency": "yearly",
    "depreciation_percentage": 12,
    "total_life": 60,
    "salvage_value": 100,
    "computation_type": "prorata_basis"
}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The fixed asset type has been update.",
    "fixed_asset_type": {
        "fixed_asset_type_id": "3640355000000319008",
        "fixed_asset_type_name": "Machines",
        "expense_account_id": "3640355000000000421",
        "expense_account_name": "Telephone Expense",
        "depreciation_account_id": "3640355000000000367",
        "depreciation_account_name": "Furniture and Equipment",
        "depreciation_method": "declining_method",
        "depreciation_percentage": 12,
        "total_life": 60,
        "depreciation_frequency": "yearly",
        "computation_type": "prorata_basis"
    }
}
```

---

## Delete a fixed asset type
Deletes the given fixed asset type.

`OAuth Scope : ZohoBooks.fixedasset.DELETE`

**Endpoint:**
`DELETE /fixedassettypes/{fixed_asset_type_id}`

### Path Parameters
| Parameter           | Type   | Required | Description                                |
| :------------------ | :----- | :------- | :----------------------------------------- |
| fixed_asset_type_id | string | Required | Unique identifier of the fixed asset type. |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/fixedassettypes/3640355000000319008?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected fixed asset type has been deleted."
}
```