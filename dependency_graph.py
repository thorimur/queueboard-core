#!/usr/bin/env python3

"""
Build dependency graphs from PR data and create D3.js visualizations.

This script reads the processed data and builds a dependency graph showing
which PRs depend on which other PRs, outputting in D3.js compatible format.
"""

import json
import sys
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class PRNode:
    """Represents a PR node in the dependency graph."""
    number: int
    title: str
    author: str
    state: str  # "open" or "closed"
    is_draft: bool
    depends_on: List[int]
    depended_on_by: List[int]
    labels: List[str]
    url: str
    additions: int
    deletions: int


class DependencyGraph:
    """Builds and analyzes PR dependency graphs."""
    
    def __init__(self, pr_data_file: str = "processed_data/open_pr_data.json"):
        """Initialize the dependency graph from PR data."""
        self.nodes: Dict[int, PRNode] = {}
        self.load_data(pr_data_file)
        self.build_reverse_dependencies()
    
    def load_data(self, data_file: str) -> None:
        """Load PR data from JSON file."""
        try:
            with open(data_file, 'r') as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"Error: Could not find data file {data_file}")
            print("Please run process.py first to generate the data.")
            sys.exit(1)
        
        # First pass: collect all PR numbers in the dataset
        available_prs = set(pr["number"] for pr in data["pr_statusses"])
        
        # Second pass: create nodes with filtered dependencies
        for pr in data["pr_statusses"]:
            pr_url = f"https://github.com/leanprover-community/mathlib4/pull/{pr['number']}"
            
            # Filter dependencies to only include PRs that are still open
            open_dependencies = [dep for dep in pr.get("depends_on", []) if dep in available_prs]
            
            node = PRNode(
                number=pr["number"],
                title=pr["title"],
                author=pr["author"],
                state=pr["state"],
                is_draft=pr["is_draft"],
                depends_on=open_dependencies,
                depended_on_by=[],
                labels=pr["label_names"],
                url=pr_url,
                additions=pr.get("additions", 0),
                deletions=pr.get("deletions", 0)
            )
            self.nodes[pr["number"]] = node
    
    def build_reverse_dependencies(self) -> None:
        """Build reverse dependency links (which PRs depend on this one)."""
        for pr_num, node in self.nodes.items():
            for dep_pr in node.depends_on:
                if dep_pr in self.nodes:
                    self.nodes[dep_pr].depended_on_by.append(pr_num)
    
    def to_d3_format(self) -> Dict:
        """Convert the dependency graph to D3.js compatible format."""
        nodes = []
        links = []
        
        for pr_num, node in self.nodes.items():
            nodes.append({
                "id": pr_num,
                "title": node.title,
                "author": node.author,
                "state": node.state,
                "is_draft": node.is_draft,
                "labels": node.labels,
                "url": node.url,
                "dependency_count": len(node.depends_on),
                "dependent_count": len(node.depended_on_by),
                "additions": node.additions,
                "deletions": node.deletions
            })
        
        for pr_num, node in self.nodes.items():
            for dep_pr in node.depends_on:
                if dep_pr in self.nodes:
                    links.append({
                        "source": pr_num,
                        "target": dep_pr,
                        "source_state": node.state,
                        "target_state": self.nodes[dep_pr].state
                    })
        
        return {
            "nodes": nodes,
            "links": links,
            "metadata": {
                "total_prs": len(self.nodes),
                "prs_with_dependencies": len([n for n in self.nodes.values() if n.depends_on]),
                "prs_that_are_dependencies": len([n for n in self.nodes.values() if n.depended_on_by]),
                "dependency_links": len(links)
            }
        }
    
    def print_statistics(self) -> None:
        """Print basic statistics about the dependency graph."""
        total_prs = len(self.nodes)
        prs_with_deps = len([n for n in self.nodes.values() if n.depends_on])
        prs_as_deps = len([n for n in self.nodes.values() if n.depended_on_by])
        
        print("=== Dependency Graph Statistics ===")
        print(f"Total PRs: {total_prs}")
        print(f"PRs with dependencies: {prs_with_deps}")
        print(f"PRs that are dependencies: {prs_as_deps}")
        
        if prs_with_deps > 0:
            example_deps = [(pr_num, len(node.depends_on)) for pr_num, node in self.nodes.items() if node.depends_on]
            example_deps.sort(key=lambda x: x[1], reverse=True)
            print(f"Example PRs with dependencies:")
            for pr_num, dep_count in example_deps[:3]:
                node = self.nodes[pr_num]
                print(f"  PR #{pr_num}: {dep_count} dependencies - {node.title[:60]}...")


def main():
    """Main function to build and analyze dependency graphs."""
    if len(sys.argv) > 1 and sys.argv[1] == "--help":
        print("Usage: python dependency_graph.py [--stats] [--d3] [--output FILE]")
        print("  --stats: Print statistics about the dependency graph")
        print("  --d3: Output D3.js compatible JSON format")
        print("  --output FILE: Save output to specified file")
        return
    
    graph = DependencyGraph()
    
    show_stats = "--stats" in sys.argv
    output_d3 = "--d3" in sys.argv
    output_file = None
    
    if "--output" in sys.argv:
        try:
            output_idx = sys.argv.index("--output")
            output_file = sys.argv[output_idx + 1]
        except (IndexError, ValueError):
            print("Error: --output requires a filename")
            sys.exit(1)
    
    if show_stats or len(sys.argv) == 1:
        graph.print_statistics()
    
    if output_d3:
        d3_data = graph.to_d3_format()
        if output_file:
            with open(output_file, 'w') as f:
                json.dump(d3_data, f, indent=2)
            print(f"D3.js data saved to {output_file}")
        else:
            print(json.dumps(d3_data, indent=2))


if __name__ == "__main__":
    main() 