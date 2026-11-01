"""CLI : python -m orchestra.gateway.tokens svc coordinateur | user chef-projet | admin"""
import os
import sys

from orchestra.gateway.auth import make_token

kind = sys.argv[1]
ident = sys.argv[2] if len(sys.argv) > 2 else "admin"
print(make_token(os.environ["ORCHESTRA_MASTER_KEY"], kind, ident))
