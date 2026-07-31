# Projects

A project is a series of tasks performed over a period of time, to achieve certain targets. There can be many number of people working on a single project and a project may consist of single or multiple tasks. A project is billed and charged upon a customer whom the project was taken up for.

### End Points

| Method | URL                                            | Description                                          |
| :----- | :--------------------------------------------- | :--------------------------------------------------- |
| POST   | `/projects`                                    | Create a project                                     |
| PUT    | `/projects`                                    | Update a project using a custom field's unique value |
| GET    | `/projects`                                    | List projects                                        |
| PUT    | `/projects/{project_id}`                       | Update project                                       |
| GET    | `/projects/{project_id}`                       | Get a project                                        |
| DELETE | `/projects/{project_id}`                       | Delete project                                       |
| POST   | `/projects/{project_id}/active`                | Activate project                                     |
| POST   | `/projects/{project_id}/inactive`              | Inactivate a project                                 |
| POST   | `/projects/{project_id}/clone`                 | Clone project                                        |
| POST   | `/projects/{project_id}/users`                 | Assign users                                         |
| GET    | `/projects/{project_id}/users`                 | List Users                                           |
| POST   | `/projects/{project_id}/users/invite`          | Invite user                                          |
| PUT    | `/projects/{project_id}/users/{user_id}`       | Update user                                          |
| GET    | `/projects/{project_id}/users/{user_id}`       | Get a Project User                                   |
| DELETE | `/projects/{project_id}/users/{user_id}`       | Delete user                                          |
| POST   | `/projects/{project_id}/comments`              | Post comment                                         |
| GET    | `/projects/{project_id}/comments`              | List comments                                        |
| DELETE | `/projects/{project_id}/comments/{comment_id}` | Delete comment                                       |
| GET    | `/projects/{project_id}/invoices`              | List invoices                                        |

---

## Attributes

### Project Attributes
| Attribute                | Type    | Description                                                                                                                                          |
| :----------------------- | :------ | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| project_id               | string  | ID of the project.                                                                                                                                   |
| project_name             | string  | Name of the project. `Max-length [100]`                                                                                                              |
| customer_id              | string  | Search projects by customer id.                                                                                                                      |
| customer_name            | string  | Name of the customer.                                                                                                                                |
| currency_code            | string  | Currency code associated with the project.                                                                                                           |
| description              | string  | Description of the project.                                                                                                                          |
| status                   | string  | Status of the project.                                                                                                                               |
| billing_type             | string  | The way you bill your customer. Allowed Values: `fixed_cost_for_project`, `based_on_project_hours`, `based_on_staff_hours` and `based_on_task_hours` |
| rate                     | float   | Project rate (if applicable).                                                                                                                        |
| budget_type              | string  | Type of budget used.                                                                                                                                 |
| total_hours              | string  | Total hours logged.                                                                                                                                  |
| total_amount             | double  | Total amount associated.                                                                                                                             |
| billed_hours             | string  | Hours already billed.                                                                                                                                |
| billed_amount            | double  | Amount already billed.                                                                                                                               |
| un_billed_hours          | string  | Hours not yet billed.                                                                                                                                |
| un_billed_amount         | double  | Amount not yet billed.                                                                                                                               |
| billable_hours           | string  | Hours marked as billable.                                                                                                                            |
| billable_amount          | double  | Amount marked as billable.                                                                                                                           |
| non_billable_hours       | string  | Hours marked as non-billable.                                                                                                                        |
| non_billable_amount      | double  | Amount marked as non-billable.                                                                                                                       |
| cost_budget_amount       | double  | Budgeted Cost to complete this project.                                                                                                              |
| is_recurrence_associated | boolean | If the project is associated with recurring invoices.                                                                                                |
| recurring_invoices       | array   | List of recurring invoices associated.                                                                                                               |
| created_time             | string  | Time of creation.                                                                                                                                    |
| show_in_dashboard        | boolean | Whether to show in the dashboard.                                                                                                                    |
| tasks                    | array   | List of tasks.                                                                                                                                       |
| users                    | array   | List of users.                                                                                                                                       |

