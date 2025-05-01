#!/usr/bin/env python3

"""
Code to suggest a reviewer for a given pull request, based on their self-indicated areas of competence/interest.
This may take the current number of pull requests assigned to each reviewer into account.

"""

import json
import sys
from typing import List, NamedTuple, Tuple

from dashboard import (
    AggregatePRInfo,
    user_link,
)

class ReviewerInfo(NamedTuple):
    github: str
    zulip: str
    # List of top-level areas a reviewer is interested in.
    # Most (but not all) of these are t-something labels in mathlib.
    top_level: List[str]
    comment: str


def read_reviewer_info() -> List[ReviewerInfo]:
    # Future: download the raw file from this link, instead of reading a local copy!
    # (This requires fixing the upstream version first: locally, it is easy to just correct the bugs.)
    # And the file should live on a more stable branch (master?), or the webpage?
    _file_url = "https://raw.githubusercontent.com/leanprover-community/mathlib4/refs/heads/reviewer-topics/docs/reviewer-topics.json"
    with open("reviewer-topics.json", "r") as fi:
        reviewer_topics = json.load(fi)
    return [
        ReviewerInfo(entry["github_handle"], entry["zulip_handle"], entry["top_level"], entry["free_form"])
        for entry in reviewer_topics
    ]


# Suggest potential reviewers for a single pull request with given number.
# We return a tuple (full code, reviewers) with information about all potential reviewers.
# The first component is the full HTML code for the purposes of a webpage table entry, containing all suggested reviewers;
# the second one contains all potential reviewers suggested (by their github handle).
# The returned suggestions are ranked; less busy reviewers come first.
def suggest_reviewers(
    existing_assignments: dict[str, Tuple[List[int], int]], reviewers: List[ReviewerInfo], number: int, info: AggregatePRInfo
) -> Tuple[str, List[str]]:
    # Look at all topic labels of this PR, and find all suitable reviewers.
    topic_labels = [lab.name for lab in info.labels if lab.name.startswith("t-") or lab.name in ["CI", "IMO"]]
    # Each reviewer, together with the list of top-level areas
    # relevant to this PR in which this reviewer is competent.
    matching_reviewers: List[Tuple[ReviewerInfo, List[str]]] = []
    if topic_labels:
        for rev in reviewers:
            reviewer_lab = rev.top_level
            if "t-metaprogramming" in reviewer_lab:
                reviewer_lab.remove("t-metaprogramming")
                reviewer_lab.append("t-meta")
            match = [lab for lab in topic_labels if lab in reviewer_lab]
            # Do not propose a PR's author as potential reviewer.
            if rev.github != info.author:
              matching_reviewers.append((rev, match))
    else:
        print(f"PR {number} has no topic labels: reviewer suggestions not implemented yet", file=sys.stderr)
        return ("no topic labels: suggestions not implemented yet", [])

    # Future: decide how to customise and filter the output, lots of possibilities!
    # - no and one reviewer look sensible already
    #   (should one show their full interests also? would that be interesting?)
    # - don't suggest more than five reviewers --- but make clear there was a selection
    #   perhaps: have two columns "all matching reviewers" and "suggested one(s)" with up to three?
    # - would showing the full interests (not just the top-level areas) be helpful?
    if not matching_reviewers:
        print(f"found no reviewers with matching interest for PR {number}", file=sys.stderr)
        return ("found no reviewers with matching interest", [])
    elif len(matching_reviewers) == 1:
        handle = matching_reviewers[0][0].github
        return (f"{user_link(handle)}", [handle])
    else:
        max_score = max([len(areas) for (_, areas) in matching_reviewers])
        if max_score > 1:
            # If there are several areas, prefer reviewers which match the highest number of them.
            proposed_reviewers = [(rev, areas) for (rev, areas) in matching_reviewers if len(areas) == max_score]
        else:
            proposed_reviewers = [(rev, areas) for (rev, areas) in matching_reviewers if len(areas) > 0]

        # Sort these reviewers according to how busy they are, by their current number of assignments.
        # (Not every reviewer has had an assignment so far, so we need to use a fall-back value.)
        with_curr_assignments = [
            (rev, areas, len(existing_assignments[rev.github][0]) if rev.github in existing_assignments else 0)
                for (rev, areas) in proposed_reviewers
        ]
        with_curr_assignments = sorted(with_curr_assignments, key=lambda s: s[2])
        # FIXME: refine which information is actually useful here.
        # Or also show information if a single (and the PR's only) area matches?
        formatted = ", ".join([
            user_link(rev.github, f"relevant area(s) of competence: {', '.join(areas)}{f'; comments: {rev.comment}' if rev.comment else ''}; {n} recent open PR(s) currently assigned")
            for (rev, areas, n) in with_curr_assignments
        ])
        suggested_reviewers = [rev.github for (rev, _areas, _n) in with_curr_assignments]
        return (formatted, suggested_reviewers)