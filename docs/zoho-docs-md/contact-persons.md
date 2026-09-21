# Contact Persons

The list of contacts created.

### Attribute

| Attribute                    | Datatype | Description                                                                                                                                                   |
| :--------------------------- | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **contact_id**               | string   | Contact id of the contact                                                                                                                                     |
| **contact_person_id**        | string   | The id of the contact person                                                                                                                                  |
| **salutation**               | string   | Salutation for the contact. Max-length [25]                                                                                                                   |
| **first_name**               | string   | First name of the contact person. Max-length [100]                                                                                                            |
| **last_name**                | string   | Last name of the contact person. Max-length [100]                                                                                                             |
| **email**                    | string   | Email address of the contact person. Max-length [100]                                                                                                         |
| **phone**                    | string   | Max-length [50]                                                                                                                                               |
| **mobile**                   | string   | Max-length [50]                                                                                                                                               |
| **is_primary_contact**       | boolean  | To mark contact person as primary for contact                                                                                                                 |
| **skype**                    | string   | skype address. Max-length [50]                                                                                                                                |
| **designation**              | string   | designation of a person. Max-length [50]                                                                                                                      |
| **department**               | string   | department on which a person belongs. Max-length [50]                                                                                                         |
| **is_added_in_portal**       | boolean  | tells whether the contact person has portal access/not                                                                                                        |
| **communication_preference** | object   | Preferred modes of communication for the contact person.                                                                                                      |
| **is_sms_enabled**           | boolean  | *(Sub-attribute)* Used to check if SMS communication preference is enabled for the contact person. <br>*(Supported Editions: SMS integration only)*           |
| **is_whatsapp_enabled**      | boolean  | *(Sub-attribute)* Used to check if WhatsApp communication preference is enabled for the contact person. <br>*(Supported Editions: WhatsApp integration only)* |

```json
// Example
{
    "contact_id": 460000000026049,
    "contact_person_id": 460000000026051,
    "salutation": "Mr",
    "first_name": "Will",
    "last_name": "Smith",
    "email": "willsmith@bowmanfurniture.com",
    "phone": "+1-925-921-9201",
    "mobile": "+1-4054439562",
    "is_primary_contact": true,
    "skype": "zoho",
    "designation": "Sales Engineer",
    "department": "Sales",
    "is_added_in_portal": true,
    "communication_preference": {
        "is_sms_enabled": true,
        "is_whatsapp_enabled": true
    }
}
```

---

## Create a contact person

