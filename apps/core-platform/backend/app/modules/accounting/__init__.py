"""Accounting — the chart of accounts, account assignments, and (later) the general ledger.

    accounting.account_types             GLOBAL  46-code type vocabulary (Zoho docs ∪ tenant response)
    accounting.accounts                  ENTITY  one ledger account of one organization (Zoho crosswalk)
    accounting.account_purposes          GLOBAL  why an entity points at an account
    accounting.account_purpose_policies  GLOBAL  which classes may carry which purposes
    accounting.account_assignments       ENTITY  polymorphic owner → account, per purpose

An entity carries accounts with ``HasAccountsMixin`` + ``registration.register_account_owner_type``
(its own migration); "which account applies?" is the resolution engine's facet ``account``
(``resolution.py``). Docs: docs/implementation-plan/accounts-module.md.
"""
