"""Vehicle module — fleet master, MVA compliance set, driving licenses.

    vehicles                     ENTITY   the physical vehicle
    vehicle_compliance_documents ENTITY   per-certificate renewal chain
    driving_licenses             ENTITY   one row per DL version (is_current)
"""

from app.modules.vehicles.model import DrivingLicense, Vehicle, VehicleComplianceDocument

__all__ = ["DrivingLicense", "Vehicle", "VehicleComplianceDocument"]
