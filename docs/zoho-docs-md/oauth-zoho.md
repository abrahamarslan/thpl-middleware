# OAuth Overview 

The Zoho Books APIs use the Open Authorization (OAuth) 2.0 protocol for authentication. This industry-standard protocol specification enables third-party applications (clients) to gain delegated access to protected resources in Zoho via an API.

## Why we use OAuth2.0?

-   Clients are not required to support password authentication or store user credentials.
-   Clients are provided with delegated access; they can only access resources authenticated by the user.
-   Users can revoke the client's delegated access anytime.
-   OAuth2.0 access tokens expire after a set period.

## How does the OAuth 2.0 authentication work?

![OAuth 2.0 Authentication Workflow](/books/api/v3/images/oauth_workflow.jpg)

# Terminologies

The following are the terms you need to know before you start using the Zoho Books APIs.

Term

Description

Protected Resources

The Zoho Books resources such as Invoices, Customers, Sales Orders, etc.

Resource Server

The Zoho Books server that hosts the protected resources.

Resource Owner

An end-user of your organization who can grant access to the protected resources.

Client

An application that sends requests to the resource server to access the protected resources on behalf of the end-user.

Client ID

The consumer key generated from the connected application.

Client Secret

The consumer secret generated from the connected application.

Authentication Server

The server that provides the necessary credentials,such as Access Tokens and Refresh Tokens, to the client. In this case, Zoho Books is the authorization server.

Authentication Code

The authorization server creates a temporary token and sends it to the client via the browser. The client will send this code to the authorization server to obtain access and refresh tokens.

Tokens

Access Token

The token that is sent to the resource server to access the user's protected resources. It provides secure and temporary access to Zoho Books APIs and is used by the applications to make requests to the connected app. Each access token is valid only for an hour and can be used only for the operations that are specified in the scope.

Refresh Token

The token that can be used to obtain new access tokens. This token has an unlimited lifetime until it is revoked by the end-user.

_Note: Access Tokens must be kept confidential since they define the type of API that you use. Do not expose your Access Tokens anywhere in public forums, public repositories, or on your website's client-side code like HTML or JavaScript. Exposing it to the public may lead to data theft, loss, or corruption._

# Scopes

Scope determines which protected resource of an end-user a client has requested access to. A scope has three parameters: service name, scope name, and operation type.

The format to define a scope is  
**scope = service\_name.scope\_name.operation\_type**

**Operation type:** CREATE, READ, UPDATE, DELETE, ALL

**List of scopes available in Zoho Books:**

Scope

Description

Available Operation Types

contacts

Access the APIs of the Contacts (Customers and Vendors) modules.

`ZohoBooks.contacts.CREATE, ZohoBooks.contacts.UPDATE, ZohoBooks.contacts.READ, ZohoBooks.contacts.DELETE, ZohoBooks.contacts.ALL`

settings

Access the APIs related to Items, Expense Categories, Users, Taxes, Currencies, and Opening Balances preferences in Settings.

`ZohoBooks.settings.CREATE, ZohoBooks.settings.UPDATE, ZohoBooks.settings.READ, ZohoBooks.settings.DELETE, ZohoBooks.settings.ALL`

estimates

Access the APIs of the Quotes/Estimates module .

`ZohoBooks.estimates.CREATE, ZohoBooks.estimates.UPDATE, ZohoBooks.estimates.READ, ZohoBooks.estimates.DELETE, ZohoBooks.estimates.ALL`

invoices

Access the APIs of the Invoices module.

`ZohoBooks.invoices.CREATE, ZohoBooks.invoices.UPDATE, ZohoBooks.invoices.READ, ZohoBooks.invoices.DELETE, ZohoBooks.invoices.ALL`

customer payments

Access the APIs of the Payments Received (customer payments) module.

`ZohoBooks.customerpayments.CREATE, ZohoBooks.customerpayments.UPDATE, ZohoBooks.customerpayments.READ, ZohoBooks.customerpayments.DELETE, ZohoBooks.customerpayments.ALL`

