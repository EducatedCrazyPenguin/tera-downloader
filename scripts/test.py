"""Run offline unittest discovery with the repository's source/test paths."""
from pathlib import Path
import os
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'src'),str(root/'tests')]
os.chdir(root)
unittest.main(module=None,argv=[sys.argv[0],'discover','-s',str(root/'tests'),*sys.argv[1:]])
