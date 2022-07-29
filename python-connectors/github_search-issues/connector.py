from dataiku.connector import Connector
import datetime
from utils import get_github_client, fetch_issues


class GithubSearchIssuesConnector(Connector):

    def __init__(self, config, plugin_config):
        Connector.__init__(self, config, plugin_config)

        self.github_client = get_github_client(config)
        self.search_query = config["search_query"]

    def get_read_schema(self):
        # Let DSS infer the schema from the columns returned by the generate_rows method
        return None

    def generate_rows(self, dataset_schema=None, dataset_partitioning=None,
                      partition_id=None, records_limit=-1):
        query_date = datetime.datetime.now()
        for issue in fetch_issues(query_date, self.github_client, self.search_query, records_limit):
            yield issue
