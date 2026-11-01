import logging

from orchestra.runtime.service import run_all
from orchestra.runtime.settings import RuntimeSettings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
run_all(RuntimeSettings.from_env())
