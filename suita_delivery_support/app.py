# Compatible with the old local start command: python suita_delivery_support/app.py
if __package__ in (None,''):
    import sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from suita_delivery_support.server import app,main
if __name__=='__main__':main()
