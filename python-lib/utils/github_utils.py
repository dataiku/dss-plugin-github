import github
from github import RateLimitExceededException, GithubException
import logging
import time
from email.utils import parsedate_to_datetime
import math

MAX_NUMBER_OF_FETCH_ATTEMPT_TO_BYPASS_RATE_LIMIT = 10
COSTLY_COMMENTS_FIELD = "comments"
COSTLY_FIELDS = ("merged", "requested_reviewers", "requested_teams", "merged_at",
                 COSTLY_COMMENTS_FIELD, "base_branch:base.ref", "head_branch:head.ref")
COSTLY_FIELD_NAMES = tuple(field.split(":", 1)[0] for field in COSTLY_FIELDS)
RATE_LIMIT_HEADERS = ("retry-after", "x-ratelimit-remaining", "x-ratelimit-reset")


def get_github_client(config, preset_id="personal_access_token_credentials_preset"):
    access_token = config[preset_id]["personal_access_token_credentials_parameter_set"]
    return github.Github(login_or_token=access_token)


def fetch_issues(query_date, github_client, search_query, records_limit,
                 enable_auto_retry=False, number_of_fetch_retry=0,
                 fetch_additional_costly_fields=False,
                 link_to_users=None, user_handle=None, unique_issues_ids=[]):
    max_attempts = _max_attempts(enable_auto_retry, number_of_fetch_retry)
    secondary_failures = 0
    for attempt in range(1, max_attempts + 1):
        current_number_of_fetched_issues = len(unique_issues_ids)
        results = []
        new_unique_issues_ids = []
        try:
            logging.info("Fetching Issues corresponding to search query '%s' %s", search_query,
                         _build_retry_log(attempt, enable_auto_retry, number_of_fetch_retry))
            searched_issues = github_client.search_issues(query=search_query)
            for issue in searched_issues:
                if records_limit != -1 and 0 <= records_limit <= current_number_of_fetched_issues:
                    logging.info("Limit of %s reached.", records_limit)
                    break
                new_record = _build_base_issue_record(issue, query_date)
                issue_already_processed = _handle_user_link(new_record, user_handle, link_to_users,
                                                             unique_issues_ids, new_unique_issues_ids)
                if issue_already_processed:
                    continue
                _fetch_costly_fields_with_retry(fetch_additional_costly_fields, issue, new_record,
                                                enable_auto_retry, number_of_fetch_retry)
                results.append(new_record)
                current_number_of_fetched_issues += 1
        except GithubException as fetch_exception:
            kind, headers = _classify_failure(fetch_exception)
            if kind is None:
                logging.exception("Unexpected GitHub search failure; propagating error")
                raise
            if attempt >= max_attempts:
                logging.exception("GitHub search retries disabled or exhausted (attempt %s/%s, %s); propagating error",
                                  attempt, max_attempts, kind)
                raise
            secondary_failures = secondary_failures + 1 if kind in ("secondary", "ambiguous") else 0
            _wait_before_retry(fetch_exception, kind, headers, secondary_failures, attempt, max_attempts, "search")
            continue
        except Exception:
            logging.exception("Unexpected error while fetching issues; propagating error")
            raise
        unique_issues_ids.extend(new_unique_issues_ids)
        return results


def _max_attempts(enable_auto_retry, number_of_fetch_retry):
    if not enable_auto_retry or number_of_fetch_retry == 0:
        return 1
    if number_of_fetch_retry == -1:
        return MAX_NUMBER_OF_FETCH_ATTEMPT_TO_BYPASS_RATE_LIMIT
    return max(1, number_of_fetch_retry)


def _build_retry_log(attempt_number, retry_boolean, max_retry):
    return "(attempt {attempt_number}, auto retry {retry_boolean}, max number of retry {max_retry})".format(
        attempt_number=attempt_number, retry_boolean=retry_boolean, max_retry=max_retry)


