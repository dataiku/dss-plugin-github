import json, datetime, logging, json, pytz
from dataiku.connector import Connector
from utils import get_github_client

COLUMNS= [
    ("number", "int"),
    ("title", "string"),
    ("nb_comments", "int"),
    ("state", "string"),
    ("assignee", "string"),
    ("created_at", "date"),
    ("updated_at", "date"),
    ("closed_at", "date"),
    ("user", "string"),
    ("labels", "string"),
    ("milestone", "string"), #, "query_date"
    ("body", "string"),
]


class GithubIssuesConnector(Connector):
    def __init__(self, config, plugin_config):
        Connector.__init__(self, config, plugin_config)
        access_token = config["personal_access_token_credentials_preset"]["personal_access_token_credentials_parameter_set"]
        gh = get_github_client(config)
        self.repos = gh.get_repo(config["repos"])

    def get_read_schema(self):
        result = { "columns" : [{"name" : x[0], "type" : x[1]} for x in COLUMNS]}
        if self.config.get('fetch_comments', False):
            result['columns'].append({
                'name':'comments_bodies',
                "type":"array", "timestampNoTzAsDate": False, "maxLength": -1,
                "arrayContent": {"type": "string", "timestampNoTzAsDate": False, "maxLength": 5000}})
        return result

    def generate_rows(self, dataset_schema=None, dataset_partitioning=None,
                      partition_id=None, records_limit = -1):

        # This connector cannot have a different schema than its fixed one
        if dataset_schema is not None:
            assert(len(self.get_read_schema()["columns"]) == len(dataset_schema["columns"]))

        logging.info("Starting Github stream with limit = %s" % records_limit)

        query_date = datetime.datetime.now()

        nb = 0

        for issue in self.repos.get_issues(state=self.config.get('state', 'all')):
            issue = self.get_issue(issue)
            issue["query_date"] = str(query_date)

            if 0 <= records_limit <= nb:
                return
            yield issue
            nb += 1

            if nb % 100 == 0:
                logging.info("Read %s issues" % nb)

    def get_issue(self,issue):
        ret= {"number": issue.number, "title": issue.title, "body": issue.body, "nb_comments": issue.comments,
              "state": issue.state}
        if issue.assignee is not None:
            ret["assignee"] = issue.assignee.login

        def astz(d):
            if d is not None:
                return d.replace(tzinfo=pytz.utc)
            else:
                return None

        ret["created_at"] = astz(issue.created_at)
        ret["updated_at"] = astz(issue.updated_at)
        ret["closed_at"] = astz(issue.closed_at)
        ret["user"] = issue.user.login
        lbls = []
        for label in issue.labels:
            lbls.append(label.name)
        ret["labels"] = json.dumps(lbls)
        milestone = issue.milestone
        if milestone is not None:
            ret["milestone"] = issue.milestone.title
        if self.config.get('fetch_comments', False):
            comments_bodies =  []
            if issue.comments > 0:
                for comment in issue.get_comments():
                    comments_bodies.append(comment.body)
            ret['comments_bodies'] = json.dumps(comments_bodies)
        return ret