credit notes

Access the APIs of the Credit Notes module.

`ZohoBooks.creditnotes.CREATE, ZohoBooks.creditnotes.UPDATE, ZohoBooks.creditnotes.READ, ZohoBooks.creditnotes.DELETE, ZohoBooks.creditnotes.ALL`

projects

Access the APIs of the Projects module.

`ZohoBooks.projects.CREATE, ZohoBooks.projects.UPDATE, ZohoBooks.projects.READ, ZohoBooks.projects.DELETE, ZohoBooks.projects.ALL`

expenses

Access the APIs of the Expenses module.

`ZohoBooks.expenses.CREATE, ZohoBooks.expenses.UPDATE, ZohoBooks.expenses.READ, ZohoBooks.expenses.DELETE, ZohoBooks.expenses.ALL`

salesorder

Access the APIs of the Sales Orders module.

`ZohoBooks.salesorders.CREATE, ZohoBooks.salesorders.UPDATE, ZohoBooks.salesorders.READ, ZohoBooks.salesorders.DELETE, ZohoBooks.salesorders.ALL`

purchase orders

Access the APIs of the Purchase Orders module.

`ZohoBooks.purchaseorders.CREATE, ZohoBooks.purchaseorders.UPDATE, ZohoBooks.purchaseorders.READ, ZohoBooks.purchaseorders.DELETE, ZohoBooks.purchaseorders.ALL`

bills

Access the APIs of the Bills module.

`ZohoBooks.bills.CREATE, ZohoBooks.bills.UPDATE, ZohoBooks.bills.READ, ZohoBooks.bills.DELETE, ZohoBooks.bills.ALL`

debit notes

Access the APIs of the Vendor Credits (debit notes) module.

`ZohoBooks.debitnotes.CREATE, ZohoBooks.debitnotes.UPDATE, ZohoBooks.debitnotes.READ, ZohoBooks.debitnotes.DELETE, ZohoBooks.debitnotes.ALL`

vendor payments

Access the APIs of the Payments Made (vendor payment) module.

`ZohoBooks.vendorpayments.CREATE, ZohoBooks.vendorpayments.UPDATE, ZohoBooks.vendorpayments.READ, ZohoBooks.vendorpayments.DELETE, ZohoBooks.vendorpayments.ALL`

banking

Access the APIs of the Banking module.

`ZohoBooks.banking.CREATE, ZohoBooks.banking.UPDATE, ZohoBooks.banking.READ, ZohoBooks.banking.DELETE, ZohoBooks.banking.ALL`

accountants

Access the APIs of the Accountant module.

`ZohoBooks.accountants.CREATE, ZohoBooks.accountants.UPDATE, ZohoBooks.accountants.READ, ZohoBooks.accountants.DELETE, ZohoBooks.accountants.ALL`

# Steps to generate and use OAuth token

### **1\. Registering New Client**

To make requests using the Zoho Books APIs, you need to register your application with Zoho Books. Here's how:

