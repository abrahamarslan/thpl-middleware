# Custom Modules

In Zoho Books, you can create a custom module to record other data when the predefined modules are not sufficient to manage all your business requirements
(*Note* : cf_ attribute is placeholder of the created custom field)

## Attributes

| Attribute                    | Type   | Description                             |
| :--------------------------- | :----- | :-------------------------------------- |
| module_record_id             | long   | ID of the Custom Module Record          |
| module_api_name              | string | Module API Name                         |
| last_modified_time           | string | Last Modified time of the Sales Order   |
| last_modified_time_formatted | string | Formatted value of modified Time        |
| created_time                 | string | Creation Time of the Sales Order        |
| created_time_formatted       | string | Creation Time of the Sales Order        |
| created_by_id                | string | Formatted value of created time         |
| last_modified_by_id          | string | Last modified by User ID                |
| record_name                  | string | Name of the record                      |
| record_name_formatted        | string | Name of the Record Formatted            |
| cf_debt_amount               | number | Value of the custom Field               |
| cf_debt_amount_formatted     | string | The formatted value of the custom Field |

### Custom Module Record Example
```json
{
    "module_record_id": "460000000639129",
    "module_api_name": "cm_debtor",
    "last_modified_time": "2022-02-18T11:00:45+0530",
    "last_modified_time_formatted": "18/02/2022 11:00 AM",
    "created_time": "2022-02-18T11:00:45+0530",
    "created_time_formatted": "2022-02-18T11:00:45+0530",
    "created_by_id": "2022-02-18T11:00:45+0530",
    "last_modified_by_id": "2112155000000069001",
    "record_name": "Alice",
    "record_name_formatted": "Alice",
    "cf_debt_amount": 10000,
    "cf_debt_amount_formatted": "₹10,000.00"
}
```

---

## Create Custom Modules
To create a custom module, you can use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`POST /{module_name}`

### Arguments
| Argument       | Type   | Required | Description               |
| :------------- | :----- | :------- | :------------------------ |
| record_name    | string | Required | Name of the record        |
| cf_debt_amount | number | Optional | Value of the custom Field |

### Path Parameters
| Parameter   | Type   | Required | Description |
| :---------- | :----- | :------- | :---------- |
| module_name | string | Required | Module Name |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/debtor?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "debtor is created successfully",
    "module_record": [
        {
            "module_record_id": "460000000639129",
            "module_api_name": "cm_debtor",
            "last_modified_time": "2022-02-18T11:00:45+0530",
            "last_modified_time_formatted": "18/02/2022 11:00 AM",
            "created_time": "2022-02-18T11:00:45+0530",
            "created_time_formatted": "2022-02-18T11:00:45+0530",
            "created_by_id": "2022-02-18T11:00:45+0530",
            "last_modified_by_id": "2112155000000069001",
            "record_name": "Alice",
            "record_name_formatted": "Alice",
            "cf_debt_amount": 10000,
            "cf_debt_amount_formatted": "₹10,000.00"
        }
    ]
}
```

---

## Bulk Update Custom Module
To update existing custom module records in bulk, use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`PUT /{module_name}`

### Arguments
| Argument         | Type   | Required | Description               |
| :--------------- | :----- | :------- | :------------------------ |
| cf_debt_amount   | number | Optional | Value of the custom Field |
| module_record_id | string | Optional | Reeccord IDs              |
| record_name      | string | Required | Name of the record        |

### Path Parameters
| Parameter   | Type   | Required | Description |
| :---------- | :----- | :------- | :---------- |
| module_name | string | Required | Module Name |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/debtor?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Bulk update successfull",
    "module_record": [
        {
            "module_record_id": "460000000639129",
            "module_api_name": "cm_debtor",
            "last_modified_time": "2022-02-18T11:00:45+0530",
            "last_modified_time_formatted": "18/02/2022 11:00 AM",
            "created_time": "2022-02-18T11:00:45+0530",
            "created_time_formatted": "2022-02-18T11:00:45+0530",
            "created_by_id": "2022-02-18T11:00:45+0530",
            "last_modified_by_id": "2112155000000069001",
            "record_name": "Alice",
            "record_name_formatted": "Alice",
            "cf_debt_amount": 10000,
            "cf_debt_amount_formatted": "₹10,000.00",
            "code": 0,
            "message": "success"
        }
    ]
}
```

---

## Get Record List of a Custom Module
To get the list of records of a custom module, you can use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`GET /{module_name}`

