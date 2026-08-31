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
    new_unique_issues_ids = []
    try:
        logging.info(
            "Fetching Issues corresponding to search query '{}' {}".format(
                search_query,
                _build_retry_log(current_attempt, enable_auto_retry, number_of_fetch_retry))
        )
        searched_issues = github_client.search_issues(query=search_query)
        for issue in searched_issues:
            if records_limit != -1 and 0 <= records_limit <= current_number_of_fetched_issues:
                logging.info("Limit of {} reached.".format(records_limit))
                break
            new_record = _build_base_issue_record(issue, query_date)
            issue_already_processed = _handle_user_link(new_record, user_handle, link_to_users, unique_issues_ids, new_unique_issues_ids)
            if issue_already_processed:
                continue
            _handle_costly_fields(fetch_additional_costly_fields, issue, new_record)
            results.append(new_record)
            current_number_of_fetched_issues += 1
    except (GithubException, RateLimitExceededException) as fetch_exception:
        if not _is_retryable_fetch_exception(fetch_exception):
            _raise_unexpected_exception(fetch_exception)
        sleep_or_throw_because_of_retryable_fetch_failure(
            enable_auto_retry, number_of_fetch_retry, current_attempt, github_client, fetch_exception
        )
        return fetch_issues(query_date, github_client, search_query, records_limit,
                            enable_auto_retry, number_of_fetch_retry,
                            fetch_additional_costly_fields,
                            link_to_users, user_handle, unique_issues_ids, current_attempt + 1)
    except Exception as err:
        _raise_unexpected_exception(err)
    unique_issues_ids += new_unique_issues_ids
    return results


def sleep_or_throw_because_of_retryable_fetch_failure(enable_auto_retry, number_of_fetch_retry, current_attempt,
                                                      github_client, fetch_exception):
    logging.error(fetch_exception)
    now = datetime.utcnow()
    retry_log = _build_retry_log(current_attempt, enable_auto_retry, number_of_fetch_retry)
    retry_reason = _get_retry_reason(fetch_exception)
    status_code = getattr(fetch_exception, "status", "n/a")
    if retry_reason == "rate limit":
        search_rate_limit = github_client.get_rate_limit().search
        logging.info("Data only partially fetched. Retry reason: {}. Status code: {}. Rate limits: {}. Current time: {} {}".format(
            retry_reason, status_code, _to_rate_limit_dict(search_rate_limit), now, retry_log
        ))
    else:
        logging.info("Data only partially fetched. Retry reason: {}. Status code: {}. Current time: {} {}".format(
            retry_reason, status_code, now, retry_log
        ))
    infinite_retry = enable_auto_retry and number_of_fetch_retry == -1
    disable_auto_retry = not enable_auto_retry or number_of_fetch_retry == 0
    if disable_auto_retry or (not infinite_retry and current_attempt >= number_of_fetch_retry):
        logging.info("Could not fetch result due to {} (status {}) even after {}.".format(
            retry_reason, status_code, retry_log
        ))
        raise fetch_exception

    if retry_reason == "rate limit":
        seconds_before_reset = (search_rate_limit.reset - now).total_seconds() + 5
    else:
        # A 502/503/504 from GitHub search is a transient upstream failure. Retrying is safe because
        # the connector is read-only and the existing retry controls still bound the behavior.
        seconds_before_reset = 5
    logging.info("Sleeping {} seconds before next attempt to fetch data after {} (status {}).".format(
        seconds_before_reset, retry_reason, status_code
    ))
    time.sleep(seconds_before_reset)


def _build_retry_log(attempt_number, retry_boolean, max_retry):
    return "(attempt {attempt_number}, auto retry {retry_boolean}, max number of retry {max_retry})".format(
        attempt_number=attempt_number, retry_boolean=retry_boolean, max_retry=max_retry)


def _is_retryable_fetch_exception(fetch_exception):
    return _is_rate_limit_exception(fetch_exception) or _is_transient_server_failure(fetch_exception)


def _get_retry_reason(fetch_exception):
    if _is_rate_limit_exception(fetch_exception):
        return "rate limit"
    return "transient 5xx"


def _is_rate_limit_exception(fetch_exception):
    return isinstance(fetch_exception, RateLimitExceededException) or (
        isinstance(fetch_exception, GithubException) and
        fetch_exception.status == 403 and
        "rate limit" in _get_github_exception_message(fetch_exception)
    )


def _is_transient_server_failure(fetch_exception):
    return isinstance(fetch_exception, GithubException) and fetch_exception.status in [502, 503, 504]


def _get_github_exception_message(fetch_exception):
    if not isinstance(fetch_exception, GithubException):
        return ""
    data = getattr(fetch_exception, "data", {})
    if isinstance(data, dict):
        return data.get("message", "").lower()
    return ""


def _handle_costly_fields(fetch_additional_costly_fields, issue_handle, new_record):
    if not fetch_additional_costly_fields:
        return
    pull_request = issue_handle.as_pull_request()._rawData
    _enrich_with_column_values(pull_request, new_record, ["merged", "requested_reviewers", "requested_teams", "merged_at"])
    new_record["comments"] = pull_request["comments"] + pull_request["review_comments"]
    _enrich_with_column_values(pull_request, new_record, ["target_branch:base.ref", "source_branch:head.ref"])


def _handle_user_link(new_record, user_handle, link_to_user, unique_issues_ids, new_unique_issues_ids):
    if user_handle is None:
        return False

    unique_id = _build_unique_id(new_record["id"], user_handle)

    issue_already_processed = unique_id in unique_issues_ids

    if issue_already_processed:
        logging.info("Already processed issue '{}'.".format(unique_id))
        return True

    new_unique_issues_ids.append(unique_id)
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
        if ":" in column_name:
            column_label, column_path = column_name.split(":", 1)
        else:
            column_label = column_path = column_name

        column_value = record_raw_data
        for column_part in column_path.split("."):
            column_value = column_value.get(column_part, {})
        record_to_enrich[column_label] = column_value


def _raise_unexpected_exception(unexpected_exception):
    logging.error("An unexpected exception occurred while fetching issues: %s", unexpected_exception)
    raise unexpected_exception
