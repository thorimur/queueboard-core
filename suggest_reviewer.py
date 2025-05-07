#!/usr/bin/env python3

"""
Code to suggest a reviewer for a given pull request, based on their self-indicated areas of competence/interest.
This may take the current number of pull requests assigned to each reviewer into account.

"""

import json
import sys
from typing import List, NamedTuple, Tuple
from classify_pr_state import PRState, PRStatus, LabelKind, determine_PR_status, label_categorisation_rules
from compute_dashboard_prs import LastStatusChange, DataStatus

from datetime import datetime
from os import path

from dateutil import parser, tz

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


class AssignmentStatistics(NamedTuple):
    timestamp: datetime
    # The number of all open PRs
    num_open: int
    # All PRs which are open and assigned to somebody. This list has no duplicates
    assigned_open: List[int]
    # The number of PRs with multiple assignees.
    number_multiple_assignees: int
    # Collating all assigned PRs: map each user's github handle to a tuple
    # (numbers, n_open, n_open_weighted, n_all), where
    # - numbers is a list of *open* PRs assigned to this user, n_open the number of these,
    # - n_open_weighted counts these PRs with some *weight* applied: PRs on the queue or with just
    #   a merge conflict get full weight, PRs waiting on the author (or zulip) get weight ...
    #   and blocked PRs do not get counted at all,
    # - n_all is the number of all PRs ever assigned to this user
    # Note that a PR assigned to several users is counted multiple times, once per assignee.
    assignments: dict[str, Tuple[List[int], float, int]]


# Compute the weight of a pull request for the purposes of counting reviewer assignments.
# A pull request has weight 1 if it is on the review queue or just has a merge conflict,
# if it is waiting on the PR author or zulip, it has weight 1/(t+t)
# (where t is the number of days since the PR was last on the queue),
# blocked PRs get weight 0.
def _compute_weight(pr: int, data: AggregatePRInfo) -> float:
    # We don't use data.last_status_change as that is None for stubborn PRs
    # (whereas we still classify them using labels and CI data).
    labels: List[LabelKind] = [label_categorisation_rules[lab.name] for lab in data.labels if lab.name in label_categorisation_rules]
    state = PRState(labels, data.CI_status, data.is_draft, data.head_repo != 'leanprover-community')
    status: PRStatus = determine_PR_status(datetime(2025, 1, 1, tzinfo=tz.tzutc()), state)
    match status:
        case PRStatus.AwaitingReview | PRStatus.MergeConflict:
            return 1.0
        case PRStatus.Blocked:
            return 0
        case PRStatus.AwaitingAuthor | PRStatus.AwaitingDecision:
            match data.last_status_change:
                case None:
                    print(f"info: PR {pr} has no last status update, assigning placehold weight 0.1")
                    return 0.1
                case LastStatusChange(DataStatus.Missing, _, _, _) | LastStatusChange(DataStatus.Incomplete, _, _, _):
                    print(f"info: PR {pr} has incomplete or missing last update status information, assigning weight 0.1")
                    return 0.1
                case LastStatusChange(DataStatus.Valid, _, delta, current):
                    assert current in [PRStatus.AwaitingAuthor, PRStatus.AwaitingDecision]
                    # Future: do I want to refine this weight function?
                    return 1 / (delta.days + 1)
        case PRStatus.Delegated | PRStatus.AwaitingBors:
            return 0
        case PRStatus.Closed | PRStatus.Contradictory | PRStatus.NotReady | PRStatus.FromFork:
            return 0
        case PRStatus.HelpWanted:
            return 0  # arguably also fine
        case _:
            # The above list should be complete!
            assert False
    return 0  # unreachable in practice


# Compute a weighted sum of all PRs with number in |prs|.
# A pull request has weight 1 if it is on the review queue or just has a merge conflict,
# if it is waiting on the PR author or zulip, it has weight 1/(t+t)
# (where t is the number of days since the PR was last on the queue),
# blocked PRs get weight 0.
def _compute_assignment_weight(prs : List[int], all_aggregate_info: dict[int, AggregatePRInfo]) -> float:
    return sum([_compute_weight(pr, all_aggregate_info[pr]) for pr in prs])


