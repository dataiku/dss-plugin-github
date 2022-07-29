from dataiku.connector import Connector
import logging
import datetime
from utils import get_github_client


class GithubPullRequestsConnector(Connector):

    def __init__(self, config, plugin_config):
        Connector.__init__(self, config, plugin_config)  # pass the parameters to the base class

        self.github_client = get_github_client(config)
        self.pr_repository_full_names = config["repositories"]
        self.compute_comment_count = config["compute_comment_count"]
        self.state = self.config["state"]
        self.current_number_of_fetched_prs = 0

    def fetch_pull_requests(self, pr_repository_full_name):
        if not "/" in pr_repository_full_name:
            raise AttributeError("Wrong repository full name: {}".format(pr_repository_full_name))
        logging.info("Fetching PR requests from {}".format(pr_repository_full_name))
        repository = self.github_client.get_repo(pr_repository_full_name)
        result = repository.get_pulls(state=self.state)
        return result

    def get_read_schema(self):
        # Let DSS infer the schema from the columns returned by the generate_rows method
        return None

    def generate_rows(self, dataset_schema=None, dataset_partitioning=None,
                      partition_id=None, records_limit=-1):

        query_date = datetime.datetime.now()

        current_number_of_fetched_prs = 0
        columns_to_keep = ["title", "html_url", "id", "number", "state", "created_at", "labels", "user", "milestone",
                           "requested_reviewers"]
        for pr_repository_full_name in self.pr_repository_full_names:

            pull_requests_for_repository = self.fetch_pull_requests(pr_repository_full_name)
            for pull_request in pull_requests_for_repository:
                if 0 <= records_limit <= current_number_of_fetched_prs:
                    logging.info("Reached records_limit ({}), stopping inserting new records in dataset.".format(
                        records_limit
                    ))
                    return
                # Using pull_request.raw_data is very costly because it triggers a _completeIfNeeded operation.
                # To bypass this mechanism we can call the protected member directly: pull_request._rawData
                pull_request_raw_data = pull_request._rawData
                result = {"query_date": query_date}
                for column_to_keep in columns_to_keep:
                    result[column_to_keep] = pull_request_raw_data[column_to_keep]
                if self.compute_comment_count:
                    # This is a costly step
                    result["comments"] = pull_request.comments
                yield result
                current_number_of_fetched_prs += 1