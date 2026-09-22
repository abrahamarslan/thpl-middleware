"""KYC & verification module — identity cycles, Aadhaar/PAN, BGV, medical, training.

    kyc_profiles              ENTITY   one row per KYC cycle (history)
    aadhaar_verifications     ENTITY   1:1 per cycle — ADV-isolated, never the raw number
    pan_verifications         ENTITY   1:1 per cycle — encrypted + masked
    liveness_verifications    ENTITY   selfie / liveness / face-match
    background_verifications  ENTITY   a BGV run (incl. police verification / PVC)
    bgv_check_results         ENTITY   normalized sub-checks of a run
    medical_fitness_certificates  ENTITY
    training_certifications   ENTITY
"""

from app.modules.kyc.model import (
    AadhaarVerification,
    BackgroundVerification,
    BGVCheckResult,
    KYCProfile,
    LivenessVerification,
    MedicalFitnessCertificate,
    PANVerification,
    TrainingCertification,
)

__all__ = [
    "AadhaarVerification",
    "BGVCheckResult",
    "BackgroundVerification",
    "KYCProfile",
    "LivenessVerification",
    "MedicalFitnessCertificate",
    "PANVerification",
    "TrainingCertification",
]