### Task Attributes (Sub-attribute of tasks)
| Attribute          | Type    | Description                             |
| :----------------- | :------ | :-------------------------------------- |
| task_id            | string  | ID of the task.                         |
| task_name          | string  | Name of the task.                       |
| description        | string  | Description of the task.                |
| rate               | float   | Rate per hour for the task.             |
| budget_hours       | string  | Task budget hours.                      |
| total_hours        | string  | Total hours logged for this task.       |
| billed_hours       | string  | Billed hours for this task.             |
| un_billed_hours    | string  | Unbilled hours for this task.           |
| non_billable_hours | string  | Non-billable hours.                     |
| status             | string  | Status of the task.                     |
| is_billable        | boolean | If the task is billable.                |
| task_custom_fields | string  | Custom fields associated with the task. |

### User Attributes (Sub-attribute of users)
| Attribute       | Type    | Description                                                                |
| :-------------- | :------ | :------------------------------------------------------------------------- |
| user_id         | string  | ID of the user to be added to the project.                                 |
| is_current_user | boolean | If the user object is the current user.                                    |
| user_name       | string  | Name of the user. `Max-length [200]`                                       |
| email           | string  | Email of the user. `Max-length [100]`                                      |
| user_role       | string  | Role to be assigned. Allowed Values: `staff`, `admin` and `timesheetstaff` |
| status          | string  | Status of the user in the project.                                         |
| rate            | float   | Hourly rate for the user.                                                  |
| budget_hours    | string  | User budget hours.                                                         |
| total_hours     | string  | Total hours logged by user.                                                |
| billed_hours    | string  | Hours billed for user.                                                     |
| un_billed_hours | string  | Hours unbilled for user.                                                   |
| cost_rate       | double  | Cost rate for the user.                                                    |

---

## Create a project

Create a project.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Arguments

