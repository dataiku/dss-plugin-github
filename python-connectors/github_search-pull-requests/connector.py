from dataiku.connector import Connector
import logging
from utils import get_github_client, fetch_issues
import datetime
import json
import re


class GithubSearchPullRequestsConnector(Connector):

    @staticmethod
    def resolve_github_team_handles(github_team_handles):
        if len(github_team_handles) is 1 and re.fullmatch(r'\[.*\]', github_team_handles[0]) is not None:
            # Variable containing list of users
            return json.loads(github_team_handles[0])
        return github_team_handles

    @staticmethod
    def build_search_query(link_to_users, user_handle, owner, state, since_date):
        search_query = "{link_to_users}:{user_handle} user:{owner} is:pr created:>{since_date}".format(
            link_to_users=link_to_users,
            user_handle=user_handle,
            owner=owner,
            since_date=since_date
        )
        if state in ["open", "closed"]:
            return "{} state:{}".format(search_query, state)
        return search_query

    def __init__(self, config, plugin_config):
        Connector.__init__(self, config, plugin_config)  # pass the parameters to the base class

        self.github_client = get_github_client(config)
        self.owner = config["owner"]
        self.github_team_handles = self.resolve_github_team_handles(config["github_team_handles"])
        self.link_to_users = config["link_to_users"]
        self.state = config["state"]
        self.since_date = config["since_date"]
        self.fetch_requested_reviewers = config["fetch_requested_reviewers"]
        self.fetch_merge_status = config["fetch_merge_status"]
        self.compute_comment_count = config["compute_comment_count"]
        self.fetched_issues_unique_ids = []

    def get_read_schema(self):
        # Let DSS infer the schema from the columns returned by the generate_rows method
        return None

    def generate_rows(self, dataset_schema=None, dataset_partitioning=None,
                      partition_id=None, records_limit=-1):
        remaining_records_to_fetch = records_limit
        query_date = datetime.datetime.now()
        fetched_issues = []

        if self.link_to_users in ["all", "open_by"]:
            fetched_issues = \
                self.fetch_issues_for_users("author", records_limit, remaining_records_to_fetch, query_date)

        can_add_new_records = records_limit is -1 or len(self.fetched_issues_unique_ids) < records_limit
        if can_add_new_records and self.link_to_users in ["all", "reviewed_by"]:
            remaining_records_to_fetch -= len(self.fetched_issues_unique_ids)
            fetched_issues += \
                self.fetch_issues_for_users("reviewed-by", records_limit, remaining_records_to_fetch, query_date)

        for issue in fetched_issues:
            yield issue

    def fetch_issues_for_users(self, link, records_limit, remaining_records_to_fetch, query_date):
        result = []
        for user_handle in self.github_team_handles:
            new_issues = self.fetch_issues_for_link_to_users(
                query_date, link, user_handle, remaining_records_to_fetch, records_limit
            )
            result += new_issues

            if records_limit is not -1:
                remaining_records_to_fetch -= len(new_issues)
                if remaining_records_to_fetch <= 0:
                    logging.info("Max number of record reached ({}). Stop fetching.".format(records_limit))
                    break

        return result

    def fetch_issues_for_link_to_users(self, query_date, link_to_users, user_handle, remaining_records_to_fetch, records_limit):
        search_query = self.build_search_query(link_to_users, user_handle, self.owner, self.state, self.since_date)
        logging.info("Fetching Issues corresponding to search query '{}' (remaining records to fetch: {})".format(
            search_query, remaining_records_to_fetch
        ))
        issues = fetch_issues(query_date, self.github_client, search_query, records_limit, self.fetch_merge_status,
                              self.fetch_requested_reviewers, self.compute_comment_count, link_to_users, user_handle,
                              self.fetched_issues_unique_ids)
        return issues
