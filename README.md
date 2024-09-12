```
├── github/               # Scripts for extracting metrics from GitHub
│   ├── releases.py
│
├── jira/                 # Scripts for extracting metrics from Jira
│   ├── engineering_excellence.py
│   ├── cycle_time.py
│   ├── release_failure.py
│   ├── released_tickets.py
│
├── tests/                # Test suite
│   ├── __init__.py       
│   ├── test_engineering_excellence.py
| 
├── .gitignore            # to ignore
├── requirements.txt      # dependencies
└── README.md             # overview
```



## Key Components##
*github/*
Scripts for extracting metrics from GitHub based on the release tags 
- releases.py: Script to retrieve and categorize GitHub releases by year and month.

*jira/*
Scripts for extracting metrics from Jira.

- engineering_excellence.py: Script to extract engineering excellence metrics from Jira. It shows for each team and month the product focus, engineering excellence focus (debt reductino, critical work) and the annual average SO FAR of ee
- cycle_time.py: Script to calculate cycle time metrics from Jira, based on when coding is finished until it's marked as released. 
- release_failure.py: Script extract all `Release` tickets, the linked tickets part of that release and whether or not the release was a failure. 
- released_tickets.py: Retrieve calculate amount of released tickets month-by-month.
- Setup and Usage

## Environmental Variables## 
Some scripts require environmental variables to be set.You can set these in your .zshrc or .bashrc file:

```
export USER_EMAIL="your_email@example.com"
xport JIRA_API_KEY="your_jira_api_key"
export JIRA_LINK="https://your_jira_instance.atlassian.net"
export GITHUB_TOKEN_READONLY_WEB="your_github_token"
export GITHUB_METRIC_OWNER="your_github_repo_owner"
export GITHUB_METRIC_REPO="your_github_repo_name"
export JIRA_PROJECTS="MYPROJECT, ENG, ETC"
export TEAM_ONE="first_team" 
# -- used for when the `team` field isn't defined for a `ONE` project
# example export TEAM_INT="mint"
```


## Example Usage ##
Extracting GitHub Releases
To retrieve and categorize GitHub releases, ensure your environmental variables are set and run:

`python3 github/releases.py`



## Tests ## 
In each functionality directory, if it has a test directory you can run all of the tests like this 
`python3 -m unittest discover -s tests -p "*.py"`

Or more verbose with `-v` flag. You can also specify the individual file. 
`python3 -m unittest discover -v -s tests -p test_engineering_excellence.py`