def collect_assignment_statistics(all_aggregate_info: dict[int, AggregatePRInfo]) -> AssignmentStatistics:
    with open(path.join("processed_data", "assignment_data.json"), "r") as fi:
        assignment_data = json.load(fi)
    time = parser.isoparse(assignment_data["timestamp"])
    num_open = assignment_data["number_open_prs"]
    assignments = assignment_data["all_assignments"]
    numbers: dict[str, Tuple[List[int], float, int]] = {}
    assigned_open_prs = []
    for reviewer, data in assignments.items():
        open_assigned = sorted([entry["number"] for entry in data if entry["state"] == "open"])
        numbers[reviewer] = (open_assigned, _compute_assignment_weight(open_assigned, all_aggregate_info), len(data))
        assigned_open_prs.extend(open_assigned)
    num_multiple_assignees = len(assigned_open_prs) - len(set(assigned_open_prs))
    assert assignment_data["number_open_assigned"] == len(list(set(assigned_open_prs)))
    return AssignmentStatistics(
        time, num_open, sorted(list(set(assigned_open_prs))), num_multiple_assignees, numbers
    )


class ReviewerSuggestion(NamedTuple):
    # full HTML code for the purposes of a webpage table entry, containing all suggested reviewers
    code: str
    # All potential reviewers suggested (by their github handle),
    # including reviewers who are at their maximum review capacity or not on the review rotation.
    # The returned suggestions are ranked; less busy reviewers come first.
    all_potential_reviewers: List[str]
    # All reviewers among |all_potential_reviewers| who are on the review rotation
    # and whose review capacity is not yet exceeded
    all_available_reviewers: List[str]
    # One reviewer among |all_available_reviewers|, randomly chosen (according to remaining review capacity)
    suggested: str | None

# Suggest potential reviewers for a single pull request with given number.
# We return all reviewers whose top-level interest have the best possible match
# for this PR.
def suggest_reviewers(
    existing_assignments: dict[str, Tuple[List[int], float, int]], reviewers: List[ReviewerInfo], number: int, info: AggregatePRInfo,
    all_info: dict[int, AggregatePRInfo]  # aggregate information about all PRs
) -> ReviewerSuggestion:
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
        return ReviewerSuggestion("no topic labels: suggestions not implemented yet", [], [], None)

    # Future: decide how to customise and filter the output, lots of possibilities!
    # - no and one reviewer look sensible already
    #   (should one show their full interests also? would that be interesting?)
    # - don't suggest more than five reviewers --- but make clear there was a selection
    #   perhaps: have two columns "all matching reviewers" and "suggested one(s)" with up to three?
    # - would showing the full interests (not just the top-level areas) be helpful?
    if not matching_reviewers:
        print(f"found no reviewers with matching interest for PR {number}", file=sys.stderr)
        return ReviewerSuggestion("found no reviewers with matching interest", [], [], None)
    elif len(matching_reviewers) == 1:
        handle = matching_reviewers[0][0].github
        return ReviewerSuggestion(f"{user_link(handle)}", [handle], [handle], handle)
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
            (rev, areas, existing_assignments[rev.github][1] if rev.github in existing_assignments else 0)
                for (rev, areas) in proposed_reviewers
        ]
        with_curr_assignments = sorted(with_curr_assignments, key=lambda s: s[2])
        # FIXME: refine which information is actually useful here.
        # Or also show information if a single (and the PR's only) area matches?
        formatted = ", ".join([
            user_link(rev.github, f"relevant area(s) of competence: {', '.join(areas)}{f'; comments: {rev.comment}' if rev.comment else ''}; {n} (weighted) open assigned PRs(s)")
            for (rev, areas, n) in with_curr_assignments
        ])
        suggested_reviewers = [rev.github for (rev, _areas, _n_weighted) in with_curr_assignments]
        # Future: replace 10 by rev.maximum_capacity and take "is on the rotation" into account
        available_with_weights = [(rev.github, 10 - n_weighted) for (rev, _areas, n_weighted) in with_curr_assignments if n_weighted <= 10]
        all_available_reviewers = [rev for (rev, _n) in available_with_weights]
        chosen_reviewer = None
        if all_available_reviewers:
            import random
            chosen_reviewer = random.choices(all_available_reviewers, weights=[n for (rev, n) in available_with_weights], k=1)[0]
        return ReviewerSuggestion(formatted, suggested_reviewers, all_available_reviewers, chosen_reviewer)


# Suggest reviewers for a list of PRs: these are traversed in order, and for each PR a list
# of possible reviewers is created. This takes a maximum review capacity into account.
# Return a dictionary (pr_number: proposed reviewers).
def suggest_reviewers_many(
    existing_assignments: dict[str, Tuple[List[int], float, int]], reviewers: List[ReviewerInfo], prs_to_assign: List[int], info: dict[int, AggregatePRInfo]
) -> dict[int, List[str]]:
    suggestions = {}
    for number in prs_to_assign:
        # TODO: filter these by a maximum review capacity, perhaps hard-coded to 10 PRs?
        suggestions[number] = suggest_reviewers(existing_assignments, reviewers, number, info[number], info).all_potential_reviewers
    return suggestions