| Argument           | Type   | Required | Description                                                                                                                                          |
| :----------------- | :----- | :------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| project_name       | string | Required | Name of the project. `Max-length [100]`                                                                                                              |
| customer_id        | string | Required | ID of the customer.                                                                                                                                  |
| currency_id        | string | Optional | ID of the currency.                                                                                                                                  |
| description        | string | Optional | Project description. `Max-length [500]`                                                                                                              |
| billing_type       | string | Required | The way you bill your customer. Allowed Values: `fixed_cost_for_project`, `based_on_project_hours`, `based_on_staff_hours` and `based_on_task_hours` |
| rate               | string | Optional | Hourly rate for a task.                                                                                                                              |
| budget_type        | string | Optional | The way you budget. Allowed Values: `total_project_cost`, `total_project_hours`, `hours_per_task` and `hours_per_staff`                              |
| budget_hours       | string | Optional | Task budget hours                                                                                                                                    |
| budget_amount      | string | Optional | Give value, if you are estimating total project revenue budget.                                                                                      |
| cost_budget_amount | double | Optional | Budgeted Cost to complete this project                                                                                                               |
| user_id            | string | Required | ID of the user to be added to the project.                                                                                                           |
| tasks              | array  | Optional | List of tasks. See Task Attributes.                                                                                                                  |
| users              | array  | Optional | List of users. See User Attributes.                                                                                                                  |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"project_name":"Network Distribution","customer_id":"460000000044001","currency_id":"460000000098001","description":"Distribution for the system of intermediaries between the producer of goods and/or services and the final user","billing_type":"based_on_task_hours","rate":" ","budget_type":" ","budget_hours":" ","budget_amount":" ","cost_budget_amount":"1000.00","user_id":"INV-00003","tasks":[{"task_name":"INV-00003","description":"INV-00003","rate":"INV-00003","budget_hours":"INV-00003"}],"users":[{"user_id":"INV-00003","is_current_user":true,"user_name":"John David","email":"johndavid@zilliuminc.com","user_role":"admin","status":"active","rate":" ","budget_hours":" ","total_hours":"12:26","billed_hours":"12:27","un_billed_hours":"00:00","cost_rate":"10.00"}]}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The project has been created.",
    "project": {
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "currency_code": "USD",
        "description": "A simple algorithm is to be tested with vehicle detection application.",
        "status": "active",
        "billing_type": "fixed_cost_for_project",
        "rate": 5000,
        "budget_type": " ",
        "total_hours": "12:26",
        "total_amount": 500,
        "billed_hours": "12:27",
        "billed_amount": 500,
        "un_billed_hours": "00:00",
        "un_billed_amount": 0,
        "billable_hours": "12:26",
        "billable_amount": 500,
        "non_billable_hours": "0.00",
        "non_billable_amount": 0,
        "cost_budget_amount": "1000.00",
        "is_recurrence_associated": false,
        "recurring_invoices": [
            "string"
        ],
        "created_time": "2013-09-18T18:05:27+0530",
        "show_in_dashboard": true,
        "tasks": [
            {
                "task_id": "460000000044009",
                "task_name": "Distribution Analysis",
                "description": "A simple algorithm is to be tested with vehicle detection application.",
                "rate": 5000,
                "budget_hours": "0",
                "total_hours": "12:26",
                "billed_hours": "12:27",
                "un_billed_hours": "00:00",
                "non_billable_hours": "0.00",
                "status": "active",
                "is_billable": true,
                "task_custom_fields": ""
            }
        ],
        "users": [
            {
                "user_id": "460000000024003",
                "is_current_user": true,
                "user_name": "John David",
                "email": "johndavid@zilliuminc.com",
                "user_role": "admin",
                "status": "active",
                "rate": 5000,
                "budget_hours": "0",
                "total_hours": "12:26",
                "billed_hours": "12:27",
                "un_billed_hours": "00:00",
                "cost_rate": "10.00"
            }
        ]
    }
}
```

---

## Update a project using a custom field's unique value

A custom field will have unique values if it's configured to not accept duplicate values. Now, you can use that custom field's value to update a project by providing its API name in the X-Unique-Identifier-Key header and its value in the X-Unique-Identifier-Value header. Based on this value, the corresponding project will be retrieved and updated. Additionally, there is an optional X-Upsert header. If the X-Upsert header is true and the custom field's unique value is not found in any of the existing projects, a new project will be created if the necessary payload details are available.

`OAuth Scope : ZohoBooks.projects.UPDATE`

### Arguments

The arguments are the same as creating a project (e.g., `project_name`, `customer_id`, `billing_type` etc.).

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Headers

| Parameter                 | Type    | Required | Description                                                                                         |
| :------------------------ | :------ | :------- | :-------------------------------------------------------------------------------------------------- |
| X-Unique-Identifier-Key   | string  | Required | Unique CustomField Api Name                                                                         |
| X-Unique-Identifier-Value | string  | Required | Unique CustomField Value                                                                            |
| X-Upsert                  | boolean | Optional | If there is no record found with unique custom field value, will create new project if set to true. |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/projects?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'X-Unique-Identifier-Key: cf_unique_cf' \
  --header 'X-Unique-Identifier-Value: unique Value' \
  --header 'X-Upsert: true' \
  --header 'content-type: application/json' \
  --data '{"project_name":"Network Distribution","customer_id":"460000000044001","currency_id":"460000000098001","description":"Distribution for the system of intermediaries between the producer of goods and/or services and the final user","billing_type":"based_on_task_hours","rate":" ","budget_type":" ","budget_hours":" ","budget_amount":" ","cost_budget_amount":"1000.00","user_id":"INV-00003","tasks":[{"task_name":"INV-00003","description":"INV-00003","rate":"INV-00003","budget_hours":"INV-00003"}],"users":[{"user_id":"INV-00003","is_current_user":true,"user_name":"John David","email":"johndavid@zilliuminc.com","user_role":"admin","status":"active","rate":" ","budget_hours":" ","total_hours":"12:26","billed_hours":"12:27","un_billed_hours":"00:00","cost_rate":"10.00"}]}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The project information has been updated.",
    "project": {
        "project_id": "460000000044019",
        ...
    }
}
```

