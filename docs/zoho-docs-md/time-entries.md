Here is the **Time Entries** documentation converted to Markdown format.

# Time Entries

Time entries are various entries of time made by users in a project, based on the time they spent on a project, in a task.

### End Points

| Method     | URL                                                 | Description         |
| :--------- | :-------------------------------------------------- | :------------------ |
| **POST**   | `/projects/timeentries`                             | Log time entries    |
| **GET**    | `/projects/timeentries`                             | List time entries   |
| **DELETE** | `/projects/timeentries`                             | Delete time entries |
| **PUT**    | `/projects/timeentries/{time_entry_id}`             | Update time entry   |
| **GET**    | `/projects/timeentries/{time_entry_id}`             | Get a time entry    |
| **DELETE** | `/projects/timeentries/{time_entry_id}`             | Delete time entry   |
| **POST**   | `/projects/timeentries/{time_entry_id}/timer/start` | Start timer         |
| **POST**   | `/projects/timeentries/timer/stop`                  | Stop timer          |
| **GET**    | `/projects/timeentries/runningtimer/me`             | Get timer           |

---

## Attributes

| Attribute                   | Type    | Description                                                     |
| :-------------------------- | :------ | :-------------------------------------------------------------- |
| `time_entry_id`             | string  | Unique identifier of the time entry.                            |
| `project_id`                | string  | Search time entries by project_id.                              |
| `project_name`              | string  | Name of the project.                                            |
| `customer_id`               | string  | Search projects by customer id.                                 |
| `customer_name`             | string  | Name of the customer.                                           |
| `task_id`                   | string  | ID of the task.                                                 |
| `task_name`                 | string  | Name of the task.                                               |
| `user_id`                   | string  | Search time entries by user_id.                                 |
| `user_name`                 | string  | Name of the user.                                               |
| `is_current_user`           | boolean | Boolean to check if the user is the current user.               |
| `log_date`                  | string  | Date on which the user spent on the task. `Date-Format [HH:mm]` |
| `begin_time`                | string  | Start time of the entry.                                        |
| `end_time`                  | string  | End time of the entry.                                          |
| `log_time`                  | string  | Total time logged.                                              |
| `is_billable`               | boolean | Whether the time entry is billable.                             |
| `billed_status`             | string  | Status of billing (e.g., unbilled).                             |
| `invoice_id`                | string  | ID of the associated invoice.                                   |
| `notes`                     | string  | Notes associated with the time entry.                           |
| `timer_started_at`          | string  | Time when the timer started.                                    |
| `timer_started_at_utc_time` | string  | Time when the timer started in UTC.                             |
| `timer_duration_in_minutes` | string  | Duration of the timer in minutes.                               |
| `timer_duration_in_seconds` | string  | Duration of the timer in seconds.                               |
| `created_time`              | string  | Time when the entry was created.                                |
| `timesheet_custom_fields`   | string  | Custom fields associated with the timesheet.                    |

### Example

```json
{
    "time_entry_id": "460000000044021",
    "project_id": "460000000044019",
    "project_name": "REAL TIME TRAFFIC FLUX",
    "customer_id": "460000000044001",
    "customer_name": "SAF Instruments Inc",
    "task_id": "460000000044009",
    "task_name": "Distribution Analysis",
    "user_id": "460000000024003",
    "user_name": "John David",
    "is_current_user": true,
    "log_date": "2013-09-17",
    "begin_time": "03:00",
    "end_time": "04:00",
    "log_time": "05:00",
    "is_billable": true,
    "billed_status": "unbilled",
    "invoice_id": "",
    "notes": " ",
    "timer_started_at": " ",
    "timer_started_at_utc_time": "",
    "timer_duration_in_minutes": " ",
    "timer_duration_in_seconds": "",
    "created_time": "2013-09-18T18:05:27+0530",
    "timesheet_custom_fields": ""
}
```

---

## Log time entries

Logging time entries.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Arguments

