import github
from github import RateLimitExceededException, GithubException
import logging
import time
from datetime import datetime

MAX_NUMBER_OF_FETCH_ATTEMPT_TO_BYPASS_RATE_LIMIT = 2


def get_github_client(config, preset_id="personal_access_token_credentials_preset"):
    access_token = config[preset_id]["personal_access_token_credentials_parameter_set"]
    return github.Github(login_or_token=access_token)


def fetch_issues(query_date, github_client, search_query, records_limit,
                 enable_auto_retry=False, number_of_fetch_retry=0,
                 fetch_additional_costly_fields=False,
                 link_to_users=None, user_handle=None, unique_issues_ids=[], current_attempt=1):
    current_number_of_fetched_issues = len(unique_issues_ids)
    results = []
    try:
        logging.info(
            "Fetching Issues corresponding to search query '{}' {}".format(
                search_query,
                _build_retry_log(current_attempt, enable_auto_retry, number_of_fetch_retry))
        )
        searched_issues = github_client.search_issues(query=search_query)
        for issue in searched_issues:
            if records_limit is not -1 and 0 <= records_limit <= current_number_of_fetched_issues:
                logging.info("Limit of {} reached.".format(records_limit))
                break
            new_record = _build_base_issue_record(issue, query_date)
            issue_already_processed = _handle_user_link(new_record, user_handle, link_to_users, unique_issues_ids)
            if issue_already_processed:
                continue
            _handle_costly_fields(fetch_additional_costly_fields, issue, new_record)
            results.append(new_record)
            current_number_of_fetched_issues += 1
    except (GithubException, RateLimitExceededException) as rate_limit_exceeded_exception:
        if isinstance(rate_limit_exceeded_exception, GithubException) and not \
                        (rate_limit_exceeded_exception.status == 403 and
                         "rate limit" in rate_limit_exceeded_exception.data.get('message', '')):
            _raise_unexpected_exception(rate_limit_exceeded_exception)
        sleep_or_throw_because_of_rate_limit(
            enable_auto_retry, number_of_fetch_retry, current_attempt, github_client, rate_limit_exceeded_exception
        )
        return fetch_issues(query_date, github_client, search_query, records_limit,
                            enable_auto_retry, number_of_fetch_retry,
                            fetch_additional_costly_fields,
                            link_to_users, user_handle, unique_issues_ids, current_attempt + 1)
    except Exception as err:
        _raise_unexpected_exception(err)
    return results


def sleep_or_throw_because_of_rate_limit(enable_auto_retry, number_of_fetch_retry, current_attempt, github_client,
                                         rate_limit_exceeded_exception):
    logging.error(rate_limit_exceeded_exception)
    now = datetime.utcnow()
    search_rate_limit = github_client.get_rate_limit().search
    retry_log = _build_retry_log(current_attempt, enable_auto_retry, number_of_fetch_retry)
    logging.info("Data only partially fetched. Rate limits: {}. Current time: {} {}".format(
        _to_rate_limit_dict(search_rate_limit), now, retry_log
    ))
    infinite_retry = enable_auto_retry and number_of_fetch_retry is -1
    disable_auto_retry = not enable_auto_retry or number_of_fetch_retry is 0
    if disable_auto_retry or (not infinite_retry and current_attempt >= number_of_fetch_retry):
        logging.info("Could not fetch result due to rate limits even after {}.".format(retry_log))
        raise rate_limit_exceeded_exception

    seconds_before_reset = (search_rate_limit.reset - now).total_seconds() + 5
    logging.info("Sleeping {} seconds before next attempt to fetch data.".format(seconds_before_reset))
    time.sleep(seconds_before_reset)


def _build_retry_log(attempt_number, retry_boolean, max_retry):
    return "(attempt {attempt_number}, auto retry {retry_boolean}, max number of retry {max_retry})".format(
        attempt_number=attempt_number, retry_boolean=retry_boolean, max_retry=max_retry)


def _handle_costly_fields(fetch_additional_costly_fields, issue_handle, new_record):
    if not fetch_additional_costly_fields:
        return
    pull_request = issue_handle.as_pull_request()._rawData
    _enrich_with_column_values(pull_request, new_record, ["merged", "requested_reviewers", "requested_teams"])
    new_record["comments"] = pull_request["comments"] + pull_request["review_comments"]


def _handle_user_link(new_record, user_handle, link_to_user, unique_issues_ids):
    if user_handle is None:
        return False

    unique_id = _build_unique_id(new_record["id"], user_handle)

    issue_already_processed = unique_id in unique_issues_ids

    if issue_already_processed:
        logging.info("Already processed issue '{}'.".format(unique_id))
        return True

    unique_issues_ids.append(unique_id)
    new_record["user_handle"] = user_handle
    new_record["link_to_user"] = link_to_user
    return False


def _parse_user(user_object):
    return user_object["login"]


def _build_unique_id(issue_id, user_handle):
    return "{} linked to {}".format(issue_id, user_handle)


def _to_rate_limit_dict(rate_limit):
    return {
        "limit": rate_limit.limit,
        "remaining": rate_limit.remaining,
        "reset": rate_limit.reset
    }


def _build_base_issue_record(raw_issue, query_date):
    issue_raw_data = raw_issue._rawData
    result = {"query_date": query_date}
    _enrich_with_column_values(
        issue_raw_data, result,
        ["title", "html_url", "id", "number", "state", "created_at", "closed_at", "labels", "milestone",
         "pull_request", "draft"]
    )
    result["author"] = _parse_user(issue_raw_data["user"])
    return result


def _enrich_with_column_values(record_raw_data, record_to_enrich, column_names):
    for column_name in column_names:
        record_to_enrich[column_name] = record_raw_data[column_name]


def _raise_unexpected_exception(unexpected_exception):
    logging.error("An unexpected exception occurred while fetching issues: %s", unexpected_exception)
    raise unexpected_exception
