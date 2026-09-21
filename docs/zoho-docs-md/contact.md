# Contacts

The list of contacts created.

### Attributes

| Attribute                                | Datatype | Description                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| :--------------------------------------- | :------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **contact_id**                           | string   | Unique identifier for the contact. System-generated ID used for API operations.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **contact_name**                         | string   | Display name for the contact. It is used for searching and displaying contacts.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **company_name**                         | string   | Legal or registered contact's company name. Used for legal documents and formal communications. Max-length [200].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **has_transaction**                      | boolean  | Indicates whether the contact has any transaction history in the system.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **contact_type**                         | string   | Determines how the contact is treated in the system. Allowed values: `customer`, `vendor`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **customer_sub_type**                    | string   | **For Customer Only:** Additional classification for customers. Allowed values: `individual`, `business`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **credit_limit**                         | double   | **For Customer Only:** The maximum credit amount that can be allowed for the customer. Once the customer's outstanding receivables reach this limit, the system will restrict the customer from creating any further transactions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **is_portal_enabled**                    | boolean  | Indicates whether portal access is enabled for the primary contact person. Allowed value: `true` and `false`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **language_code**                        | string   | Preferred language for the contact. Determines portal language. Allowed values: `de`, `en`, `es`, `fr`, `it`, `ja`, `nl`, `pt`, `pt_br`, `sv`, `zh`, `en_gb`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **is_taxable**                           | boolean  | Indicates whether the customer is subject to tax collection. Tax-related fields are only available when this field is set to true. Allowed values: `true` and `false`. <br>*(Supported Editions: US, Canada, Australia, India, Mexico, Kenya, South Africa)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **tax_id**                               | string   | Unique identifier for the tax or tax group assigned to the contact. Available only when `is_taxable` is `true`. <br>*(Supported Editions: India, US)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **tds_tax_id**                           | string   | Unique identifier for the Tax Deducted at Source (TDS) tax configuration assigned to the contact. <br>*(Supported Editions: Mexico)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **tax_name**                             | string   | Display name of the tax assigned to the contact. <br>*(Supported Editions: India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **tax_percentage**                       | double   | Tax percentage assigned to the contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **tax_authority_id**                     | string   | Unique identifier for the tax authority responsible for the customer's tax jurisdiction. Tax authority depends on the location of the customer. For example, if the customer is located in NY, then the tax authority is NY tax authority. <br>*(Supported Editions: US)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **tax_exemption_id**                     | string   | Unique identifier for the tax exemption configuration assigned to this contact. <br>*(Supported Editions: US, Canada, Australia, India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **tax_authority_name**                   | string   | Display name of the tax authority responsible for the customer's tax jurisdiction.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **tax_exemption_code**                   | string   | Code identifier for the tax exemption assigned to the contact. <br>*(Supported Editions: US, Canada, Australia, India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **place_of_contact**                     | string   | State or union territory code where the contact is located for Indian tax purposes. (This node identifies the place of supply and source of supply when invoices/bills are raised for the customer/vendor respectively. This is not applicable for Overseas contacts). <br>*(Supported Editions: India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **gst_no**                               | string   | 15-digit GST identification number of the contact as issued by the Indian tax authorities. <br>*(Supported Editions: India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| **vat_treatment**                        | string   | VAT treatment of the contact. Allowed Values: <br>`uk` (A business that is located in the UK.)<br>`eu_vat_registered` (A business that is reg for VAT and trade goods between Northern Ireland and EU. This node is available only for organizations enabled for NI protocol in VAT Settings.)<br>`overseas` (A business that is located outside UK. Pre Brexit, this was split as `eu_vat_registered`, `eu_vat_not_registered` and `non_eu`). <br>*(Supported Editions: UK)*                                                                                                                                                                                                                                                                                       |
| **tax_treatment**                        | string   | Tax treatment of the contact. <br>Allowed Values:<br>`vat_registered`, `vat_not_registered`, `gcc_vat_not_registered`, `gcc_vat_registered`, `non_gcc`, `dz_vat_registered` and `dz_vat_not_registered`<br>`home_country_mexico` (A business that is located within MX)<br>`border_region_mexico` (A business that is located in the northern and southern border regions in MX)<br>`non_mexico` (A business that is located outside MX).<br>**For Kenya Edition:** `vat_registered`, `vat_not_registered`, `non_kenya`(A business that is located outside Kenya).<br>**For SouthAfrica Edition:** `vat_registered`, `vat_not_registered`, `overseas`(A business that is located outside SouthAfrica). <br>*(Supported Editions: GCC, Mexico, Kenya, South Africa)* |
| **tax_exemption_certificate_number**     | string   | Tax Exemption Certificate number is issued by the Kenya Revenue Authority (KRA) to organizations or individuals who qualify for tax exemption. <br>*(Supported Editions: Kenya)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **tax_regime**                           | string   | Tax Regime of the contact. Allowed Values: `general_legal_person`, `legal_entities_non_profit`, `resident_abroad`, `production_cooperative_societies`, `agricultural_livestock`, `optional_group_of_companies`, `coordinated`, `simplified_trust`, `wages_salaries_income`, `lease`, `property_disposal_acquisition`, `other_income`, `resident_abroad`, `divident_income`, `individual_business_professional`, `interest_income`, `income_obtaining_price`, `no_tax_obligation`, `tax_incorporation`, `income_through_technology_platform`, `simplified_trust`. <br>*(Supported Editions: Mexico)*                                                                                                                                                                 |
| **legal_name**                           | string   | Official legal name of the contact as registered with tax authorities in Mexico. <br>*(Supported Editions: Mexico)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                 |
| **is_tds_registered**                    | boolean  | Indicates whether the contact is registered for Tax Deducted at Source (TDS) in Mexico. <br>*(Supported Editions: Mexico)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **gst_treatment**                        | string   | Choose whether the contact is GST registered/unregistered/consumer/overseas. Allowed values are `business_gst`, `business_none`, `overseas`, `consumer`. <br>*(Supported Editions: India)*                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **is_linked_with_zohocrm**               | boolean  | Indicates whether this contact is linked with Zoho CRM.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **website**                              | string   | Official website URL of the contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **owner_id**                             | string   | **For Customer Only:** Unique identifier for the user assigned as the owner of the contact. This field specifies which user in the organization is responsible for managing the business relationship with this contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **primary_contact_id**                   | string   | Unique identifier for the primary contact person of the contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **pricebook_id**                         | string   | Pricebook id which is associated with the contact. Max-length [200].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                |
| **contact_number**                       | string   | Contact number associated with the contact for internal tracking and identification purposes. Max-length [200].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **ignore_auto_number_generation**        | boolean  | Indicates whether the auto generation contact_number is ignored or not for the contact. Allowed values: `true`, `false`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **payment_terms**                        | integer  | Number of days allowed for payment after the invoice date.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_terms_label**                  | string   | Human-readable label of payment terms displayed on invoices and other transactions. Max-length [200].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| **currency_id**                          | string   | Unique identifier for the currency assigned to this contact. The currency_id must correspond to a valid currency configuration in the system.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **currency_code**                        | string   | Three-letter ISO currency code for the currency assigned to this contact. If not specified, the organization's default currency will be used.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                       |
| **currency_symbol**                      | string   | Currency symbol that represents the currency assigned to this contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **opening_balances**                     | array    | Details of opening balances. Contains `location_id`, `exchange_rate`, `opening_balance_amount`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **outstanding_receivable_amount**        | integer  | Total amount owed by the customer for all outstanding invoices and transactions.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **outstanding_receivable_amount_bcy**    | integer  | Total amount owed by the customer in the organization's base currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |
| **unused_credits_receivable_amount**     | integer  | Total amount of unused credits available for the customer.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **unused_credits_receivable_amount_bcy** | integer  | Total amount of unused credits available for the customer in base currency.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **status**                               | string   | Indicates whether the contact is active or inactive. Allowed values: `active`, `inactive`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **payment_reminder_enabled**             | boolean  | Indicates whether automated payment reminders are enabled for this contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| **custom_fields**                        | array    | Custom fields of the contact. Contains `index`, `value`, `label`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                   |
| **billing_address**                      | object   | Billing address information. Contains `attention`, `address`, `street2`, `state_code`, `city`, `state`, `zip`, `country`, `fax`, `phone`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                           |
| **shipping_address**                     | object   | Shipping address information. Contains `attention`, `address`, `street2`, `state_code`, `city`, `state`, `zip`, `country`, `fax`, `phone`.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                          |
| **facebook**                             | string   | Facebook profile URL for the contact. Max-length [100].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                             |
| **twitter**                              | string   | X profile URL for the contact. Max-length [100].                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                    |
| **contact_persons**                      | array    | List of contact persons. Contains `contact_person_id`, `salutation`, `first_name`, `last_name`, `email`, `phone`, `mobile`, `designation`, `department`, `skype`, `is_primary_contact`, `enable_portal`, and `communication_preference` (`is_sms_enabled`, `is_whatsapp_enabled`).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  |
| **default_templates**                    | object   | Default templates associated with the contact (invoices, estimates, credit notes, etc.).                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                            |
| **notes**                                | string   | Additional comments or notes about the contact.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **created_time**                         | string   | Timestamp when the contact was initially created in the system.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                     |
| **last_modified_time**                   | string   | Timestamp when the contact was last updated or modified in the system.                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                              |

---

## Create a Contact

Create a new contact with comprehensive business information. This operation allows you to create a customer or vendor by providing details such as contact name, company information, addresses, contact persons, payment terms, tax settings, and custom fields.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts`

### Arguments

| Parameter                            | Datatype | Description                                                                                                                  |
| :----------------------------------- | :------- | :--------------------------------------------------------------------------------------------------------------------------- |
| **contact_name**                     | string   | **(Required)** Display name for the contact. It is used for searching and displaying contacts.                               |
| **company_name**                     | string   | Legal or registered contact's company name. Used for legal documents and formal communications. Max-length [200].            |
| **website**                          | string   | Official website URL of the contact.                                                                                         |
| **language_code**                    | string   | Preferred language for the contact. Determines portal language. Allowed values: `de,en,es,fr,it,ja,nl,pt,pt_br,sv,zh,en_gb`. |
| **contact_type**                     | string   | Determines how the contact is treated in the system. Allowed values: `customer`, `vendor`.                                   |
| **customer_sub_type**                | string   | **For Customer Only:** Additional classification for customers. Allowed values: `individual`, `business`.                    |
| **credit_limit**                     | double   | **For Customer Only:** The maximum credit amount that can be allowed for the customer.                                       |
| **pricebook_id**                     | string   | Pricebook id which is associated with the contact. Max-length [200].                                                         |
| **contact_number**                   | string   | Contact number associated with the contact for internal tracking and identification purposes. Max-length [200].              |
| **ignore_auto_number_generation**    | boolean  | Indicates whether the auto generation contact_number is ignored or not for the contact. Allowed values: `true`, `false`.     |
| **tags**                             | array    | Filter all your reports based on the tag. Contains `tag_id`, `tag_option_id`.                                                |
| **is_portal_enabled**                | boolean  | Indicates whether portal access is enabled for the primary contact person. Allowed value: `true` and `false`.                |
| **currency_id**                      | string   | Unique identifier for the currency assigned to this contact.                                                                 |
| **payment_terms**                    | integer  | Number of days allowed for payment after the invoice date.                                                                   |
| **payment_terms_label**              | string   | Human-readable label of payment terms displayed on invoices and other transactions. Max-length [200].                        |
| **notes**                            | string   | Additional comments or notes about the contact.                                                                              |
| **billing_address**                  | object   | Billing address information for the contact.                                                                                 |
| **shipping_address**                 | object   | Shipping address information for the contact.                                                                                |
| **contact_persons**                  | array    | Array of contact persons details.                                                                                            |
| **default_templates**                | object   | Default templates for various modules.                                                                                       |
| **custom_fields**                    | array    | Custom fields of the contact.                                                                                                |
| **opening_balances**                 | array    | Opening balance details.                                                                                                     |
| **vat_reg_no**                       | string   | **For UK Edition:** VAT Registration number (2-12 chars). **For Avalara:** VAT Reg Number for EU sales.                      |
| **owner_id**                         | string   | **For Customer Only:** Unique identifier for the user assigned as the owner of the contact.                                  |
| **tax_reg_no**                       | string   | Tax Registration Number. Formats vary by edition (GCC: 15 digits, Mexico: 12 digits, Kenya: 11 digits, SA: 10 digits).       |
| **tax_exemption_certificate_number** | string   | **For Kenya Edition:** Tax Exemption Certificate number.                                                                     |
| **country_code**                     | string   | Two letter country code. Important for UK, GCC, and Avalara integrations.                                                    |
| **vat_treatment**                    | string   | **For UK Edition:** VAT treatment (`uk`, `eu_vat_registered`, `overseas`).                                                   |
| **tax_treatment**                    | string   | Tax treatment based on edition (GCC, Mexico, Kenya, South Africa).                                                           |
| **tax_regime**                       | string   | **For Mexico Edition:** Tax Regime of the contact.                                                                           |
| **legal_name**                       | string   | **For Mexico Edition:** Official legal name of the contact.                                                                  |
| **is_tds_registered**                | boolean  | **For Mexico Edition:** Indicates whether the contact is registered for TDS.                                                 |
| **place_of_contact**                 | string   | **For India Edition:** State or union territory code.                                                                        |
| **gst_no**                           | string   | **For India Edition:** 15-digit GST identification number.                                                                   |
| **gst_treatment**                    | string   | **For India Edition:** GST status (`business_gst`, `business_none`, `overseas`, `consumer`).                                 |
| **tax_authority_name**               | string   | Display name of the tax authority.                                                                                           |
| **avatax_exempt_no**                 | string   | **Avalara:** Exemption certificate number.                                                                                   |
| **avatax_use_code**                  | string   | **Avalara:** Used to group like customers for exemption purposes.                                                            |
| **tax_exemption_id**                 | string   | **For US/CA/AU/IN:** Unique identifier for the tax exemption configuration.                                                  |
| **tax_exemption_code**               | string   | **For US/CA/AU/IN:** Code identifier for the tax exemption.                                                                  |
| **tax_authority_id**                 | string   | **For US Edition:** Unique identifier for the tax authority.                                                                 |
| **tax_id**                           | string   | **For India/US:** Unique identifier for the tax or tax group.                                                                |
| **tds_tax_id**                       | string   | **For Mexico:** Unique identifier for the TDS tax configuration.                                                             |
| **is_taxable**                       | boolean  | Indicates whether the customer is subject to tax collection.                                                                 |
| **facebook**                         | string   | Facebook profile URL.                                                                                                        |
| **twitter**                          | string   | X profile URL.                                                                                                               |
| **track_1099**                       | boolean  | **For US Edition:** Boolean to track a contact for 1099 reporting.                                                           |
| **tax_id_type**                      | string   | **For US Edition:** Tax ID type (SSN, ATIN, ITIN, EIN).                                                                      |
| **tax_id_value**                     | string   | **For US Edition:** Tax ID of the contact.                                                                                   |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Update a contact using a custom field's unique value

Update a contact by providing its API name in the `X-Unique-Identifier-Key` header and its value in the `X-Unique-Identifier-Value` header.

`OAuth Scope : ZohoBooks.contacts.UPDATE`

**Method:** `PUT`
**URL:** `/contacts`

### Headers

| Header                        | Datatype | Description                                                |
| :---------------------------- | :------- | :--------------------------------------------------------- |
| **X-Unique-Identifier-Key**   | string   | **(Required)** Unique CustomField Api Name                 |
| **X-Unique-Identifier-Value** | string   | **(Required)** Unique CustomField Value                    |
| **X-Upsert**                  | boolean  | If true and no record is found, will create a new contact. |

### Arguments
*Accepts the same arguments as Create Contact.*

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## List Contacts

Retrieve a comprehensive list of all contacts with advanced filters.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts`

### Query Parameters

| Parameter           | Datatype | Description                                                                                                                                                                                                             |
| :------------------ | :------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization                                                                                                                                                                                   |
| **contact_type**    | string   | Search contacts by contact type. Allowed Values: `customer`, `vendor`.                                                                                                                                                  |
| **contact_name**    | string   | Search by contact name. Variants: `contact_name_startswith` and `contact_name_contains`.                                                                                                                                |
| **company_name**    | string   | Search by company name. Variants: `company_name_startswith` and `company_name_contains`.                                                                                                                                |
| **first_name**      | string   | Search by first name of the primary contact person. Variants: `first_name_startswith`, `first_name_contains`.                                                                                                           |
| **last_name**       | string   | Search by last name. Variants: `last_name_startswith`, `last_name_contains`.                                                                                                                                            |
| **address**         | string   | Search by any address field. Variants: `address_startswith`, `address_contains`.                                                                                                                                        |
| **email**           | string   | Search by email. Variants: `email_startswith`, `email_contains`.                                                                                                                                                        |
| **phone**           | string   | Search by phone. Variants: `phone_startswith`, `phone_contains`.                                                                                                                                                        |
| **filter_by**       | string   | Filter by status: `Status.All`, `Status.Active`, `Status.Inactive`, `Status.Duplicate`, `Status.PortalEnabled`, `Status.PortalDisabled`, `Invoice.OverDue`, `Invoice.Unpaid`, `Status.CreditLimitExceed`, `Status.Crm`. |
| **search_text**     | string   | Search contacts by contact name or notes.                                                                                                                                                                               |
| **sort_column**     | string   | Sort contacts. Allowed Values: `contact_name`, `first_name`, `last_name`, `email`, `outstanding_receivable_amount`, `created_time`, `last_modified_time`.                                                               |
| **zcrm_contact_id** | string   | CRM Contact ID for the contact.                                                                                                                                                                                         |
| **zcrm_account_id** | string   | CRM Account ID for the contact.                                                                                                                                                                                         |
| **zcrm_vendor_id**  | string   | CRM Vendor ID for the contact.                                                                                                                                                                                          |
| **page**            | integer  | Page number to be fetched. Default value is 1.                                                                                                                                                                          |
| **per_page**        | integer  | Number of records to be fetched per page. Default value is 200.                                                                                                                                                         |

---

## Update a Contact

Update an existing contact with comprehensive business information.

`OAuth Scope : ZohoBooks.contacts.UPDATE`

**Method:** `PUT`
**URL:** `/contacts/{contact_id}`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Arguments
*Accepts the same arguments as Create Contact.*

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Get Contact

Retrieve comprehensive details of a specific contact.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Delete a Contact

Delete an existing contact.

`OAuth Scope : ZohoBooks.contacts.DELETE`

**Method:** `DELETE`
**URL:** `/contacts/{contact_id}`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Mark as Active

Mark a contact as active.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/active`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Mark as Inactive

Mark a contact as inactive.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/inactive`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Enable Portal Access

Enable portal access for a contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/portal/enable`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Arguments

| Parameter           | Datatype | Description                                                                               |
| :------------------ | :------- | :---------------------------------------------------------------------------------------- |
| **contact_persons** | array    | **(Required)** List containing `contact_person_id` to enable portal for specific persons. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Enable Payment Reminders

Enable automated payment reminders for a contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/paymentreminder/enable`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Disable Payment Reminders

Disable automated payment reminders for a contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/paymentreminder/disable`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Email Statement

Email statement to the contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/statements/email`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Arguments

| Parameter                  | Datatype | Description                                                          |
| :------------------------- | :------- | :------------------------------------------------------------------- |
| **send_from_org_email_id** | boolean  | Boolean to trigger the email from the organization's email address.  |
| **to_mail_ids**            | array    | **(Required)** Array of email address of the recipients.             |
| **cc_mail_ids**            | array    | Array of email address of the recipients to be cced.                 |
| **subject**                | string   | **(Required)** Subject of an email has to be sent. Max-length [1000] |
| **body**                   | string   | **(Required)** Body of an email has to be sent. Max-length [5000]    |

### Query Parameters

| Parameter                 | Datatype | Description                                                                      |
| :------------------------ | :------- | :------------------------------------------------------------------------------- |
| **organization_id**       | string   | **(Required)** ID of the organization                                            |
| **start_date**            | string   | Start date for the statement (yyyy-mm-dd). Defaults to current month if not set. |
| **end_date**              | string   | End date for the statement (yyyy-mm-dd).                                         |
| **multipart_or_formdata** | string   | Files to be attached along with the statement.                                   |

---

## Get Statement Mail Content

Get the statement mail content.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/statements/email`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                                |
| :------------------ | :------- | :----------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization      |
| **start_date**      | string   | Start date for the statement (yyyy-mm-dd). |
| **end_date**        | string   | End date for the statement (yyyy-mm-dd).   |

---

## Email Contact

Send email to contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/email`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Arguments

| Parameter       | Datatype | Description                                                                 |
| :-------------- | :------- | :-------------------------------------------------------------------------- |
| **to_mail_ids** | array    | **(Required)** Array of email address of the recipients.                    |
| **subject**     | string   | **(Required)** Subject of an email has to be sent. Max-length [1000]        |
| **body**        | string   | **(Required)** Body of an email has to be sent. Max-length [5000]           |
| **attachments** | binary   | Files to be attached to the email. It has to be sent in multipart/formdata. |

### Query Parameters

| Parameter                   | Datatype | Description                             |
| :-------------------------- | :------- | :-------------------------------------- |
| **organization_id**         | string   | **(Required)** ID of the organization   |
| **send_customer_statement** | boolean  | Send customer statement pdf with email. |

---

## List Comments

List recent activities of a contact.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/comments`

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

---

## Add Additional Address

Add an additional address for a contact.

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/address`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Arguments

| Parameter     | Datatype | Description                                                                             |
| :------------ | :------- | :-------------------------------------------------------------------------------------- |
| **attention** | string   | Attention for proper delivery and routing of business correspondence. Max-length [100]. |
| **address**   | string   | Street 1 address for the contact. Max-length [500].                                     |
| **street2**   | string   | Street 2 address for the contact. Max-length [255].                                     |
| **city**      | string   | City name for the address. Max-length [100].                                            |
| **state**     | string   | State for the address. Max-length [100].                                                |
| **zip**       | string   | Postal or ZIP code for the address. Max-length [50].                                    |
| **country**   | string   | Country name for the address. Max-length [100].                                         |
| **fax**       | string   | Fax number for the address. Max-length [50].                                            |
| **phone**     | string   | The contact phone number associated with the address. Max-length [50].                  |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Get Contact Addresses

Get addresses of a contact including its Shipping Address, Billing Address and other additional addresses.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/address`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Edit Additional Address

Edit the additional address of a contact.

`OAuth Scope : ZohoBooks.contacts.UPDATE`

**Method:** `PUT`
**URL:** `/contacts/{contact_id}/address/{address_id}`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |
| **address_id** | string   | **(Required)** Unique identifier of the address. |

### Arguments

| Parameter      | Datatype | Description                               |
| :------------- | :------- | :---------------------------------------- |
| **address_id** | string   | **(Required)** Address id of the address. |
| **attention**  | string   | Attention for proper delivery.            |
| **address**    | string   | Street 1 address.                         |
| **street2**    | string   | Street 2 address.                         |
| **city**       | string   | City name.                                |
| **state**      | string   | State.                                    |
| **zip**        | string   | Postal or ZIP code.                       |
| **country**    | string   | Country name.                             |
| **fax**        | string   | Fax number.                               |
| **phone**      | string   | Contact phone number.                     |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Delete Additional Address

Delete the additional address of a contact.

`OAuth Scope : ZohoBooks.contacts.DELETE`

**Method:** `DELETE`
**URL:** `/contacts/{contact_id}/address/{address_id}`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |
| **address_id** | string   | **(Required)** Unique identifier of the address. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## List Refunds

List the refund history of a contact.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/refunds`

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

---

## Track 1099

Track a contact for 1099 reporting. *(Note: This API is only available when the organization's country is U.S.A).*

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/track1099`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Untrack 1099

Use this API to stop tracking payments to a vendor for 1099 reporting. *(Note: This API is only available when the organization's country is U.S.A).*

`OAuth Scope : ZohoBooks.contacts.CREATE`

**Method:** `POST`
**URL:** `/contacts/{contact_id}/untrack1099`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                           |
| :------------------ | :------- | :------------------------------------ |
| **organization_id** | string   | **(Required)** ID of the organization |

---

## Get Unused Retainer Payments

Retrieve information about unused retainer payments for a specific contact.

`OAuth Scope : ZohoBooks.contacts.READ`

**Method:** `GET`
**URL:** `/contacts/{contact_id}/receivables/unusedretainerpayments`

### Path Parameters

| Parameter      | Datatype | Description                                      |
| :------------- | :------- | :----------------------------------------------- |
| **contact_id** | string   | **(Required)** Unique identifier of the contact. |

### Query Parameters

| Parameter           | Datatype | Description                                                          |
| :------------------ | :------- | :------------------------------------------------------------------- |
| **organization_id** | string   | **(Required)** ID of the organization                                |
| **currency_id**     | string   | Currency ID to filter unused retainer payments by specific currency. |