### Path Parameters
| Parameter   | Type   | Required | Description |
| :---------- | :----- | :------- | :---------- |
| module_name | string | Required | Module Name |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/debtor?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "module_record": [
        {
            "module_record_id": "460000000639129",
            "module_api_name": "cm_debtor",
            "last_modified_time": "2022-02-18T11:00:45+0530",
            "last_modified_time_formatted": "18/02/2022 11:00 AM",
            "created_time": "2022-02-18T11:00:45+0530",
            "created_time_formatted": "2022-02-18T11:00:45+0530",
            "created_by_id": "2022-02-18T11:00:45+0530",
            "last_modified_by_id": "2112155000000069001",
            "record_name": "Alice",
            "record_name_formatted": "Alice",
            "cf_debt_amount": 10000,
            "cf_debt_amount_formatted": "₹10,000.00"
        }
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false,
        "applied_filter": "Status.All",
        "sort_column": "created_time",
        "sort_order": "D"
    }
}
```

---

## Delete Custom Modules
To delete a custom module, you can use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`DELETE /{module_name}`

### Path Parameters
| Parameter   | Type   | Required | Description |
| :---------- | :----- | :------- | :---------- |
| module_name | string | Required | Module Name |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/cm_debtor?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "Module record deleted"
}
```

---

## Update Custom Module
To update an existing custom module, use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`PUT /{module_name}/{module_id}`

### Arguments
| Argument       | Type   | Required | Description               |
| :------------- | :----- | :------- | :------------------------ |
| record_name    | string | Required | Name of the record        |
| cf_debt_amount | number | Optional | Value of the custom Field |

### Path Parameters
| Parameter   | Type    | Required | Description      |
| :---------- | :------ | :------- | :--------------- |
| module_name | string  | Required | Module Name      |
| module_id   | integer | Required | Custom Module ID |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/debtor/987000000654321?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"field1":"value1","field2":"value2"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "debtor is updated successfully.",
    "module_record": [
        {
            "module_record_id": "460000000639129",
            "module_api_name": "cm_debtor",
            "last_modified_time": "2022-02-18T11:00:45+0530",
            "last_modified_time_formatted": "18/02/2022 11:00 AM",
            "created_time": "2022-02-18T11:00:45+0530",
            "created_time_formatted": "2022-02-18T11:00:45+0530",
            "created_by_id": "2022-02-18T11:00:45+0530",
            "last_modified_by_id": "2112155000000069001",
            "record_name": "Alice",
            "record_name_formatted": "Alice",
            "cf_debt_amount": 10000,
            "cf_debt_amount_formatted": "₹10,000.00"
        }
    ]
}
```

---

## Get Individual Record Details
To get the details of an individual organisation, use the argument below.

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`GET /{module_name}/{module_id}`

### Path Parameters
| Parameter   | Type    | Required | Description      |
| :---------- | :------ | :------- | :--------------- |
| module_name | string  | Required | Module Name      |
| module_id   | integer | Required | Custom Module ID |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/debtor/987000000654321?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "module_record": {
        "module_plural_name": "debtors",
        "comments": [
            {
                "date": "2022-02-17",
                "commented_by": "Staff Bob",
                "operation_type": "Added",
                "comment_type": "system",
                "date_formatted": "17/02/2022 12:09 AM",
                "description": "Record added.",
                "time": "12:09 AM",
                "comment_id": "3000000003061",
                "commented_by_id": "3000000002565"
            }
        ],
        "module_api_name": "cm_debtor",
        "shared_type": "read_write",
        "can_submit": false,
        "approvers_list": "",
        "can_approve": false,
        "module_name": "debtor",
        "module_fields": [
            {
                "field_id": 1,
                "is_active": true,
                "is_mandatory": true,
                "label": "debtor Name",
                "api_name": "record_name",
                "data_type_formatted": "Text Box (Single Line)",
                "value_formatted": "Alice",
                "data_type": "string",
                "pii_type": "non_pii",
                "value": "Alice",
                "max_length": 255,
                "help_text": ""
            }
        ],
        "module_record_id": 3000000003057,
        "shared_to": [
            460000000639128,
            460000000639129
        ]
    },
    "module_record_hash": {
        "module_record_id": "2022-02-17",
        "module_api_name": "cm_debtor",
        "last_modified_time": "2022-02-18T11:00:45+0530",
        "last_modified_time_formatted": "18/02/2022 11:00 AM",
        "created_time": "2022-02-18T11:00:45+0530",
        "created_time_formatted": "2022-02-18T11:00:45+0530",
        "created_by_id": "2112155000000069001",
        "last_modified_by_id": "2112155000000069001",
        "record_name": "Alice",
        "record_name_formatted": "Alice"
    },
    "users": [
        {
            "id": 2112155000000069000,
            "text": "Staff Bob",
            "name": "Staff Bob",
            "email": "string",
            "photo_url": "string",
            "is_current_user": true
        }
    ]
}
```

---

## Delete individual records
to delete individual records of a custom module, use the argument below

`OAuth Scope : ZohoBooks.custommodules.ALL`

**Endpoint:**
`DELETE /{module_name}/{module_id}`

### Path Parameters
| Parameter   | Type    | Required | Description      |
| :---------- | :------ | :------- | :--------------- |
| module_name | string  | Required | Module Name      |
| module_id   | integer | Required | Custom Module ID |

### Query Parameters
| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
#### cURL
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/cm_debtor/2112155000000652000?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success"
}
```