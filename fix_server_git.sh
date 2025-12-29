#!/bin/bash
# Fix Git branch issues on DigitalOcean server
# Run this on your server: bash fix_server_git.sh

set -e

echo "=== Fixing Git Branch Configuration ==="
echo ""

cd /root/ceefax_station_website

# Check if it's a git repository
if [ ! -d .git ]; then
    echo "ERROR: Not a git repository!"
    echo "Re-cloning repository..."
    cd /root
    rm -rf ceefax_station_website
    git clone https://github.com/thaum-labs/ceefax_station_website.git
    cd ceefax_station_website
    echo "Repository cloned successfully."
else
    echo "Git repository found."
fi

echo ""
echo "Current branch status:"
git branch -a

echo ""
echo "Fetching latest from origin..."
git fetch origin --prune

echo ""
echo "Checking out main branch..."
# Try to checkout main, create it if it doesn't exist
if git show-ref --verify --quiet refs/heads/main; then
    echo "Local main branch exists, checking it out..."
    git checkout main
else
    echo "Local main branch doesn't exist, creating from origin/main..."
    git checkout -b main origin/main
fi

echo ""
echo "Setting up branch tracking..."
git branch --set-upstream-to=origin/main main || {
    echo "Setting upstream failed, trying alternative method..."
    git config branch.main.remote origin
    git config branch.main.merge refs/heads/main
}

echo ""
echo "Pulling latest changes..."
git pull

echo ""
echo "Cleaning up any stale references..."
git remote prune origin
git branch -D index.html 2>/dev/null || true

echo ""
echo "=== Fix Complete ==="
echo ""
echo "Current status:"
git status
echo ""
echo "Branches:"
git branch -vv

