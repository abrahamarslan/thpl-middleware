"""HR / employment module — employment history, gig-worker statutory, payouts.

    employment_records        ENTITY   one stint per row; is_current marks active
    gig_worker_registrations  ENTITY   1:1 Code on Social Security / e-Shram
    gig_worker_fy_stats       ENTITY   per-(worker, financial year) accrual
    bank_accounts             ENTITY   payee-polymorphic payout accounts
"""

from app.modules.hr.model import (
    BankAccount,
    EmploymentRecord,
    GigWorkerFYStats,
    GigWorkerRegistration,
)

__all__ = [
    "BankAccount",
    "EmploymentRecord",
    "GigWorkerFYStats",
    "GigWorkerRegistration",
]