def _fetch_costly_fields_with_retry(fetch_additional_costly_fields, issue, new_record,
                                    enable_auto_retry, number_of_fetch_retry):
    if not fetch_additional_costly_fields:
        return
    new_record.update({name: None for name in COSTLY_FIELD_NAMES})
    max_attempts = _max_attempts(enable_auto_retry, number_of_fetch_retry)
    secondary_failures = 0
    for attempt in range(1, max_attempts + 1):
        costly_fields = {}
        try:
            _handle_costly_fields(issue, costly_fields)
            new_record.update(costly_fields)
            return
        except GithubException as error:
            kind, headers = _classify_failure(error)
            if kind not in ("primary", "secondary", "ambiguous"):
                logging.exception("Optional fields failed with a non-rate-limit GitHub error; keeping base record")
                return
            if attempt >= max_attempts:
                logging.exception("Optional-field rate-limit retries disabled or exhausted (attempt %s/%s); keeping base record",
                                  attempt, max_attempts)
                return
            secondary_failures = secondary_failures + 1 if kind in ("secondary", "ambiguous") else 0
            _wait_before_retry(error, kind, headers, secondary_failures, attempt, max_attempts, "optional fields")
        except Exception:
            logging.exception("Optional fields failed unexpectedly; keeping base record")
            return


def _classify_failure(exc):
    raw = getattr(exc, "headers", None)
    headers = {str(k).lower(): str(v) for k, v in raw.items() if str(k).lower() in RATE_LIMIT_HEADERS} if hasattr(raw, "items") else {}
    data = getattr(exc, "data", None)
    message = data.get("message", "") if isinstance(data, dict) else ""
    message = message if isinstance(message, str) else ""
    normalized_message = message.lower()
    status = getattr(exc, "status", None)
    limited = (isinstance(exc, RateLimitExceededException) or status == 429 or
               (status == 403 and ("rate limit" in normalized_message or
                headers.get("x-ratelimit-remaining") == "0" or "retry-after" in headers)))
    if limited:
        if "secondary" in normalized_message or "abuse" in normalized_message:
            kind = "secondary"
        else:
            kind = "primary" if headers.get("x-ratelimit-remaining") == "0" else "ambiguous"
    else:
        kind = "transient" if status in (502, 503, 504) else None
    logging.info("GitHub failure: status=%s message=%s headers=%s rate_limited=%s classification=%s",
                 status, message, headers, limited, kind)
    return kind, headers


def _parse_nonnegative_header_number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def _retry_delay(kind, headers, secondary_failures, now):
    if kind == "transient":
        logging.info("Transient GitHub error: retrying in 5 seconds")
        return 5
    retry_after = _parse_nonnegative_header_number(headers.get("retry-after"))
    if retry_after is None and headers.get("retry-after"):
        try:
            parsed = parsedate_to_datetime(headers["retry-after"])
            if parsed.tzinfo is not None:
                retry_after = max(0, parsed.timestamp() - now)
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    reset = _parse_nonnegative_header_number(headers.get("x-ratelimit-reset"))
    if retry_after is not None:
        minimum, reason = retry_after, "Retry-After"
    elif headers.get("x-ratelimit-remaining") == "0" and reset is not None:
        minimum, reason = max(0, reset - now) + 5, "rate-limit reset plus five seconds"
    else:
        minimum, reason = 60, "fallback"
    if kind in ("secondary", "ambiguous"):
        backoff = 60 * 2 ** min(max(secondary_failures - 1, 0), 5)
        delay = max(minimum, backoff)
        logging.info("Rate-limit delay: %s=%s seconds, %s backoff=%s seconds; retrying in %s seconds",
                     reason, minimum, kind, backoff, delay)
        return delay
    logging.info("Rate-limit delay: %s; retrying in %s seconds", reason, minimum)
    return minimum


def _wait_before_retry(error, kind, headers, secondary_failures, attempt, max_attempts, scope):
    delay = _retry_delay(kind, headers, secondary_failures, time.time())
    logging.warning("GitHub %s failure: status=%s classification=%s headers=%s attempt=%s/%s; sleeping %s seconds before retry",
                    scope, getattr(error, "status", None), kind, headers, attempt, max_attempts, delay)
    time.sleep(delay)


def _handle_costly_fields(issue_handle, new_record):
    pull_request = issue_handle.as_pull_request()._rawData
    for field in COSTLY_FIELDS:
        if field == COSTLY_COMMENTS_FIELD:
            new_record[COSTLY_COMMENTS_FIELD] = pull_request["comments"] + pull_request["review_comments"]
        else:
            _enrich_with_column_values(pull_request, new_record, [field])


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


