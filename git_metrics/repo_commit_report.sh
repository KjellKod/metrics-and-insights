#!/bin/bash

#
#
# The purpose of this file is to be able to get all the commits for a specific date range for multiple repositories.
# The usage here is for example an audit or other oversight activity.
# The stored date is similar to: 
# git log master --since="YYYY-MM-DD" --until="YYYY-MM-DD" --first-parent --pretty=format:"%h,%an,%ad,%s" --date=iso --abbrev=7
# (abbrev7 gives the hash to be the same short length as the GitHub UI)

# Usage function
usage() {
    echo "Usage: $0 --start-date YYYY-MM-DD --end-date YYYY-MM-DD --repos 'owner1/repo1,owner2/repo2'"
    echo
    echo "Example:"
    echo "$0 --start-date 2024-10-15 --end-date 2025-01-15 --repos 'my_organization/web,my_organization/metrics'"
    exit 1
}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --start-date)
            START_DATE="$2"
            shift 2
            ;;
        --end-date)
            END_DATE="$2"
            shift 2
            ;;
        --repos)
            REPOS="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

# Validate required parameters
if [[ -z "$START_DATE" || -z "$END_DATE" || -z "$REPOS" ]]; then
    usage
fi

# Create output file with headers
SCRIPT_DIR="$PWD"
OUTPUT_FILE="$SCRIPT_DIR/commit_report.csv"
echo "repository,hash,author,date,message" > "$OUTPUT_FILE"

# Function to get commits for a specific branch
get_branch_commits() {
    local branch=$1
    echo "Attempting to get commits for branch: $branch"
    
    # Show current directory and list repo contents
    pwd | cat
    ls -la | cat
    
    # Show git status and branch info
    git status | cat
    git branch -a | cat
    
    # Try to fetch and check out the branch
    echo "Fetching branch $branch..."
    git fetch --quiet origin "$branch"
    echo "Checking out branch $branch..."
    git checkout -q "$branch" || git checkout -q "origin/$branch"
    
    # Show the exact command we're running
    echo "Running git log command..."
    GIT_CMD="git log $branch --since=\"$START_DATE\" --until=\"$END_DATE\" --first-parent --pretty=format:\"$REPO_TRIM,%h,%an,%ad,%s\" --date=iso --abbrev=7"
    echo "Command: $GIT_CMD"
    
    # Execute the command and capture output
    OUTPUT=$(eval "$GIT_CMD")
    echo "Command output:"
    
    # Append to file and check if successful
    if [ ! -z "$OUTPUT" ]; then
        echo "$OUTPUT" >> "$OUTPUT_FILE"
        COMMIT_COUNT=$(echo "$OUTPUT" | wc -l)
        echo "Successfully wrote $COMMIT_COUNT commits to file"
        return 0
    else
        echo "No output generated from git log command"
        return 1
    fi
}

# Process each repository
IFS=',' read -ra REPO_ARRAY <<< "$REPOS"
for REPO in "${REPO_ARRAY[@]}"; do
    REPO_TRIM=$(echo "$REPO" | xargs)  # Trim whitespace
    echo "Processing repository: $REPO_TRIM"
    
    # Use a fixed directory under /tmp
    TEMP_DIR="/tmp/${REPO_TRIM//\//_}"
    echo "Using directory: $TEMP_DIR"
    
    if [ ! -d "$TEMP_DIR" ]; then
        echo "Directory doesn't exist, cloning repository..."
        mkdir -p "$TEMP_DIR"
        git clone --quiet "git@github.com:$REPO_TRIM.git" "$TEMP_DIR"
        if [ $? -ne 0 ]; then
            echo "Error: Failed to clone $REPO_TRIM"
            echo "$REPO_TRIM,ERROR,ERROR,ERROR,Failed to clone repository" >> "$OUTPUT_FILE" 
            continue
        fi
    else
        echo "Directory exists, updating repository..."
        cd "$TEMP_DIR"
        git fetch --all --quiet
        cd - > /dev/null
    fi
    
    cd "$TEMP_DIR"
    
    # Try master first, then main if master fails
    if ! get_branch_commits "master"; then
        echo "master branch failed, trying main..."
        if ! get_branch_commits "main"; then
            echo "Error: Neither master nor main branch worked for $REPO_TRIM"
            echo "$REPO_TRIM,ERROR,ERROR,ERROR,No commits found in specified date range" >> "$OUTPUT_FILE"
        fi
    fi
    
    cd - > /dev/null
done

echo "Report generated: $OUTPUT_FILE"
echo "=== Summary ==="
TOTAL_REPOS=$(cat "$OUTPUT_FILE" | grep -v "^repository" | cut -d',' -f1 | sort -u | wc -l)
ERROR_REPOS=$(cat "$OUTPUT_FILE" | grep "ERROR" | cut -d',' -f1 | sort -u | wc -l)
SUCCESS_REPOS=$((TOTAL_REPOS - ERROR_REPOS))
echo "Report generated: $OUTPUT_FILE"
echo "Total unique repositories processed: $TOTAL_REPOS"
echo "Successful: $SUCCESS_REPOS"
echo "Errors: $ERROR_REPOS"