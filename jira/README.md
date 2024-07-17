install the jiradoodles package in edit mode will fix unit test issues
=====================
pip install -e .

run unit test
============
python3 -m unittest discover -s test




jira_metrics/
│
├── bin/                    # Directory for executable scripts
│   ├── extract_metadata.py
│   ├── extract_performance.py
│   └── ...
│
├── jira_metrics/           # Main package directory
│   ├── __init__.py         # Makes jira_metrics a Python package
│   ├── config.py           # Configuration settings and constants
│   ├── utilities/          # Utility modules
│   │   ├── __init__.py
│   │   ├── time_utils.py
│   │   ├── io_utils.py
│   │   ├── json_utils.py
│   │   ├── jira_query.py
│   │   └── ...
│   ├── metrics/            # Modules for specific metrics extraction
│   │   ├── __init__.py

│   │   ├── sprint_metadata.py
│   │   ├── performance_metrics.py
│   │   └── ...
│   └── data/               # For storing local data files, if necessary
│
├── tests/                  # Test suite
│   ├── __init__.py
│   ├── test_time_utils.py
│   ├── test_io_utils.py
│   ├── test_json_utils.py
│   ├── test_jira_query.py
│   └── ...
│
├── .gitignore              # Specifies intentionally untracked files to ignore
├── requirements.txt        # Fixed versions of dependencies
└── README.md               # Project overview and setup instructions


Key Components
bin/: This directory contains executable scripts that users can run. Each script uses functionalities from the jira_metrics package. These scripts are the entry points for different tasks like extracting metadata or performance metrics.
jira_metrics/: The main package containing all the modular code.
config.py: Central configuration file for managing constants like API keys, URLs, etc.
utilities/: Utility modules that provide common functionalities like handling time and dates, I/O operations, and Jira queries.
metrics/: Modules dedicated to extracting specific metrics from Jira.
tests/: Contains all unit tests. Each utility and metrics module should have corresponding test modules here.

Development Practices
Modularity: Keep the code modular. Each utility should have a single responsibility and should be independent as much as possible.
Testing: Aim for high test coverage. Mock external dependencies like Jira API responses.
Documentation: Each module, class, and method should have clear docstrings explaining what it does. The README should provide clear setup and usage instructions.
Version Control: Use Git for version control. Include a .gitignore file to exclude unnecessary files (like __pycache__).

Setup Files
init_.py: Necessary in each directory that you want to treat as a Python package. This can be empty or can include package imports.
requirements.txt: List all the dependencies with versions that are known to work with your application.
This structure should provide a solid foundation for building and scaling your Jira metrics extraction tool while keeping the code organized and maintainable.
