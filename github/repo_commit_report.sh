#!/bin/bash

# Usage function
usage() {
    echo "Usage: $0 --start-date YYYY-MM-DD --end-date YYYY-MM-DD --repos 'owner1/repo1,owner2/repo2'"
    echo
    echo "Example:"
    echo "$0 --start-date 2024-10-15 --end-date 2025-01-15 --repos 'onfleet/web,onfleet/mobile'"
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
OUTPUT_FILE="commit_report.csv"
echo "repository,hash,author,date,message" > "$OUTPUT_FILE"

# Function to get commits for a specific branch
get_branch_commits() {
    local branch=$1
    if git fetch --quiet origin "$branch" 2>/dev/null; then
        echo "Using branch: $branch"
        git log "origin/$branch" --since="$START_DATE" --until="$END_DATE" --first-parent \
            --pretty=format:"$REPO_TRIM,%h,%an,%ad,%s" --date=iso --abbrev=7 >> "../$OUTPUT_FILE"
        return 0
    fi
    return 1
}

# Process each repository
IFS=',' read -ra REPO_ARRAY <<< "$REPOS"
for REPO in "${REPO_ARRAY[@]}"; do
    REPO_TRIM=$(echo "$REPO" | xargs)  # Trim whitespace
    
    # Create temp directory for repo
    TEMP_DIR=$(mktemp -d)
    echo "Processing repository: $REPO_TRIM"
    
    # Clone repository (depth 1 for speed, we'll fetch more as needed)
    git clone --quiet "git@github.com:$REPO_TRIM.git" "$TEMP_DIR"
    
    if [ $? -eq 0 ]; then
        cd "$TEMP_DIR"
        
        # Try master first, then main if master fails
        if ! get_branch_commits "master"; then
            echo "master branch not found, trying main..."
            if ! get_branch_commits "main"; then
                echo "Error: Neither master nor main branch found in $REPO_TRIM"
                echo "$REPO_TRIM,ERROR,ERROR,ERROR,No master or main branch found" >> "../$OUTPUT_FILE"
            fi
        fi
        
        cd ..
        rm -rf "$TEMP_DIR"
        echo "Completed processing $REPO_TRIM"
    else
        echo "Error: Failed to clone $REPO_TRIM"
        echo "$REPO_TRIM,ERROR,ERROR,ERROR,Failed to clone repository" >> "$OUTPUT_FILE"
    fi
done

echo "Report generated: $OUTPUT_FILE"