-   Go to the [Zoho Developer Console.](https://api-console.zoho.com/)
-   Choose a client type.

Client Type

Description

Client-based Applications

Applications that are built to run exclusively on browsers independent of the web servers.

Server-based Applications

Web-based applications that are built to run with a dedicated HTTP server and intended for use by multiple Zoho accounts.  
These applications may address specific use cases for different Zoho accounts and should have both a dedicated backend server and web UI to handle the authorization process and the application's logic.  
The application redirects users to Zoho for the authorization process using a web browser, allowing users to grant permission for the app to access their Zoho data on their behalf.

Mobile-based Applications

Applications that are built to run on smartphones and tablets.

Non-browser Applications

Applications that run on devices without browsers such as smart TVs and printers.

Self Client

Applications that do not have a redirect URL or a web UI, operating solely in the backend without requiring user interaction.  
A self-client is commonly employed when both the application and Zoho services are managed by the same person, aiming to establish secure communication between them.

_**Note:** For more details on Client types, refer to [https://www.zoho.com/accounts/protocol/oauth.html](https://www.zoho.com/accounts/protocol/oauth.html)_

-   Enter the following details.

-   **Client Name:** The name of your application you want to register with Zoho Books.
-   **Homepage URL:** The URL of your webpage.  
    Only the following client types require this:

1.  Client-based applications
2.  Server-based applications
3.  Mobile-based applications
4.  Non-browser applications

-   **Authorized Redirect URLs:** A valid URL of your application to which Zoho Accounts redirects you with a grant token (code) after successful authentication.  
    Only the following client types require this:

1.  Client-based applications
2.  Server-based applications
3.  Mobile-based applications
4.  Non-browser applications

-   Click **CREATE**. You will receive the Client ID and Client Secret.

### **2\. Make the Authorization Request**

-   An **Access token** is an OAuth token used to access Zoho's protected resources. The method for generating the access token depends on the app used. For example, server-based apps can use the authorization code flow to generate an access token, while client-based apps can use the implicit flow.
-   However, in any method, the access token will be provided only after the user grants permission through consent. The access tokens are always granted for the specific scopes which are mentioned in the request, and the scopes will be displayed to the user while asking for permission.
-   To use the Zoho Books APIs, the users must authenticate the application to make API calls on their behalf with an access token. The access token, in return, must be obtained from a grant token (authorization code). The Zoho Books APIs use the authorization code **grant type** to provide access to protected resources.
-   There are two ways in which you can generate the grant token based on the client type.

1.  Web based applications
2.  Self client

### **i) Web Based Applications**

**_Note:_ Replace {Accounts\_URL} with your [domain specific Zoho Accounts URL](/books/api/v3/oauth/#multi-dc) while generating tokens.**

To generate a grant token for web-based applications, hit the below GET HTTP request in any browser:

**Request:**

**HTTP Request Type:** GET

**URI Endpoint:** {Accounts\_URL}/oauth/v2/auth

**Request Parameters:**

**Mandatory:**

**client\_id** - Obtained from registering your client in the Zoho Accounts developer console.

**response\_type** - Value must be **code**.

**redirect\_uri** - The URI endpoint that Zoho Accounts will redirect the web browser to with the authorization code after authorizing the client.  
**Make sure the authorized redirect URI is the same as the one provided while registering your client.**

**scope** - Sample scope - "ZohoBooks.invoices.READ"

**Optional:**

**access\_type** - Value can be **offline** or **online**. If the access\_type is not mentioned as offline, by default it will be considered as online.

-   If the value is **offline**, you will receive a refresh token along with the access token the first time you make the request. Once the access token expires, you can use the refresh token to regenerate it.
-   If the value is **online**, you will receive only the access token. If you forget your refresh token or cannot access it, use the following parameter along with access\_type to receive a new refresh token.

**prompt** - Value must be **consent**. If this parameter is included in the query, whenever you generate an OAuth token, the user's consent approval will be mandatory.

**Example Request:** To receive another refresh token, include **access\_type=offline** and **prompt=consent** in your authorization request.

**Response:**

With the request, you'll be redirected to the User Consent page.

Upon clicking **Accept**, Zoho will redirect to the given redirect\_uri with code and state param. This code value is mandatory to get the access token in the next step, and this code will be valid for 2 minutes.

On clicking **Deny**, the server will return an error.

**Request Example**
```curl
https://accounts.zoho.com/oauth/v2/auth?scope=ZohoBooks.invoices.CREATE,ZohoBooks.invoices.READ,ZohoBooks.invoices.UPDATE,ZohoBooks.invoices.DELETE&client_id=1000.0SRSxxxxxxxxxxxxxxxxxxxx239V&state=testing&response_type=code&redirect_uri=http://www.zoho.com/books&access_type=offline&prompt=consent
```

### **ii) Self Client**

Use this method to generate the organization-specific grant token if your application does not have a domain and a redirect URL. You can also use this option when your application is a standalone server-side application performing a back-end job.

**To generate grant token:**

1.  Go to [Zoho Developer Console](https://api-console.zoho.com/) and log in with your Zoho Books username and password.
2.  Choose **Self Client** from the list of client types, and click **Create Now.**
3.  Click **OK** in the pop-up to enable a self client for your account. Your Client ID and Client Secret will be available in the **Client Secret** tab.
4.  Click the **Generate Code** tab and enter the required scope separated by commas. Refer to our list of Scopes\[Scopes link will be attached\], for more details. The system will throw the **Enter a valid scope error** when you enter one or more incorrect scopes.
5.  Select the **Time Duration** for which the grant token should be valid. Note that after the specified time, the grant token will expire.
6.  Enter a description and click **Create**. The grant token code for the specified scope will be displayed. Copy it.

### **Possible errors:**

**1\. invalid\_redirect\_uri in /oauth/v2/auth**

**Solution:**

Ensure the Redirect URI you pass in /oauth/v2/auth matches the one you have registered in the developer console.

### **3\. Generating Access and Refresh Tokens**

OAuth2.0 requests are usually authenticated with an access token, which is passed as bearer token. To use this access token, you need to construct a normal HTTP request and include it in an authorization header along with the value of bearer.

**_Note:_ Replace {Accounts\_URL} with your [domain specific Zoho Accounts URL](/books/api/v3/oauth/#multi-dc) while generating tokens.**

To generate access and refresh token, hit the below POST HTTP request:

**Request:**

**HTTP Request Type:** POST

**URI Endpoint:** {Accounts\_URL}/oauth/v2/token

**Request Parameters:**

**grant\_type** - Enter the value as **authorization\_code**.

**client\_id** - Specify the Client ID obtained from the connected app.

**client\_secret** - Specify the Client Secret obtained from the connected app.

**redirect\_uri** - Specify the Callback URL that you registered during the app registration.

**code** - Enter the grant token generated from [step 2](/books/api/v3/oauth/#step2)

**Response:**

-   The **access\_token** will expire after a particular period(in seconds) (as given in the **expires\_in** param of the response).
-   The **refresh\_token** is permanent and will be used to generate new access token if the current access token is expired.
-   Each access token is only valid for one hour and can be used only for the operations defined in the scope.
-   A refresh token does not expire. Use it to regenerate access tokens when they expire.
-   Use the value in the **api\_domain** key to make API calls to Zoho Books

_**Note:** Each time a re-consent is accepted, a new refresh token is generated. The maximum limit is **20 refresh tokens** per user. If this limit is crossed, the first refresh token is automatically deleted to accommodate the latest one. This is done irrespective of whether the first refresh token is in use or not._

**Request Example**
```curl
curl -H "Content-Type: application/data" -X POST https://accounts.zoho.com/oauth/v2/token?code=1000.dd7exxxxxxxxxxxxxxxxxxxxxxxx9bb8.b6c0xxxxxxxxxxxxxxxxxxxxxxxxdca4&client_id=1000.0SRSxxxxxxxxxxxxxxxxxxxx239V&client_secret=fb01xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx8abf&redirect_uri=http://www.zoho.com/books&grant_type=authorization_code
```
  

Response Example

```json
{ "access_token": "{access_token}", "refresh_token": "{refresh_token}", "api_domain": "https://www.zohoapis.com", "token_type": "Bearer", "expires_in": 3600 }
```

### **Possible errors:**

**1\. Facing "server error" occurred in /oauth/v2/token**

**Solution:**

The endpoint /oauth/v2/token supports only POST request. Requests you hit directly from the browser are GET request. Since the token generation request contains sensitive information like client secret, refresh token, the GET request is not allowed for this endpoint.

When you make a POST request, the data sent to the server is stored in the request body of the HTTP request and they don't remain in browser history and is never cached.

POST request can be made from REST client tools like postman, advanced rest client, or from your application code.

**2\. invalid\_code in /oauth/v2/token ( If the grant\_type is authorization\_code )**

**Solution:**

The code value generated using /oauth/v2/auth is valid only for two minutes and is only one time usable. You will get invalid\_code when you use have already used the code or you try to use an expired code.

**3\. Refresh Token missing in response**

**Solution:**

**a. To receive refresh token for the first time:**

Include **access\_type=offline** in /oauth/v2/auth to get refresh token along with the access token as a response for /oauth/v2/token.

**b. To receive another refresh token:**

-   Passing **access\_type=offline** will give the refresh token along with the access token only the first time you use.
-   Adding the **prompt=consent** prompts for user consent whenever your app tries to access a user's details.
-   To receive another refresh token, include access\_type=offline and prompt=consent in your authorization request (/oauth/v2/auth).

**4\. invalid\_client or invalid\_client\_secret in /oauth/v2/token**

**Solution:**

Remove the new line character or extra space between the parameters.  
Ensure you're using the client id and secret registered in the same domain where you're trying to generate token

**5\. invalid\_client in /oauth/v2/token**

**Solution:**

The values required for /oauth/v2/token must be sent as **params**. This request does not support sending params as a JSON object or as an array in the body. Therefore, ensure that you include the parameters in the query string.

**Request Example**
```curl
curl -H "Content-Type: application/data" -X POST "https://accounts.zoho.com/oauth/v2/token?client_id=1000.Y0LXXXXXXXXXXXXXXXXXFI&client_secret=0xxxxxxxd&scope=AaaServer.profile.READ&grant_type=authorization_code&redirect_uri=https://iam&code=1000.b6xxxxxxxxx9"
```

### **4\. Refreshing Access Token**

**_Note:_ Replace {Accounts\_URL} with your [domain specific Zoho Accounts URL](/books/api/v3/oauth/#multi-dc) while generating tokens.**

Access tokens expire after an hour of generation. To generate a new access token, use the refresh token you generated earlier in [step 3](/books/api/v3/oauth/#step3). Make a HTTP POST request with the following URL:

**Request:**

**HTTP Request Type:** POST

**URI Endpoint:** {Accounts\_URL}/oauth/v2/token

**Request Parameters:**

**refresh\_token** - Refresh token generated.

**grant\_type** - Enter the value as **refresh\_token**.

**client\_id** - Specify the Client ID obtained from the connected app.

**client\_secret** - Specify the Client Secret obtained from the connected app.

**Response:**

The **new access token** will be received in response

**Request Example**
```curl
curl -H "Content-Type: application/data" -X POST https://accounts.zoho.com/oauth/v2/token?refresh_token=1000.8ecdxxxxxxxxxxxxxxxxxxxxx5cb7.4638xxxxxxxxxxxxxxxxxxxxxxebdc&client_id=1000.0SRSxxxxxxxxxxxxxxxxxxxx239V&client_secret=fb01xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx8abf&redirect_uri=http://www.zoho.com/books&grant_type=refresh_token
```
  

Response Example

```json
{ "access_token": "{new_access_token}", "api_domain": "https://www.zohoapis.com", "token_type": "Bearer", "expires_in": 3600 }
```

### **Possible errors:**

**1\. invalid\_code in /oauth/v2/token ( If the grant\_type is refresh\_token )**

**Solution:**

Ensure the refresh\_token has not been deleted. It may be deleted in the following cases:

1.  You revoked it from the Connected Apps in your Zoho Accounts.
2.  You revoked it using `https://accounts.zoho.com/oauth/v2/token/revoke?token={refresh_token}`
3.  You changed your Zoho Accounts password and opted for the removal of the web sessions.

### **5\. Revoking Access or Refresh token**

**_Note:_ Replace {Accounts\_URL} with your [domain specific Zoho Accounts URL](/books/api/v3/oauth/#multi-dc) while generating tokens.**

To revoke an access or refresh token, call the following POST URL with the given params:

**Request:**

**HTTP Request Type:** POST

**URI Endpoint:** {Accounts\_URL}/oauth/v2/token/revoke

**Request Parameters:**

**token** - Access or Refresh token that has to be revoked.

**Request Example**
```curl
curl -H "Content-Type: application/data" -X POST https://accounts.zoho.com/oauth/v2/token/revoke?token=1000.8ecdxxxxxxxxxxxxxxxxxxxxxxxx5cb7.4638xxxxxxxxxxxxxxxxxxxxxxxxebdc
```

### **6\. Calling an API**

The access Token can be passed only in the **header** and cannot be passed in the request param

-   Header name - Authorization
-   Header value - Zoho-oauthtoken {access\_token} **(Strictly follow this format.)**

**Request Example**
```curl
curl --request GET \ --url 'https://www.zohoapis.com/books/v3/invoices?organization_id=10234695' \ --header 'Authorization: Zoho-oauthtoken 1000.41d9xxxxxxxxxxxxxxxxxxxxxxxxc2d1.8fccxxxxxxxxxxxxxxxxxxxxxxxx125f'
```

### **Possible errors:**

**1\. If the OAuth token is not properly sent in the headers, unauthorized error may occur.**

**Solution:**

Make sure the format of Header value is correct as mentioned above

## Token Validity

### **Grant Token (Authorization code)**

**For Self Client:** - The grant token is a **one-time** use token and it is valid for **three** minutes, by default. If you want to extend its expiration time, choose the required time from the drop-down while generating the token from the API console.

**For Other Clients:** - The grant token is a **one-time** use token and it is valid for **two** minutes.

You can generate a maximum of **10 grant tokens** in a span of 10 minutes per client ID. If the limit is reached, "access\_denied" exception will be thrown for the remaining duration.

### **Access Token**

Each access token is valid for one hour.

A maximum of **15 active access tokens** can be stored per refresh token. When the 16th token is requested, the oldest token is invalidated. When an invalid access token is used, **"INVALID\_OAUTHTOKEN"** exception will be thrown.

You can generate a maximum of 10 access tokens from a refresh token in a span of **10 minutes**.

If the 10-minute throttle limit is reached, **"Access Denied"** error will be thrown. Re-use valid tokens to avoid this exception.

### **Refresh Token**

Refresh tokens do not expire until a user revokes them.

A maximum of **20 refresh tokens** can be stored per user.

When you generate the 21st refresh token, the oldest refresh token will become **invalid**.

## Multi DC support

To access information of the users from different regions you can use the Multi DC feature. If you want to use the Client ID created in one DC in other DCs, you need to enable Multi DC for that specific client ID from your developer console. To enable:

-   Open [Zoho Developer Console.](https://api-console.zoho.com/)
-   Select the required client.
-   Go to Settings and enable Multi DC

Once enabled, you will be able to make /oauth/v2/token call to the respective DC based on the user's location. (.com,.eu,.in, and other DCs).

To know the region to which a user belongs, check the response to your /oauth/v2/auth call. The response will look like:

\[redirect-url\]?code=1000.0fxxxxxxxxxxxxxxe5.cfffcfxxxxxxx89&location=eu&accounts-server=https://accounts.zoho.eu&

The location value and the accounts-server represents to the location where the user account resides.

If the user account is in the EU, the generated code will also be in EU only and not in other DCs. Therefore, the correct request would be **https://accounts.zoho.eu/oauth/v2/token**

You must use your domain-specific **Zoho Accounts URL** to generate grant token, access and refresh tokens, and to revoke tokens. The following are the various domains and their corresponding accounts URLs.

Data Center

Domain

Base API URI

United States

.com

https://www.zohoapis.com/billing/

Europe

.eu

https://www.zohoapis.eu/billing/

India

.in

https://www.zohoapis.in/billing/

Australia

.com.au

https://www.zohoapis.com.au/billing/

Japan

.jp

https://www.zohoapis.jp/billing/

Canada

.ca

https://www.zohoapis.ca/billing/

China

.com.cn

https://www.zohoapis.com.cn/billing/

Saudi Arabia

.sa

https://www.zohoapis.sa/billing/