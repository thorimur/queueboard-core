#!/usr/bin/env python3
"""
Merge paginated timeline items from GitHub CLI --paginate output.
Takes concatenated JSON objects on stdin and combines timelineItems.nodes arrays.
"""

import json
import sys

def merge_timeline_items():
    # Read all input
    data = sys.stdin.read().strip()
    if not data:
        return
    
    # Split concatenated JSON objects on }{ pattern
    parts = data.split('}{')
    if len(parts) == 1:
        # Only one JSON object, just output it
        print(data)
        return
    
    # Reconstruct individual JSON objects
    parts[0] += '}'
    for i in range(1, len(parts) - 1):
        parts[i] = '{' + parts[i] + '}'
    parts[-1] = '{' + parts[-1]
    
    all_timeline_nodes = []
    base_data = None
    
    for part in parts:
        try:
            obj = json.loads(part)
            timeline_items = obj["data"]["repository"]["pullRequest"]["timelineItems"]
            
            # Collect all timeline nodes
            all_timeline_nodes.extend(timeline_items["nodes"])
            
            # Keep the first complete object as our base
            if base_data is None:
                base_data = obj
                
        except (json.JSONDecodeError, KeyError):
            continue
    
    if base_data:
        # Replace the timeline nodes with merged data
        base_data["data"]["repository"]["pullRequest"]["timelineItems"]["nodes"] = all_timeline_nodes
        base_data["data"]["repository"]["pullRequest"]["timelineItems"]["pageInfo"]["hasNextPage"] = False
        
        print(json.dumps(base_data))

if __name__ == "__main__":
    merge_timeline_items() 