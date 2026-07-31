Here is the markdown documentation for **Locations** module based on the provided HTML.

# Locations

Create locations for each branch and warehouse in your organisation and manage them all in one place.

### End Points

| Method     | URL                                      | Description        |
| :--------- | :--------------------------------------- | :----------------- |
| **POST**   | `/settings/locations/enable`             | Enable Locations   |
| **POST**   | `/locations`                             | Create a location  |
| **GET**    | `/locations`                             | List all locations |
| **PUT**    | `/locations/{location_id}`               | Update location    |
| **DELETE** | `/locations/{location_id}`               | Delete a location  |
| **POST**   | `/locations/{location_id}/active`        | Mark as Active     |
| **POST**   | `/locations/{location_id}/inactive`      | Mark as Inactive   |
| **POST**   | `/locations/{location_id}/markasprimary` | Mark as Primary    |

---

## Attributes

| Attribute                   | Type    | Description                                                    |
| :-------------------------- | :------ | :------------------------------------------------------------- |
| `location_id`               | string  | Location ID                                                    |
| `location_name`             | string  | Name of the location                                           |
| `type`                      | string  | Type of the location                                           |
| `email`                     | string  | Email id for the location                                      |
| `phone`                     | string  | Mobile number for location                                     |
| `status`                    | string  | Status of the locations. Allowed Values: `active`, `inactive`  |
| `is_primary`                | boolean | Whether it is primary location or not                          |
| `address`                   | object  | Address of the location. See sub-attributes below.             |
| `parent_location_id`        | string  | Parent Location ID                                             |
| `associated_series_ids`     | array   | IDs of transaction series associated with this location.       |
| `auto_number_generation_id` | string  | Autonumber generation group ID                                 |
| `associated_users`          | array   | Users associated with this location. See sub-attributes below. |
| `tax_settings_id`           | string  | Tax Settings ID (India only)                                   |

**Sub-Attributes for `address`**

| Attribute         | Type   | Description                   |
| :---------------- | :----- | :---------------------------- |
| `city`            | string | City Name of the location.    |
| `state`           | string | State Name of the location.   |
| `country`         | string | Country Name of the location. |
| `attention`       | string | Attention of the location.    |
| `state_code`      | string | State code of the location.   |
| `street_address1` | string | Street Name of the location.  |
| `street_address2` | string | Street Name of the location.  |

**Sub-Attributes for `associated_users`**

| Attribute   | Type   | Description |
| :---------- | :----- | :---------- |
| `user_id`   | string | User ID     |
| `user_name` | string | User Name   |

### Example

```json
{
    "address": {
        "city": "New York City",
        "state": "New York",
        "country": "U.S.A",
        "attention": "string",
        "state_code": "NY",
        "street_address1": "No:234,90 Church Street",
        "street_address2": "McMillan Avenue"
    },
    "email": "willsmith@bowmanfurniture.com",
    "is_primary": true,
    "phone": "+1-925-921-9201",
    "status": "active",
    "location_id": "460000000038080",
    "location_name": "Head Office",
    "type": "general / line_item_only",
    "parent_location_id": "460000000041010",
    "associated_series_ids": [
        "982000000870911",
        "982000000870915"
    ],
    "auto_number_generation_id": "982000000870911",
    "associated_users": [
        {
            "user_id": "460000000036868",
            "user_name": "John Doe"
        }
    ],
    "tax_settings_id": "460000000038080"
}
```

---

## Enable Locations

Enable Locations for an organisation.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/settings/locations/enable?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "We're enabling locations for your organization."
}
```

---

## Create a location

Create a location.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Argument                    | Type    | Required | Description                                                             |
| :-------------------------- | :------ | :------- | :---------------------------------------------------------------------- |
| `location_name`             | string  | Required | Name of the location                                                    |
| `tax_settings_id`           | string  | Required | Tax Settings ID (India Only)                                            |
| `address`                   | object  | Required | Address object containing `country`. Other address fields are optional. |
| `type`                      | string  | Optional | Type of the location                                                    |
| `email`                     | string  | Optional | Email id for the location                                               |
| `phone`                     | string  | Optional | Mobile number for location                                              |
| `parent_location_id`        | string  | Optional | Parent Location ID                                                      |
| `associated_series_ids`     | array   | Optional | Array of transaction series IDs                                         |
| `auto_number_generation_id` | string  | Optional | Autonumber generation group ID                                          |
| `is_all_users_selected`     | boolean | Optional | Whether all users are selected or not                                   |
| `user_ids`                  | string  | Optional | Comma separated user ids.                                               |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/locations?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "type": "general / line_item_only",
    "email": "willsmith@bowmanfurniture.com",
    "phone": "+1-925-921-9201",
    "address": {
        "city": "New York City",
        "state": "New York",
        "country": "U.S.A",
        "attention": "string",
        "state_code": "NY",
        "street_address1": "No:234,90 Church Street",
        "street_address2": "McMillan Avenue"
    },
    "location_name": "Head Office",
    "tax_settings_id": "460000000038080",
    "parent_location_id": "460000000041010",
    "associated_series_ids": [
        "982000000870911",
        "982000000870915"
    ],
    "auto_number_generation_id": "982000000870911",
    "is_all_users_selected": false,
    "user_ids": "460000000036868,460000000036869"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Location has been created.",
    "locations": {
        "address": {
            "city": "New York City",
            "state": "New York",
            "country": "U.S.A",
            "attention": "string",
            "state_code": "NY",
            "street_address1": "No:234,90 Church Street",
            "street_address2": "McMillan Avenue"
        },
        "email": "willsmith@bowmanfurniture.com",
        "is_primary": true,
        "phone": "+1-925-921-9201",
        "status": "active",
        "location_id": "460000000038080",
        "location_name": "Head Office",
        "type": "general / line_item_only",
        "parent_location_id": "460000000041010",
        "associated_series_ids": [
            "982000000870911",
            "982000000870915"
        ],
        "auto_number_generation_id": "982000000870911",
        "associated_users": [
            {
                "user_id": "460000000036868",
                "user_name": "John Doe"
            }
        ],
        "tax_settings_id": "460000000038080"
    }
}
```