---

## List projects

List all projects with pagination.

`OAuth Scope : ZohoBooks.projects.READ`

### Query Parameters

| Parameter       | Type    | Required | Description                                                                                        |
| :-------------- | :------ | :------- | :------------------------------------------------------------------------------------------------- |
| organization_id | string  | Required | ID of the organization                                                                             |
| filter_by       | string  | Optional | Filter projects by any status. Allowed Values: `Status.All`, `Status.Active` and `Status.Inactive` |
| customer_id     | string  | Optional | Search projects by customer id.                                                                    |
| sort_column     | string  | Optional | Sort projects. Allowed Values: `project_name`, `customer_name`, `rate` and `created_time`          |
| page            | integer | Optional | Page number to be fetched. Default value is 1.                                                     |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                    |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "projects": [
        {
            "project_id": "460000000044019",
            "project_name": "REAL TIME TRAFFIC FLUX",
            "customer_id": "460000000044001",
            "customer_name": "SAF Instruments Inc",
            "description": "A simple algorithm is to be tested with vehicle detection application.",
            "status": "active",
            "billing_type": "fixed_cost_for_project",
            "rate": 5000,
            "created_time": "2013-09-18T18:05:27+0530",
            "has_attachment": false,
            "total_hours": "12:26",
            "billable_hours": "12:26"
        }
    ],
    "page_context": [
        {
            "page": 10,
            "per_page": 450,
            "report_name": "Projects",
            "has_more_page": false,
            "sort_order": "D",
            "sort_column": "created_time"
        }
    ]
}
```

---

## Update project

Update details of a project.

`OAuth Scope : ZohoBooks.projects.UPDATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

Arguments are similar to creating a project (e.g., `project_name`, `customer_id`, `billing_type`, `tasks`, `users`, etc.).

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"project_name":"Network Distribution","customer_id":"460000000044001","currency_id":"460000000098001","description":"Distribution for the system of intermediaries between the producer of goods and/or services and the final user","billing_type":"based_on_task_hours","rate":" ","budget_type":" ","budget_hours":" ","budget_amount":" ","cost_budget_amount":"1000.00","user_id":"INV-00003","tasks":[{"task_name":"INV-00003","description":"INV-00003","rate":"INV-00003","budget_hours":"INV-00003"}],"users":[{"user_id":"INV-00003","is_current_user":true,"user_name":"John David","email":"johndavid@zilliuminc.com","user_role":"admin","status":"active","rate":" ","budget_hours":" ","total_hours":"12:26","billed_hours":"12:27","un_billed_hours":"00:00","cost_rate":"10.00"}]}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The project information has been updated.",
    "project": {
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "currency_code": "USD",
        "description": "A simple algorithm is to be tested with vehicle detection application.",
        "status": "active",
        "billing_type": "fixed_cost_for_project",
        "rate": 5000,
        "budget_type": " ",
        "total_hours": "12:26",
        "total_amount": 500,
        "billed_hours": "12:27",
        "billed_amount": 500,
        "un_billed_hours": "00:00",
        "un_billed_amount": 0,
        "billable_hours": "12:26",
        "billable_amount": 500,
        "non_billable_hours": "0.00",
        "non_billable_amount": 0,
        "cost_budget_amount": "1000.00",
        "is_recurrence_associated": false,
        "recurring_invoices": [
            "string"
        ],
        "created_time": "2013-09-18T18:05:27+0530",
        "show_in_dashboard": true,
        "tasks": [ ... ],
        "users": [ ... ]
    }
}
```

---

## Get a project

Get the details of a project.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "project": {
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "currency_code": "USD",
        ...
        "tasks": [...],
        "users": [...]
    }
}
```

