import os

NEO4J_URI = os.environ.get("NEO4J_URI", "bolt://localhost:17687")
ADMIN_USER = "admin"
ADMIN_PASSWORD = os.environ.get("NEO4J_ADMIN_PASSWORD", "admin-dev-pw")
GATEWAY_USER = "gateway"
GATEWAY_PASSWORD = os.environ.get("NEO4J_GATEWAY_PASSWORD", "gateway-dev-pw")
CDC_USER = "cdc"
CDC_PASSWORD = os.environ.get("NEO4J_CDC_PASSWORD", "cdc-dev-pw")
KGCURATOR_USER = "kgcurator"
KGCURATOR_PASSWORD = os.environ.get("NEO4J_KGCURATOR_PASSWORD", "kgcurator-dev-pw")