| Argument      | Type    | Required | Description                                                                                                          |
| :------------ | :------ | :------- | :------------------------------------------------------------------------------------------------------------------- |
| `project_id`  | string  | Required | ID of the project.                                                                                                   |
| `task_id`     | string  | Required | ID of the task.                                                                                                      |
| `user_id`     | string  | Required | ID of the user.                                                                                                      |
| `log_date`    | string  | Required | Date on which the user spent on the task. `Date-Format [HH:mm]`                                                      |
| `log_time`    | string  | Optional | Time the user spent on this task. Either send this attribute or begin and end time attributes. `Time-Format [HH:mm]` |
| `begin_time`  | string  | Optional | Time the user started working on this task. `Time-Format [HH:mm]`                                                    |
| `end_time`    | string  | Optional | Time the user stopped working on this task. `Time-Format [HH:mm]`                                                    |
| `is_billable` | boolean | Optional | Whether it is billable or not.                                                                                       |
| `notes`       | string  | Optional | Description of the work done. `Max-length [500]`                                                                     |
| `start_timer` | string  | Optional | Start timer.                                                                                                         |
| `cost_rate`   | double  | Optional | Hourly cost rate                                                                                                     |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"project_id":"Network Distribution","task_id":"460000000044001","user_id":"460000000024003","log_date":"2013-09-17","log_time":" ","begin_time":"10:00","end_time":"15:00","is_billable":true,"notes":" ","start_timer":" ","cost_rate":10}'
```

### Response Example

```json
{
    "code": 0,
    "message": "Your timesheet entry has been added.",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": ""
    }
}
```

---

## List time entries

List all time entries with pagination.

`OAuth Scope : ZohoBooks.projects.READ`

### Query Parameters

| Parameter         | Type    | Required | Description                                                                                                                                                                                                                                                                                                                      |
| :---------------- | :------ | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `organization_id` | string  | Required | ID of the organization                                                                                                                                                                                                                                                                                                           |
| `from_date`       | string  | Optional | Date from which the time entries logged to be fetched                                                                                                                                                                                                                                                                            |
| `to_date`         | string  | Optional | Date up to which the time entries logged to be fetched                                                                                                                                                                                                                                                                           |
| `filter_by`       | string  | Optional | Filter time entries by date and status. Allowed Values: `Date.All`, `Date.Today`, `Date.ThisWeek`, `Date.ThisMonth`, `Date.ThisQuarter`, `Date.ThisYear`, `Date.PreviousDay`, `Date.PreviousWeek`, `Date.PreviousMonth`, `Date.PreviousQuarter`, `Date.PreviousYear`, `Date.CustomDate`, `Status.Unbilled` and `Status.Invoiced` |
| `project_id`      | string  | Optional | Search time entries by project_id.                                                                                                                                                                                                                                                                                               |
| `user_id`         | string  | Optional | Search time entries by user_id.                                                                                                                                                                                                                                                                                                  |
| `sort_column`     | string  | Optional | Sort time entries. Allowed Values: `project_name`, `task_name`, `user_name`, `log_date`, `timer_started_at` and `customer_name`                                                                                                                                                                                                  |
| `page`            | integer | Optional | Page number to be fetched. Default value is 1.                                                                                                                                                                                                                                                                                   |
| `per_page`        | integer | Optional | Number of records to be fetched per page. Default value is 200.                                                                                                                                                                                                                                                                  |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "time_entries": [
        {
            "time_entry_id": "460000000044021",
            "project_id": "460000000044019",
            "project_name": "REAL TIME TRAFFIC FLUX",
            "customer_id": "460000000044001",
            "customer_name": "SAF Instruments Inc",
            "task_id": "460000000044009",
            "task_name": "Distribution Analysis",
            "user_id": "460000000024003",
            "user_name": "John David",
            "is_current_user": true,
            "log_date": "2013-09-17",
            "begin_time": "03:00",
            "end_time": "04:00",
            "log_time": "05:00",
            "is_billable": true,
            "billed_status": "unbilled",
            "invoice_id": "",
            "notes": " ",
            "timer_started_at": " ",
            "timer_duration_in_minutes": " ",
            "created_time": "2013-09-18T18:05:27+0530",
            "cost_rate": 0,
            "cost_amount": 0
        },
        {...},
        {...}
    ],
    "page_context": [
        {
            "page": 10,
            "per_page": 450,
            "report_name": "Projects",
            "has_more_page": false,
            "sort_order": "D",
            "sort_column": "customer_name"
        }
    ]
}
```

---

## Delete time entries

Deleting time entries.

