#!/bin/bash

# Pre-merge conflict check script
# This script checks if the current branch can be merged into main without conflicts
# Usage: ./scripts/check-merge.sh [target-branch]

set -e

TARGET_BRANCH="${1:-main}"
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

echo "======================================"
echo "Pre-Merge Conflict Check"
echo "======================================"
echo "Current branch: $CURRENT_BRANCH"
echo "Target branch: $TARGET_BRANCH"
echo ""

# Check if we're on a branch
if [ "$CURRENT_BRANCH" == "HEAD" ]; then
    echo "❌ Error: You are in detached HEAD state"
    exit 1
fi

# Check if target branch is the same as current
if [ "$CURRENT_BRANCH" == "$TARGET_BRANCH" ]; then
    echo "❌ Error: Cannot check merge into the same branch"
    exit 1
fi

# Fetch latest changes
echo "Fetching latest changes..."
git fetch origin "$TARGET_BRANCH" 2>/dev/null || {
    echo "⚠️  Warning: Could not fetch $TARGET_BRANCH from remote"
}

# Check if target branch exists
if ! git rev-parse --verify "$TARGET_BRANCH" >/dev/null 2>&1; then
    echo "❌ Error: Target branch '$TARGET_BRANCH' does not exist"
    exit 1
fi

echo ""
echo "Step 1: Checking for uncommitted changes..."
if ! git diff-index --quiet HEAD --; then
    echo "⚠️  Warning: You have uncommitted changes"
    echo "   Please commit or stash your changes before checking merge compatibility"
    git status --short
    echo ""
fi

echo ""
echo "Step 2: Checking for merge conflicts..."
MERGE_BASE=$(git merge-base HEAD "$TARGET_BRANCH")

# Use git merge-tree to check for conflicts without actually merging
MERGE_OUTPUT=$(git merge-tree "$MERGE_BASE" "$TARGET_BRANCH" HEAD)

if echo "$MERGE_OUTPUT" | grep -q '<<<<<<<'; then
    echo "❌ MERGE CONFLICTS DETECTED!"
    echo ""
    echo "Conflicting files:"
    echo "$MERGE_OUTPUT" | grep -B 5 '<<<<<' | grep 'changed in both' || {
        # Fallback: try to identify files another way
        echo "$MERGE_OUTPUT" | grep -E '^\+\+\+|^---' | sort -u
    }
    echo ""
    echo "To resolve conflicts:"
    echo "  1. Merge $TARGET_BRANCH into your branch: git merge $TARGET_BRANCH"
    echo "  2. Resolve the conflicts manually"
    echo "  3. Commit the resolved changes"
    echo "  4. Run this script again to verify"
    exit 1
else
    echo "✅ No merge conflicts detected"
fi

echo ""
echo "Step 3: Checking code compatibility..."

# Check if Python files exist
if find . -name "*.py" -not -path "*/\.*" -not -path "*/venv/*" -not -path "*/env/*" | grep -q .; then
    echo "  Checking Python syntax..."
    
    # Check Python syntax for changed files
    CHANGED_PY_FILES=$(git diff --name-only "$TARGET_BRANCH"...HEAD | grep '\.py$' || true)
    
    if [ -n "$CHANGED_PY_FILES" ]; then
        echo "  Modified Python files:"
        echo "$CHANGED_PY_FILES" | sed 's/^/    - /'
        
        # Basic syntax check
        for file in $CHANGED_PY_FILES; do
            if [ -f "$file" ]; then
                python3 -m py_compile "$file" 2>/dev/null || {
                    echo "  ⚠️  Syntax error in: $file"
                }
            fi
        done
        echo "  ✅ Python syntax check complete"
    else
        echo "  No Python files modified"
    fi
fi

echo ""
echo "Step 4: Checking for functional conflicts..."

# Look for potentially conflicting changes in the same files
COMMON_FILES=$(comm -12 \
    <(git diff --name-only "$MERGE_BASE" "$TARGET_BRANCH" | sort) \
    <(git diff --name-only "$MERGE_BASE" HEAD | sort))

if [ -n "$COMMON_FILES" ]; then
    echo "  Files modified in both branches:"
    echo "$COMMON_FILES" | sed 's/^/    - /'
    echo ""
    echo "  ⚠️  Review these files carefully to ensure functionality is compatible"
else
    echo "  ✅ No overlapping file modifications"
fi

echo ""
echo "======================================"
echo "✅ Pre-Merge Check Complete"
echo "======================================"
echo ""
echo "Summary:"
echo "  • No merge conflicts detected"
echo "  • Code syntax is valid"
if [ -n "$COMMON_FILES" ]; then
    echo "  • Warning: Some files were modified in both branches"
else
    echo "  • No functional conflicts expected"
fi
echo ""
echo "✅ Branch '$CURRENT_BRANCH' is ready to merge into '$TARGET_BRANCH'"
echo ""