---

## Delete project

Deleting a existing project.

`OAuth Scope : ZohoBooks.projects.DELETE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The project has been deleted."
}
```

---

## Activate project

Mark project as active.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/active?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected Projects have been marked as active."
}
```

---

## Inactivate a project

Marking a project as inactive.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/inactive?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The selected projects have been marked as inactive."
}
```

---

## Clone project

Cloning a project.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

| Argument     | Type   | Required | Description                             |
| :----------- | :----- | :------- | :-------------------------------------- |
| project_name | string | Required | Name of the project. `Max-length [100]` |
| description  | string | Optional | Project description. `Max-length [500]` |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/clone?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"project_name":"Network Distribution","description":"Distribution for the system of intermediaries between the producer of goods and/or services and the final user"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Project has been cloned successfully.",
    "project": {
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        ...
    }
}
```

---

## Assign users

Assign users to a project.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

| Argument  | Type   | Required | Description                                          |
| :-------- | :----- | :------- | :--------------------------------------------------- |
| users     | array  | Optional | List of user objects. Must contain `user_id` inside. |
| cost_rate | double | Required | Cost rate for the user.                              |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"users":[{"user_id":"460000000024003"}],"cost_rate":"10.00"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Users added",
    "users": [
        {
            "user_id": "460000000024003",
            "is_current_user": true,
            "user_name": "John David",
            "email": "johndavid@zilliuminc.com",
            "user_role": "admin",
            "status": "active",
            "rate": 5000,
            "budget_hours": "0",
            "cost_rate": "10.00"
        }
    ]
}
```

---

## List Users

Get list of users associated with a project.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "users": [
        {
            "user_id": "460000000024003",
            "is_current_user": true,
            "user_name": "John David",
            "email": "johndavid@zilliuminc.com",
            "user_role": "admin",
            "status": "active",
            "rate": 5000,
            "budget_hours": "0",
            "cost_rate": "10.00"
        }
    ]
}
```

---

## Invite user

Invite an user to the project.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

| Argument     | Type   | Required | Description                                                                |
| :----------- | :----- | :------- | :------------------------------------------------------------------------- |
| user_name    | string | Required | Name of the user. `Max-length [200]`                                       |
| email        | string | Required | Email of the user. `Max-length [100]`                                      |
| user_role    | string | Optional | Role to be assigned. Allowed Values: `staff`, `admin` and `timesheetstaff` |
| rate         | string | Optional | Hourly rate for a task.                                                    |
| budget_hours | string | Optional | Task budget hours.                                                         |
| cost_rate    | double | Optional | Cost rate of the user.                                                     |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users/invite?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"user_name":"John David","email":"johndavid@zilliuminc.com","user_role":"admin","rate":" ","budget_hours":"0","cost_rate":"10.00"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The staff has been added.",
    "users": [
        {
            "user_id": "460000000024003",
            "user_name": "John David",
            "email": "johndavid@zilliuminc.com",
            "user_role": "admin",
            "is_current_user": true,
            "cost_rate": "10.00"
        }
    ]
}
```

---

## Update user

Update details of a user.

`OAuth Scope : ZohoBooks.projects.UPDATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |
| user_id    | string | Required | Unique identifier of the user.    |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

| Argument     | Type   | Required | Description                                                                |
| :----------- | :----- | :------- | :------------------------------------------------------------------------- |
| user_name    | string | Optional | Name of the user. `Max-length [200]`                                       |
| user_role    | string | Optional | Role to be assigned. Allowed Values: `staff`, `admin` and `timesheetstaff` |
| rate         | float  | Optional | Hourly rate.                                                               |
| budget_hours | string | Optional | Task budget hours.                                                         |
| cost_rate    | double | Optional | Cost rate.                                                                 |

### Request Example
```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users/460000000024003?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"user_name":"John David","user_role":"admin","rate":5000,"budget_hours":"0","cost_rate":"10.00"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "The staff information has been updated.",
    "users": [
        {
            "user_id": "460000000024003",
            "user_name": "John David",
            "email": "johndavid@zilliuminc.com",
            "user_role": "admin",
            "is_current_user": true,
            "cost_rate": "10.00",
            ...
        }
    ]
}
```

---

## Get a Project User

Get details of a user in project.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |
| user_id    | string | Required | Unique identifier of the user.    |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users/460000000024003?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "user": {
        "user_id": "460000000024003",
        "is_current_user": true,
        "user_name": "John David",
        "email": "johndavid@zilliuminc.com",
        "user_role": "admin",
        "cost_rate": "10.00"
    }
}
```