---

## List all locations

List all the available locations in your zoho inventory.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/locations?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "locations": [
        {
            "type": "general / line_item_only",
            "email": "willsmith@bowmanfurniture.com",
            "phone": "+1-925-921-9201",
            "address": {
                "city": "New York City",
                "state": "New York",
                "country": "U.S.A",
                "attention": "string",
                "state_code": "NY",
                "street_address1": "No:234,90 Church Street",
                "street_address2": "McMillan Avenue"
            },
            "location_id": "460000000038080",
            "location_name": "Head Office",
            "tax_settings_id": "460000000038080",
            "parent_location_id": "460000000041010",
            "associated_series_ids": [
                "982000000870911",
                "982000000870915"
            ],
            "auto_number_generation_id": "982000000870911",
            "is_all_users_selected": false,
            "associated_users": [
                {
                    "user_id": "460000000036868",
                    "user_name": "John Doe"
                }
            ]
        }
    ]
}
```

---

## Update location

Update location

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `location_id` | string | Required | Unique identifier of the location. |

### Arguments

| Argument                    | Type    | Required | Description                                                             |
| :-------------------------- | :------ | :------- | :---------------------------------------------------------------------- |
| `location_name`             | string  | Required | Name of the location                                                    |
| `tax_settings_id`           | string  | Required | Tax Settings ID (India Only)                                            |
| `address`                   | object  | Required | Address object containing `country`. Other address fields are optional. |
| `type`                      | string  | Optional | Type of the location                                                    |
| `email`                     | string  | Optional | Email id for the location                                               |
| `phone`                     | string  | Optional | Mobile number for location                                              |
| `parent_location_id`        | string  | Optional | Parent Location ID                                                      |
| `associated_series_ids`     | array   | Optional | Array of transaction series IDs                                         |
| `auto_number_generation_id` | string  | Optional | Autonumber generation group ID                                          |
| `is_all_users_selected`     | boolean | Optional | Whether all users are selected or not                                   |
| `user_ids`                  | string  | Optional | Comma separated user ids.                                               |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/locations/130426000000664020?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{
    "type": "general / line_item_only",
    "email": "willsmith@bowmanfurniture.com",
    "phone": "+1-925-921-9201",
    "address": {
        "city": "New York City",
        "state": "New York",
        "country": "U.S.A",
        "attention": "string",
        "state_code": "NY",
        "street_address1": "No:234,90 Church Street",
        "street_address2": "McMillan Avenue"
    },
    "location_name": "Head Office",
    "tax_settings_id": "460000000038080",
    "parent_location_id": "460000000041010",
    "associated_series_ids": [
        "982000000870911",
        "982000000870915"
    ],
    "auto_number_generation_id": "982000000870911",
    "is_all_users_selected": false,
    "user_ids": "460000000036868,460000000036869"
}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Location has been updated.",
    "locations": {
        "address": {
            "city": "New York City",
            "state": "New York",
            "country": "U.S.A",
            "attention": "string",
            "state_code": "NY",
            "street_address1": "No:234,90 Church Street",
            "street_address2": "McMillan Avenue"
        },
        "email": "willsmith@bowmanfurniture.com",
        "is_primary": true,
        "phone": "+1-925-921-9201",
        "status": "active",
        "location_id": "460000000038080",
        "location_name": "Head Office",
        "type": "general / line_item_only",
        "parent_location_id": "460000000041010",
        "associated_series_ids": [
            "982000000870911",
            "982000000870915"
        ],
        "auto_number_generation_id": "982000000870911",
        "associated_users": [
            {
                "user_id": "460000000036868",
                "user_name": "John Doe"
            }
        ],
        "tax_settings_id": "460000000038080"
    }
}
```

---

## Delete a location

Delete a location.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `location_id` | string | Required | Unique identifier of the location. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/locations/130426000000664020?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The location has been deleted.."
}
```

---

## Mark as Active

Mark location as Active.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `location_id` | string | Required | Unique identifier of the location. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/locations/130426000000664020/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The location has been marked as active."
}
```

---

## Mark as Inactive

Mark location as Inactive.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `location_id` | string | Required | Unique identifier of the location. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/locations/130426000000664020/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The location has been marked as inactive."
}
```

---

## Mark as Primary

Mark location as primary.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter     | Type   | Required | Description                        |
| :------------ | :----- | :------- | :--------------------------------- |
| `location_id` | string | Required | Unique identifier of the location. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/locations/130426000000664020/markasprimary?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The location has been marked as primary."
}
```