`OAuth Scope : ZohoBooks.projects.DELETE`

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The selected timesheet entries have been deleted"
}
```

---

## Update time entry

Update logged time entry.

`OAuth Scope : ZohoBooks.projects.UPDATE`

### Path Parameters

| Parameter       | Type   | Required | Description                          |
| :-------------- | :----- | :------- | :----------------------------------- |
| `time_entry_id` | string | Required | Unique identifier of the time entry. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Arguments

| Argument      | Type    | Required | Description                                                                                                          |
| :------------ | :------ | :------- | :------------------------------------------------------------------------------------------------------------------- |
| `project_id`  | string  | Required | ID of the project.                                                                                                   |
| `task_id`     | string  | Required | ID of the task.                                                                                                      |
| `user_id`     | string  | Required | ID of the user.                                                                                                      |
| `log_date`    | string  | Required | Date on which the user spent on the task. `Date-Format [HH:mm]`                                                      |
| `log_time`    | string  | Optional | Time the user spent on this task. Either send this attribute or begin and end time attributes. `Time-Format [HH:mm]` |
| `begin_time`  | string  | Optional | Time the user started working on this task. `Time-Format [HH:mm]`                                                    |
| `end_time`    | string  | Optional | Time the user stopped working on this task. `Time-Format [HH:mm]`                                                    |
| `is_billable` | boolean | Optional | Whether it is billable or not.                                                                                       |
| `notes`       | string  | Optional | Description of the work done. `Max-length [500]`                                                                     |
| `start_timer` | string  | Optional | Start timer.                                                                                                         |
| `cost_rate`   | double  | Optional | Hourly cost rate                                                                                                     |

### Request Example

```bash
curl --request PUT \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/460000000044021?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f' \
  --header 'content-type: application/json' \
  --data '{"project_id":"Network Distribution","task_id":"460000000044001","user_id":"460000000024003","log_date":"2013-09-17","log_time":" ","begin_time":"10:00","end_time":"15:00","is_billable":true,"notes":" ","start_timer":" ","cost_rate":0}'
```

### Response Example

```json
{
    "code": 0,
    "message": "The timesheet's information has been updated.",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": "",
        "cost_rate": 0
    }
}
```

---

## Get a time entry

Get details of a time entry.

`OAuth Scope : ZohoBooks.projects.READ`

### Path Parameters

| Parameter       | Type   | Required | Description                          |
| :-------------- | :----- | :------- | :----------------------------------- |
| `time_entry_id` | string | Required | Unique identifier of the time entry. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/460000000044021?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": "",
        "cost_rate": 0
    }
}
```

---

## Delete time entry

Deleting a logged time entry.

`OAuth Scope : ZohoBooks.projects.DELETE`

### Path Parameters

| Parameter       | Type   | Required | Description                          |
| :-------------- | :----- | :------- | :----------------------------------- |
| `time_entry_id` | string | Required | Unique identifier of the time entry. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request DELETE \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/460000000044021?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The time entry has been deleted."
}
```

---

## Start timer

Start tracking time spent.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Path Parameters

| Parameter       | Type   | Required | Description                          |
| :-------------- | :----- | :------- | :----------------------------------- |
| `time_entry_id` | string | Required | Unique identifier of the time entry. |

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/460000000044021/timer/start?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "The timer has been started.",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": ""
    }
}
```

---

## Stop timer

Stop tracking time, say taking a break or leaving.

`OAuth Scope : ZohoBooks.projects.CREATE`

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request POST \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/timer/stop?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "Timer has been stopped successfully.",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": ""
    }
}
```

---

## Get timer

Get current running timer.

`OAuth Scope : ZohoBooks.projects.READ`

### Query Parameters

| Parameter         | Type   | Required | Description            |
| :---------------- | :----- | :------- | :--------------------- |
| `organization_id` | string | Required | ID of the organization |

### Request Example

```bash
curl --request GET \
  --url 'https://www.zohoapis.com/books/v3/projects/timeentries/runningtimer/me?organization_id=10234695' \
  --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### Response Example

```json
{
    "code": 0,
    "message": "success",
    "time_entry": {
        "time_entry_id": "460000000044021",
        "project_id": "460000000044019",
        "project_name": "REAL TIME TRAFFIC FLUX",
        "customer_id": "460000000044001",
        "customer_name": "SAF Instruments Inc",
        "task_id": "460000000044009",
        "task_name": "Distribution Analysis",
        "user_id": "460000000024003",
        "user_name": "John David",
        "is_current_user": true,
        "log_date": "2013-09-17",
        "begin_time": "03:00",
        "end_time": "04:00",
        "log_time": "05:00",
        "is_billable": true,
        "billed_status": "unbilled",
        "invoice_id": "",
        "notes": " ",
        "timer_started_at": " ",
        "timer_started_at_utc_time": "",
        "timer_duration_in_minutes": " ",
        "timer_duration_in_seconds": "",
        "created_time": "2013-09-18T18:05:27+0530",
        "timesheet_custom_fields": ""
    }
}
```