---

## Delete user

Remove user from a project.

`OAuth Scope : ZohoBooks.projects.DELETE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |
| user_id    | string | Required | Unique identifier of the user.    |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/users/460000000024003?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The staff has been removed"
}
```

---

## Post comment

Post comment to a project.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Arguments

| Argument    | Type   | Required | Description                             |
| :---------- | :----- | :------- | :-------------------------------------- |
| description | string | Required | Project description. `Max-length [500]` |

### Request Example
```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"description":"Billing based on task hours"}'
```

### Response Example
```json
{
    "code": 0,
    "message": "Comments added.",
    "comments": [
        {
            "project_id": "460000000044019",
            "comment_id": "460000000044027",
            "description": "A simple algorithm is to be tested with vehicle detection application.",
            "commented_by_id": "460000000024003",
            "commented_by": "John David",
            "date": "6:52 PM",
            "date_description": "19 days ago",
            "time": "6:52 PM"
        }
    ]
}
```

---

## List comments

Get comments for a project.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/comments?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "comments": [
        {
            "comment_id": "460000000044027",
            "project_id": "460000000044019",
            "description": "A simple algorithm is to be tested with vehicle detection application.",
            "commented_by_id": "460000000024003",
            "commented_by": "John David",
            "is_current_user": true,
            "date": "6:52 PM",
            "date_description": "19 days ago",
            "time": "6:52 PM"
        }
    ]
}
```

---

## Delete comment

Deleting a comment.

`OAuth Scope : ZohoBooks.projects.DELETE`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |
| comment_id | string | Required | Unique identifier of the comment. |

### Query Parameters

| Parameter       | Type   | Required | Description            |
| :-------------- | :----- | :------- | :--------------------- |
| organization_id | string | Required | ID of the organization |

### Request Example
```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/comments/460000000044027?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "The comment has been deleted."
}
```

---

## List invoices

Lists invoices created for this project.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter  | Type   | Required | Description                       |
| :--------- | :----- | :------- | :-------------------------------- |
| project_id | string | Required | Unique identifier of the project. |

### Query Parameters

| Parameter       | Type    | Required | Description                                                                                           |
| :-------------- | :------ | :------- | :---------------------------------------------------------------------------------------------------- |
| organization_id | string  | Required | ID of the organization                                                                                |
| sort_column     | string  | Optional | Sort invoices raised. Allowed Values: `invoice_number`, `date`, `total`, `balance` and `created_time` |
| page            | integer | Optional | Page number to be fetched. Default value is 1.                                                        |
| per_page        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                       |

### Request Example
```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/460000000044019/invoices?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example
```json
{
    "code": 0,
    "message": "success",
    "invoices": [
        {
            "invoice_id": "460000000044001",
            "customer_name": "SAF Instruments Inc",
            "status": "active",
            "invoice_number": "INV-00004",
            "reference_number": " ",
            "date": "6:52 PM",
            "due_date": "6:52 PM",
            "total": "310.75",
            "balance": "48.75",
            "created_time": "2013-09-18T18:05:27+0530"
        }
    ],
    "page_context": {
        "page": 10,
        "per_page": 450,
        "report_name": "Projects",
        "has_more_page": false,
        "sort_order": "D",
        "sort_column": "created_time"
    }
}
```