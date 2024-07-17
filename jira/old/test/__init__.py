import os
import sys

# Calculate the path based on the location of the __init__.py file
current_dir = os.path.dirname(__file__)
parent_dir = os.path.join(current_dir, '..')
src_dir = os.path.join(parent_dir, 'src')

# Add the 'src' directory to the Python path
sys.path.insert(0, os.path.abspath(src_dir))

