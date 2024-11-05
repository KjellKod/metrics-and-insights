import argparse
from collections import defaultdict
from datetime import datetime
from jira_utils import get_tickets_from_jira

# Global variable for verbosity
VERBOSE = False
EXCEPTIONS = ["ENG-8158"]


def exceptions_check(ticket_key):
    return ticket_key in EXCEPTIONS


def parse_arguments():
    # Define the argument parser
    # pylint: disable=global-statement
    global VERBOSE
    parser = argparse.ArgumentParser(description="Process some tickets.")
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Enable verbose output"
    )
    args = parser.parse_args()
    VERBOSE = args.verbose


def verbose_print(message):
    if VERBOSE:
        print(message)


def extract_linked_tickets(issue):
    linked_keys = []
    for link in issue.fields.issuelinks:
        if hasattr(link, "outwardIssue"):
            linked_keys.append(link.outwardIssue.key)
    return linked_keys


def count_failed_releases(issue):
    release_events = []
    last_released_index = None

    # Reverse the order of histories to process from oldest to most recent
    for history in reversed(issue.changelog.histories):
        for item in history.items:
            # print all item information
            if item.field == "status":
                verbose_print(
                    f"{issue.key} {item.field}, from: {item.fromString} --> {item.toString}"
                )
                if item.toString == "Released":
                    release_date = datetime.strptime(
                        history.created, "%Y-%m-%dT%H:%M:%S.%f%z"
                    )
                    release_events.append((release_date, False))
                    last_released_index = len(release_events) - 1
                if item.fromString == "Released" and item.toString != "Released":
                    if last_released_index is not None:
                        release_events[last_released_index] = (
                            release_events[last_released_index][0],
                            True,
                        )
                        last_released_index = (
                            None  # Reset the index after marking as failed
                        )

    # Check for exceptions
    if exceptions_check(issue.key):
        for i in range(len(release_events)):
            release_events[i] = (release_events[i][0], False)

    fail_count = sum(1 for _, failed in release_events if failed)
    return fail_count, release_events


def analyze_release_tickets(start_date, end_date):
    jql_query = f"project IN (ENG, ONF) AND summary ~ 'Production Release' AND type = 'Release' AND status changed to Released during ({start_date}, {end_date}) ORDER BY created ASC"
    release_tickets = get_tickets_from_jira(jql_query)
    (
        release_info,
        failed_releases_per_month,
        failed_releaselinked_tickets_count_per_month,
        total_linked_tickets_count_per_month,
        total_releases_per_month,
        exceptions,
    ) = process_release_tickets(release_tickets)
    print_release_info(
        release_info,
        failed_releases_per_month,
        failed_releaselinked_tickets_count_per_month,
        total_linked_tickets_count_per_month,
        total_releases_per_month,
    )
    print_total_failure_percentage(total_releases_per_month, failed_releases_per_month)
    print_exceptions(exceptions)


def process_release_tickets(release_tickets):
    release_info = defaultdict(list)
    failed_releases_per_month = defaultdict(int)
    failed_releaselinked_tickets_count_per_month = defaultdict(
        int
    )  # To store the total linked tickets considering multiple failures
    total_linked_tickets_count_per_month = defaultdict(int)
    total_releases_per_month = defaultdict(int)
    exceptions = []

    for ticket in release_tickets:
        linked_tickets = extract_linked_tickets(ticket)
        _, release_events = count_failed_releases(ticket)
        if exceptions_check(ticket.key):
            exceptions.append(ticket.key)

        # Sort release events by date
        release_events.sort(key=lambda x: x[0])

        for release_date, failed in release_events:
            month_key = release_date.strftime("%Y-%m")
            release_info[month_key].append(
                {
                    "release_ticket": ticket.key,
                    "release_date": release_date.strftime("%Y-%m-%d"),
                    "linked_tickets": linked_tickets,
                    "failed": failed,
                }
            )
            total_releases_per_month[
                month_key
            ] += 1  # Increment total releases for the month
            total_linked_tickets_count_per_month[month_key] += len(
                linked_tickets
            )  # Increment total linked tickets for the month
            if failed:
                failed_releases_per_month[month_key] += 1
                failed_releaselinked_tickets_count_per_month[month_key] += len(
                    linked_tickets
                )

    return (
        release_info,
        failed_releases_per_month,
        failed_releaselinked_tickets_count_per_month,
        total_linked_tickets_count_per_month,
        total_releases_per_month,
        exceptions,
    )


def print_release_info(
    release_info,
    failed_releases_per_month,
    failed_releaselinked_tickets_count_per_month,
    total_linked_tickets_count_per_month,
    total_releases_per_month,
):
    # Print the collected information
    for month in sorted(release_info.keys()):
        print(f"Month: {month}")
        for info in sorted(release_info[month], key=lambda x: x["release_date"]):
            fail_message = "FAILED RELEASE  " if info["failed"] else "RELEASE\t\t"
            if VERBOSE:
                verbose_print(
                    f"{fail_message} {info['release_ticket']} [{info['release_date']}], Linked Tickets: {len(info['linked_tickets'])} ({', '.join(info['linked_tickets'])})"
                )
            else:
                print(
                    f"{fail_message} {info['release_ticket']} [{info['release_date']}]"
                )
        total_releases = total_releases_per_month[month]
        failed_releases = failed_releases_per_month[month]
        failure_percentage = (
            (failed_releases / total_releases) * 100 if total_releases > 0 else 0
        )
        print(
            f"Total of {total_releases} releases for {month}, number of failed: {failed_releases}"
        )
        print(
            f"Total released tickets {total_linked_tickets_count_per_month[month]}, total failed release linked tickets: {failed_releaselinked_tickets_count_per_month[month]}"
        )
        print(f"Release Failure Percentage for {month}: {failure_percentage:.2f}%")
        print(
            f"Release Failure Linked Tickets Percentage for {month}: {(failed_releaselinked_tickets_count_per_month[month] / total_linked_tickets_count_per_month[month]) * 100:.2f}%"
        )
        print("---")


def print_total_failure_percentage(total_releases_per_month, failed_releases_per_month):
    total_releases_all_time = sum(total_releases_per_month.values())
    total_failed_releases_all_time = sum(failed_releases_per_month.values())
    total_failure_percentage = (
        (total_failed_releases_all_time / total_releases_all_time) * 100
        if total_releases_all_time > 0
        else 0
    )
    print(
        f"\nTotal release failure percentage for the whole time period: {total_failure_percentage:.2f}%"
    )


def print_exceptions(exceptions):
    if exceptions:
        print(
            f"\n* Releases that were wrongly tagged as failed and corrected in this script were: {', '.join(exceptions)}"
        )


def main():
    parse_arguments()
    current_year = datetime.now().year
    start_date = f"{current_year}-01-01"
    end_date = f"{current_year}-12-31"
    analyze_release_tickets(start_date, end_date)


if __name__ == "__main__":
    main()
