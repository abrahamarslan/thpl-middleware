Here is the documentation for the **Users** module converted to Markdown format.

# Users

Users are various individuals/entities that are a part of an organisation. Each user will have a different role to play, like admin, staff etc.

### End Points

| Method     | URL                         | Description           |
| :--------- | :-------------------------- | :-------------------- |
| **POST**   | `/users`                    | Create a user         |
| **GET**    | `/users`                    | List Users            |
| **PUT**    | `/users/{user_id}`          | Update a user         |
| **GET**    | `/users/{user_id}`          | Get an user details   |
| **DELETE** | `/users/{user_id}`          | Delete a user         |
| **GET**    | `/users/me`                 | Get current user      |
| **POST**   | `/users/{user_id}/invite`   | Invite a user         |
| **POST**   | `/users/{user_id}/active`   | Mark user as active   |
| **POST**   | `/users/{user_id}/inactive` | Mark user as inactive |

---

## Attributes

| Attribute         | Type    | Description                                                         |
| :---------------- | :------ | :------------------------------------------------------------------ |
| `user_id`         | string  | Unique identifier of the user.                                      |
| `name`            | string  | Name of the user.                                                   |
| `email`           | string  | Email address of the user.                                          |
| `user_role`       | string  | Role assigned to the user (e.g., admin, staff).                     |
| `role_id`         | string  | Unique identifier of the role.                                      |
| `status`          | string  | Status of the user (e.g., active, inactive, invited).               |
| `is_current_user` | boolean | Indicates if the user object represents the current logged-in user. |
| `photo_url`       | string  | URL to the user's photo.                                            |
| `cost_rate`       | double  | Hourly cost rate for the user.                                      |
| `user_type`       | string  | Type of user (e.g., zoho).                                          |
| `created_time`    | string  | Timestamp when the user was created.                                |

---

## Create a user

Create a user for your organization.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Arguments

| Argument    | Type   | Required | Description                          |
| :---------- | :----- | :------- | :----------------------------------- |
| `name`      | string | Required | Name of the user.                    |
| `email`     | string | Required | Email address of the user.           |
| `role_id`   | string | Optional | ID of the role assigned to the user. |
| `cost_rate` | double | Optional | Hourly cost rate.                    |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/users?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"name":"Sujin Kumar","email":"johndavid@zilliuminc.com","role_id":"982000000006005","cost_rate":0}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Your invitation has been sent."
}
```

---

## List Users

Get the list of all users in the organization.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type    | Required | Description                                                                                                                          |
| :---------------- | :------ | :------- | :----------------------------------------------------------------------------------------------------------------------------------- |
| `organization_id` | string  | Required | ID of the organization.                                                                                                              |
| `filter_by`       | string  | Optional | Filter users by status. <br>Allowed Values: `Status.All`, `Status.Active`, `Status.Inactive`, `Status.Invited` and `Status.Deleted`. |
| `sort_column`     | string  | Optional | Sort users. <br>Allowed Values: `name`, `email`, `user_role` and `status`.                                                           |
| `page`            | integer | Optional | Page number to be fetched. Default value is 1.                                                                                       |
| `per_page`        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                      |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/users?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "users": [
        {
            "user_id": "982000000554041",
            "role_id": "982000000006005",
            "name": "Sujin Kumar",
            "email": "johndavid@zilliuminc.com",
            "user_role": "admin",
            "status": "active",
            "is_current_user": true,
            "photo_url": "https://contacts.zoho.com/file?ID=d27344a22bad8bb83a03722b4aa5bc6967c3135f24307fe40db8572782432fd6aae0110f8bb9c4c79e8e0f0cca5904aecfacbf079f13b48c295bacc89ae91fca&fs=thumb",
            "is_customer_segmented": false,
            "is_vendor_segmented": false,
            "user_type": "zoho"
        },
        {...},
        {...}
    ],
    "page_context": {
        "page": 1,
        "per_page": 10,
        "has_more_page": false,
        "report_name": "Users",
        "sort_column": "name",
        "sort_order": "A"
    }
}
```

---

## Update a user

Update the details of a user.

`OAuth Scope : ZohoBooks.settings.UPDATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Arguments

| Argument    | Type   | Required | Description                          |
| :---------- | :----- | :------- | :----------------------------------- |
| `name`      | string | Required | Name of the user.                    |
| `email`     | string | Required | Email address of the user.           |
| `role_id`   | string | Optional | ID of the role assigned to the user. |
| `cost_rate` | double | Optional | Hourly cost rate.                    |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"name":"Sujin Kumar","email":"johndavid@zilliuminc.com","role_id":"982000000006005","cost_rate":0}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The user information has been updated."
}
```

---

## Get an user details

Get the details of a user.

`OAuth Scope : ZohoBooks.settings.READ`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "user": {
        "user_id": "982000000554041",
        "name": "Sujin Kumar",
        "email_ids": [
            {
                "email": "johndavid@zilliuminc.com",
                "is_selected": true
            }
        ],
        "status": "active",
        "user_role": "admin",
        "user_type": "zoho",
        "role_id": "982000000006005",
        "cost_rate": 0,
        "photo_url": "https://contacts.zoho.com/file?ID=d27344a22bad8bb83a03722b4aa5bc6967c3135f24307fe40db8572782432fd6aae0110f8bb9c4c79e8e0f0cca5904aecfacbf079f13b48c295bacc89ae91fca&fs=thumb",
        "is_employee": true,
        "created_time": "2016-06-05T02:30:08-0700",
        "custom_fields": ""
    }
}
```

---

## Delete a user

Delete a user associated to the organization.

`OAuth Scope : ZohoBooks.settings.DELETE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The user has been removed from your organization."
}
```

---

## Get current user

Get the details of the current user.

`OAuth Scope : ZohoBooks.settings.READ`

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/users/me?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "user": {
        "user_id": "982000000554041",
        "name": "Sujin Kumar",
        "email_ids": [
            {
                "email": "johndavid@zilliuminc.com",
                "is_selected": true
            }
        ],
        "status": "active",
        "user_role": "admin",
        "user_type": "zoho",
        "role_id": "982000000006005",
        "cost_rate": 0,
        "photo_url": "https://contacts.zoho.com/file?ID=d27344a22bad8bb83a03722b4aa5bc6967c3135f24307fe40db8572782432fd6aae0110f8bb9c4c79e8e0f0cca5904aecfacbf079f13b48c295bacc89ae91fca&fs=thumb",
        "is_employee": true,
        "created_time": "2016-06-05T02:30:08-0700",
        "custom_fields": ""
    }
}
```

---

## Invite a user

Send invitation email to a user.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041/invite?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "Your invitation has been sent."
}
```

---

## Mark user as active

Mark an inactive user as active.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The user has been marked as active."
}
```

---

## Mark user as inactive

Mark an active user as inactive.

`OAuth Scope : ZohoBooks.settings.CREATE`

### Path Parameters

| Parameter | Type   | Required | Description                    |
| :-------- | :----- | :------- | :----------------------------- |
| `user_id` | string | Required | Unique identifier of the user. |

### Query Parameters

| Parameter         | Type   | Required | Description             |
| :---------------- | :----- | :------- | :---------------------- |
| `organization_id` | string | Required | ID of the organization. |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/users/982000000554041/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The user has been marked as inactive."
}
```