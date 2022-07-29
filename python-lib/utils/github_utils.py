import github
from github import RateLimitExceededException
import logging
import time
from datetime import datetime

MAX_NUMBER_OF_FETCH_ATTEMPT_TO_BYPASS_RATE_LIMIT = 2


def parse_user(user_object):
    return user_object["login"]


def build_unique_id(issue):
    return "{} linked to {}".format(issue["id"], issue["user_handle"])


def to_rate_limit_dict(rate_limit):
    return {
        "limit": rate_limit.limit,
        "remaining": rate_limit.remaining,
        "reset": rate_limit.reset
    }


def get_github_client(config, preset_id="personal_access_token_credentials_preset"):
    access_token = config[preset_id]["personal_access_token_credentials_parameter_set"]
    return github.Github(login_or_token=access_token)


def fetch_issues(query_date, github_client, search_query, records_limit, fetch_requested_reviewers=False,
                 compute_comment_count=False, link_to_users=None, user_handle=None, unique_issues_ids=[],
                 current_attempt=1):
    current_number_of_fetched_issues = 0
    columns_to_keep = ["title", "html_url", "id", "number", "state", "created_at", "labels", "milestone", "pull_request"]
    results = []
    try:
        logging.info("Fetching Issues corresponding to search query '{}'".format(search_query))
        for issue in github_client.search_issues(query=search_query):
            if 0 <= records_limit <= current_number_of_fetched_issues:
                logging.info("Reached records_limit ({}), stopping inserting new records in dataset.".format(
                    records_limit
                ))
                break
            issue_raw_data = issue._rawData
            result = {"query_date": query_date}
            for column_to_keep in columns_to_keep:
                result[column_to_keep] = issue_raw_data[column_to_keep]
            result["author"] = parse_user(issue_raw_data["user"])
            if user_handle is not None:
                result["user_handle"] = user_handle
                unique_id = build_unique_id(result)
                if unique_id in unique_issues_ids:
                    logging.info("Skipping already processed issue '{}'.".format(unique_id))
                    continue
                unique_issues_ids.append(unique_id)
            if link_to_users is not None:
                result["link_to_user"] = link_to_users
            if fetch_requested_reviewers:
                pull_request = issue.as_pull_request()
                # Tuple where user is first
                result["requested_reviewers"] = \
                    [{"name": user.name, "login": user.login} for user in pull_request.get_review_requests()[0]]
                if compute_comment_count:
                    result["comments"] = pull_request.comments + pull_request.review_comments
            results.append(result)
            current_number_of_fetched_issues += 1
    except RateLimitExceededException as rate_limit_exceeded_exception:
        logging.error(rate_limit_exceeded_exception)
        now = datetime.utcnow()
        search_rate_limit = github_client.get_rate_limit().search
        logging.info("Data only partially fetched for attempt {}. Rate limits: {}. Current time: {}".format(
            current_attempt,
            to_rate_limit_dict(search_rate_limit),
            now
        ))
        if current_attempt <= MAX_NUMBER_OF_FETCH_ATTEMPT_TO_BYPASS_RATE_LIMIT:
            seconds_before_reset = (search_rate_limit.reset - now).total_seconds() + 1
            logging.info(
                "Sleeping {} seconds before fetching data again due to rate limits (attempt number {})".format(
                    seconds_before_reset, current_attempt
                )
            )
            time.sleep(seconds_before_reset)
            return fetch_issues(query_date, github_client, search_query, records_limit, fetch_requested_reviewers,
                                compute_comment_count, link_to_users, user_handle, unique_issues_ids, ++current_attempt)
        else:
            logging.info("Could not fetch result due to rate limits even after {} attempts.".format(current_attempt))
            raise rate_limit_exceeded_exception

    return results
