"""GitLab issue tracker integration."""

import click
import gitlab
from azure.devops.connection import Connection
from azure.devops.exceptions import AzureDevOpsClientError
from msrest.authentication import BasicAuthentication
from azure.devops.v7_1.work_item_tracking import Wiql

from gibr.issue import Issue
from gibr.notify import error
from gibr.registry import register_tracker
from gibr.trackers.base import IssueTracker


@register_tracker(
    key="azure",
    display_name="AzureDevOps",
)
class AzureTracker(IssueTracker):
    """Azure issue tracker using python-gitlab."""

    def __init__(self, url: str, token: str, project: str, team: str):
        """Initialize AzureTracker with connection to specified project."""
        self.url = url
        self.project_name = project
        self.team_name = team
        try:
            credentials = BasicAuthentication('', token)
            connection = Connection(base_url=url, creds=credentials)

            self.wit_client = connection.clients.get_work_item_tracking_client()
        except Exception as e:
            raise ValueError(f"Failed to connect to Azure: {e}")

    @classmethod
    def configure_interactively(cls) -> dict:
        """Interactively prompt user for Azure configuration."""
        url = click.prompt(
            "Azure base URL (e.g. https://dev.azure.com/YOURORG)", default="https://dev.azure.com/YOURORG"
        )
        project = click.prompt("Azure project name (e.g. project)")
        token_var = click.prompt(
            "Environment variable for your Azure PAT", default="AZURE_PAT"
        )
        team = click.prompt(
            "Team name", default=""
        )
        cls.check_token(token_var)
        return {
            "url": url,
            "project": project,
            "team": team,
            "token": f"${{{token_var}}}",
        }

    @classmethod
    def from_config(cls, config):
        """Create GitlabTracker from config dictionary."""
        try:
            url = config["url"]
            token = config["token"]
            project = config["project"]
            team = config["team"]
        except KeyError as e:
            raise ValueError(f"Missing key in 'gitlab' config: {e.args[0]}")
        return cls(url=url, token=token, project=project, team=team)

    @classmethod
    def describe_config(cls, config: dict) -> str:
        """Return a short string describing the config."""
        return f"""GitLab:
            URL                : {config.get("url")}
            Project            : {config.get("project")}
            Token              : {config.get("token")}"""

    def get_issue(self, issue_id: str) -> dict:
        pass
        try:
            issue = self.wit_client.get_work_item(int(issue_id))
        except AzureDevOpsClientError:
            error(f"Issue #{issue_id} not found in Azure project {self.project_name} for team {self.team_name}.")
        return Issue(id=issue.id, title=issue.fields['System.Title'], type=issue.fields['System.WorkItemType'])

    def list_issues(self) -> list[dict]:
        """List all open issues in the project."""
        wiql = Wiql(
            query=f"""
            select [System.Id]
            from WorkItems
            where [System.IterationPath] = @CurrentIteration('[{self.project_name}]\{self.team_name}') AND 
            [System.AssignedTo] = @Me AND
            ([System.WorkItemType] = 'Product Backlog Item' OR  [System.WorkItemType] = 'Feature' OR
             [System.WorkItemType] = 'Epic' OR [System.WorkItemType] = 'Task' OR [System.WorkItemType] = 'Bug') AND
            NOT ([System.State] = 'Done' OR [System.State] = 'Removed' OR [System.State] = 'Closed')
            order by [System.ChangedDate] desc"""
        )
        # We limit number of results to 30 on purpose
        wiql_results = self.wit_client.query_by_wiql(wiql).work_items
        if wiql_results:
            issues = (
                self.wit_client.get_work_item(int(res.id)) for res in wiql_results
            )
        return [Issue(id=issue.id, title=issue.fields['System.Title'], type=issue.fields['System.WorkItemType']) for issue in issues]