Create a contact person for contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/contactpersons`

### Arguments

| Parameter                    | Datatype | Description                                                                                                                                                  |
| :--------------------------- | :------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **contact_id**               | string   | Contact id of the contact                                                                                                                                    |
| **salutation**               | string   | Salutation for the contact. Max-length [25]                                                                                                                  |
| **first_name**               | string   | **(Required)** First name of the contact person. Max-length [100]                                                                                            |
| **last_name**                | string   | Last name of the contact person. Max-length [100]                                                                                                            |
| **email**                    | string   | Email address of the contact person. Max-length [100]                                                                                                        |
| **phone**                    | string   | Max-length [50]                                                                                                                                              |
| **mobile**                   | string   | Max-length [50]                                                                                                                                              |
| **skype**                    | string   | skype address. Max-length [50]                                                                                                                               |
| **designation**              | string   | designation of a person. Max-length [50]                                                                                                                     |
| **department**               | string   | department on which a person belongs. Max-length [50]                                                                                                        |
| **enable_portal**            | boolean  | option to enable the portal access. allowed values `true`, `false`                                                                                           |
| **communication_preference** | object   | Preferred modes of communication for the contact person.                                                                                                     |
| **is_sms_enabled**           | boolean  | *(Sub-argument)* Used to check if SMS communication preference is enabled for the contact person. <br>*(Supported Editions: SMS integration only)*           |
| **is_whatsapp_enabled**      | boolean  | *(Sub-argument)* Used to check if WhatsApp communication preference is enabled for the contact person. <br>*(Supported Editions: WhatsApp integration only)* |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

### Request Example

```json
{
    "contact_id": 460000000026049,
    "salutation": "Mr",
    "first_name": "Will",
    "last_name": "Smith",
    "email": "willsmith@bowmanfurniture.com",
    "phone": "+1-925-921-9201",
    "mobile": "+1-4054439562",
    "skype": "zoho",
    "designation": "Sales Engineer",
    "department": "Sales",
    "enable_portal": true,
    "communication_preference": {
        "is_sms_enabled": true,
        "is_whatsapp_enabled": true
    }
}
```

### Response Example (201 Created)

```json
{
    "code": 0,
    "message": "The contactperson has been Created",
    "contact_person": [
        {
            "contact_id": 460000000026049,
            "contact_person_id": 460000000026051,
            "salutation": "Mr",
            "first_name": "Will",
            "last_name": "Smith",
            "email": "willsmith@bowmanfurniture.com",
            "phone": "+1-925-921-9201",
            "mobile": "+1-4054439562",
            "is_primary_contact": true,
            "skype": "zoho",
            "designation": "Sales Engineer",
            "department": "Sales",
            "is_added_in_portal": true,
            "communication_preference": {
                "is_sms_enabled": true,
                "is_whatsapp_enabled": true
            }
        },
        ...
    ]
}
```

---

## Update a contact person

Update an existing contact person.

`OAuth Scope : ZohoBooks.contacts.UPDATE`

**Method:** `PUT`
**URL:** `/contacts/contactpersons/{contact_person_id}`

### Arguments

| Parameter                    | Datatype | Description                                                                                                                                                  |
| :--------------------------- | :------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **contact_id**               | string   | **(Required)** Contact id of the contact                                                                                                                     |
| **salutation**               | string   | Salutation for the contact. Max-length [25]                                                                                                                  |
| **first_name**               | string   | **(Required)** First name of the contact person. Max-length [100]                                                                                            |
| **last_name**                | string   | Last name of the contact person. Max-length [100]                                                                                                            |
| **email**                    | string   | Email address of the contact person. Max-length [100]                                                                                                        |
| **phone**                    | string   | Max-length [50]                                                                                                                                              |
| **mobile**                   | string   | Max-length [50]                                                                                                                                              |
| **skype**                    | string   | skype address. Max-length [50]                                                                                                                               |
| **designation**              | string   | designation of a person. Max-length [50]                                                                                                                     |
| **department**               | string   | department on which a person belongs. Max-length [50]                                                                                                        |
| **enable_portal**            | boolean  | option to enable the portal access. allowed values `true`, `false`                                                                                           |
| **is_primary_contact**       | boolean  | To mark contact person as primary for contact                                                                                                                |
| **communication_preference** | object   | Preferred modes of communication for the contact person.                                                                                                     |
| **is_sms_enabled**           | boolean  | *(Sub-argument)* Used to check if SMS communication preference is enabled for the contact person. <br>*(Supported Editions: SMS integration only)*           |
| **is_whatsapp_enabled**      | boolean  | *(Sub-argument)* Used to check if WhatsApp communication preference is enabled for the contact person. <br>*(Supported Editions: WhatsApp integration only)* |

### Path Parameters

| Parameter             | Datatype | Description                                             |
| :-------------------- | :------- | :------------------------------------------------------ |
| **contact_person_id** | string   | **(Required)** Unique identifier of the contact person. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

### Request Example

```json
{
    "contact_id": 460000000026049,
    "salutation": "Mr",
    "first_name": "Will",
    "last_name": "Smith",
    "email": "willsmith@bowmanfurniture.com",
    "phone": "+1-925-921-9201",
    "mobile": "+1-4054439562",
    "skype": "zoho",
    "designation": "Sales Engineer",
    "department": "Sales",
    "enable_portal": true,
    "is_primary_contact": true,
    "communication_preference": {
        "is_sms_enabled": true,
        "is_whatsapp_enabled": true
    }
}
```

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "The contactperson details has been updated.",
    "contact_person": [
        {
            "contact_id": 460000000026049,
            "contact_person_id": 460000000026051,
            "salutation": "Mr",
            "first_name": "Will",
            "last_name": "Smith",
            "email": "willsmith@bowmanfurniture.com",
            "phone": "+1-925-921-9201",
            "mobile": "+1-4054439562",
            "is_primary_contact": true,
            "skype": "zoho",
            "designation": "Sales Engineer",
            "department": "Sales",
            "is_added_in_portal": true,
            "communication_preference": {
                "is_sms_enabled": true,
                "is_whatsapp_enabled": true
            }
        },
        ...
    ]
}
```

