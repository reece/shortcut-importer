#!/usr/bin/env python3

import functools
import logging
import os
import shelve

from .services.githubzenhub import GitHubZenHub
from .services.shortcut import EasyShortcut
import yaml

_logger = logging.getLogger(__name__)


class Importer:
    def __init__(self, config):
        self.config = config
        self.github_org = self.config["github"]["org"]
        self.gz = GitHubZenHub(github_config=config["github"], zenhub_config=config["zenhub"])
        self.sc = EasyShortcut(token=config["shortcut"]["token"])
        self.migrated = shelve.open(config["migrated_filename"])
        self.strict = True

    @functools.lru_cache(maxsize=1000)
    def _map_username(self, github_username):
        try:
            return self.config["github_shortcut_user_map"][github_username]
        except KeyError:
            if not self.strict:
                _logger.warning("GitHub user %s is unmapped" % (github_username,))
                return None
            raise

    def migrate_repo(self, repo_name):
        for issue in self.gz.fetch_issues(self.github_org, repo_name):
            issue_abbr = f"{issue.repository.organization.login}/{repo_name}#{issue.number}"
            is_epic = any(l for l in issue.labels if l.name == "Epic")
            if issue.user.login == "reece":
                continue
            if issue.html_url in self.migrated:
                _logger.debug("Skipping %s; already migrated to %s" % (issue.html_url, self.migrated[issue.html_url]))
                continue
            sc_issue = self.migrate_issue(issue)
            self.migrated[issue.html_url] = sc_issue["id"]
            if True:
                _logger.info(f"TESTING: {issue_abbr}: Migrating only one issue/epic")
                break  # testing: migrate only one issue in this repo

    def migrate_issue(self, issue):
        repo_name = issue.repository.name  # better: i.r.full_name
        is_epic = any(l for l in issue.labels if l.name == "Epic")
        _logger.info(
            "Migrating %s/%s#%s; %s w/%s comments: %s)"
            % (
                self.github_org,
                repo_name,
                issue.number,
                "Epic" if is_epic else "Story",
                issue.comments,
                issue.title,
            )
        )
        
        # todo: repo -> project
        # todo: closed_at?
        # todo: closed_by?
        
        original_comment = f"Migrated from GitHub [{self.github_org}/{repo_name}#{issue.number}]({issue.html_url})"
        body = dict(
            name=issue.title,
            description=original_comment + "\n\n---\n\n" + (issue.body or ""),
            created_at=issue.created_at,
            owners=list(filter(None, [self._map_username(a.login) for a in issue.assignees])),
            external_id=issue.html_url,
            requested_by=self._map_username(issue.user.login),
        )

        if is_epic:
            body["epic_state"] = self.config["github_shortcut_epic_state_map"][issue.state]
            epic = self.sc.create_epic(**body)
            for c in issue.get_comments():
                self.sc.create_epic_comment(
                    epic["id"],
                    author=self._map_username(c.user.login),
                    created_at=c.created_at,
                    text=c.body,
                )
            return epic

        else:  # Story
            body["state"] = self.config["github_shortcut_issue_state_map"][issue.state]
            story = self.sc.create_story(**body)
            for c in issue.get_comments():
                self.sc.create_story_comment(
                    story["id"],
                    author=self._map_username(c.user.login),
                    created_at=c.created_at,
                    text=c.body,
                )
            return story