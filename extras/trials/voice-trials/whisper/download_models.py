import common  # sets HF_HOME inside this folder
from common import model_path, log

for name in ("large-v3", "medium"):
    p = model_path(name)
    log(name, "->", p)