---

## Delete a contact person

Delete an existing contact person.

`OAuth Scope : ZohoBooks.contacts.DELETE`

**Method:** `DELETE`
**URL:** `/contacts/contactpersons/{contact_person_id}`

### Path Parameters

| Parameter             | Datatype | Description                                             |
| :-------------------- | :------- | :------------------------------------------------------ |
| **contact_person_id** | string   | **(Required)** Unique identifier of the contact person. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "The contact person has been deleted."
}
```

---

## List contact persons

List all contacts with pagination.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/contactpersons`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                                                     |
| :------------------ | :------- | :-------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization                           |
| **page**            | integer  | Page number to be fetched. Default value is 1.                  |
| **per_page**        | integer  | Number of records to be fetched per page. Default value is 200. |

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "success",
    "contact_persons": [
        {
            "contact_person_id": 460000000026051,
            "salutation": "Mr",
            "first_name": "Will",
            "last_name": "Smith",
            "email": "willsmith@bowmanfurniture.com",
            "phone": "+1-925-921-9201",
            "mobile": "+1-4054439562",
            "is_primary_contact": true,
            "skype": "zoho",
            "designation": "Sales Engineer",
            "department": "Sales",
            "is_added_in_portal": true,
            "communication_preference": {
                "is_sms_enabled": true,
                "is_whatsapp_enabled": true
            }
        },
        ...
    ],
    "page_context": {
        "page": 1,
        "per_page": 200,
        "has_more_page": false,
        "sort_column": "contact_person_id",
        "sort_order": "A"
    }
}
```

---

## Get a contact person

Get the contact person details.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/contactpersons/{contact_person_id}`

### Path Parameters

| Parameter             | Datatype | Description                                             |
| :-------------------- | :------- | :------------------------------------------------------ |
| **contact_id**        | string   | **(Required)** Unique identifier of the contact.        |
| **contact_person_id** | string   | **(Required)** Unique identifier of the contact person. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "success",
    "contact_person": {
        "contact_id": 460000000026049,
        "contact_person_id": 460000000026051,
        "salutation": "Mr",
        "first_name": "Will",
        "last_name": "Smith",
        "email": "willsmith@bowmanfurniture.com",
        "phone": "+1-925-921-9201",
        "mobile": "+1-4054439562",
        "is_primary_contact": true,
        "skype": "zoho",
        "designation": "Sales Engineer",
        "department": "Sales",
        "is_added_in_portal": true,
        "communication_preference": {
            "is_sms_enabled": true,
            "is_whatsapp_enabled": true
        }
    }
}
```

---

## Mark as primary contact person

Mark a contact person as primary for the contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/contactpersons/{contact_person_id}/primary`

### Path Parameters

| Parameter             | Datatype | Description                                             |
| :-------------------- | :------- | :------------------------------------------------------ |
| **contact_person_id** | string   | **(Required)** Unique identifier of the contact person. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

### Response Example (200 OK)

```json
{
    "code": 0,
    "message": "This contact person has been marked as your primary contact person."
}
```